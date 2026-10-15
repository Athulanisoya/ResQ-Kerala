"""Gemini Live WebSocket transport for the OpenAI Agents SDK's tool loop.

The SDK owns tool execution. This adapter only translates text and function-call
messages, keeping one Live session open across the SDK's model turns. Native
audio output is required by Flash Live; audio is discarded by this text workflow.
Protocol: https://ai.google.dev/api/live
"""
import asyncio
import json
import logging
from typing import Any
from uuid import uuid4

from agents.items import ModelResponse
from agents.models.interface import Model
from agents.tool import FunctionTool
from agents.usage import Usage
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText
from websockets.asyncio.client import connect


GEMINI_LIVE_URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)
# The WebSocket debug logger includes handshake headers. Keep credentials out of
# logs even if the application later enables root-level debug logging.
_TRANSPORT_LOGGER = logging.Logger("resq.gemini_live.transport")
_TRANSPORT_LOGGER.disabled = True


class GeminiLiveError(Exception):
    """A provider failure that never includes request data or provider messages."""

    def __init__(self, code: int | None = None):
        self.code = code if isinstance(code, int) and not isinstance(code, bool) else None
        super().__init__("The Gemini Live session could not complete the tool workflow.")


def _error_code(error: Exception) -> int | None:
    response = getattr(error, "response", None)
    code = getattr(response, "status_code", None)
    if code is None:
        code = getattr(getattr(error, "rcvd", None), "code", None)
    return code if isinstance(code, int) and not isinstance(code, bool) else None


class GeminiLiveModel(Model):
    """Single-run, non-streaming SDK model backed by Gemini's stateful Live API."""

    def __init__(self, model: str, api_key: str):
        self.model = model.removeprefix("models/")
        self._api_key = api_key
        self._ws: Any = None
        self._closed = False
        self._config: str | None = None
        self._tool_names: set[str] = set()
        self._seen_calls: set[str] = set()
        self._pending: dict[str, str] = {}
        self._completed: dict[str, Any] = {}

    async def _cleanup_on_run_end(self, owner: object) -> None:
        await self.close()

    async def close(self) -> None:
        self._closed = True
        ws, self._ws = self._ws, None
        self._api_key = ""
        if ws is not None:
            try:
                await asyncio.wait_for(ws.close(), timeout=3)
            except Exception:
                # Cleanup must not replace an SDK/tool error with provider data.
                pass

    async def get_response(
        self, system_instructions, input, model_settings, tools, output_schema,
        handoffs, tracing, *, previous_response_id=None, conversation_id=None,
        prompt=None,
    ) -> ModelResponse:
        try:
            if (self._closed or output_schema is not None or handoffs
                    or previous_response_id or conversation_id or prompt):
                raise GeminiLiveError()
            setup = self._setup(system_instructions, model_settings, tools)
            config = json.dumps(setup, sort_keys=True)
            if self._ws is None:
                turns = self._initial_turns(input)
                self._config = config
                self._ws = await connect(
                    GEMINI_LIVE_URL,
                    additional_headers={"x-goog-api-key": self._api_key},
                    open_timeout=10, close_timeout=2, max_size=1024 * 1024,
                    max_queue=16, logger=_TRANSPORT_LOGGER,
                )
                await self._send({"setup": setup})
                event = await self._receive()
                if "setupComplete" not in event:
                    raise GeminiLiveError()
                await self._send({"clientContent": {"turns": turns, "turnComplete": True}})
            else:
                if config != self._config:
                    raise GeminiLiveError()
                await self._send({"toolResponse": {"functionResponses": self._tool_responses(input)}})
            return await self._next_response()
        except asyncio.CancelledError:
            await self.close()
            raise
        except GeminiLiveError:
            await self.close()
            raise
        except Exception as error:
            await self.close()
            raise GeminiLiveError(_error_code(error)) from None

    def stream_response(self, *args, **kwargs):
        raise NotImplementedError("Gemini Live streaming is not exposed by this text tool workflow.")

    def _setup(self, system_instructions, model_settings, tools) -> dict:
        declarations = []
        names = set()
        for tool in tools:
            if not isinstance(tool, FunctionTool) or tool.name in names:
                raise GeminiLiveError()
            names.add(tool.name)
            declarations.append({
                "name": tool.name, "description": tool.description,
                "parametersJsonSchema": tool.params_json_schema,
            })
        self._tool_names = names
        generation = {"responseModalities": ["AUDIO"]}
        if model_settings.max_tokens is not None:
            generation["maxOutputTokens"] = model_settings.max_tokens
        if model_settings.temperature is not None:
            generation["temperature"] = model_settings.temperature
        setup = {
            "model": "models/" + self.model,
            "generationConfig": generation,
            "tools": [{"functionDeclarations": declarations}],
            "outputAudioTranscription": {},
        }
        if system_instructions:
            setup["systemInstruction"] = {"parts": [{"text": system_instructions}]}
        return setup

    @staticmethod
    def _initial_turns(input) -> list[dict]:
        if isinstance(input, str):
            return [{"role": "user", "parts": [{"text": input}]}]
        if not isinstance(input, list) or not input:
            raise GeminiLiveError()
        turns = []
        for item in input:
            if not isinstance(item, dict) or item.get("role") != "user":
                raise GeminiLiveError()
            content = item.get("content")
            if isinstance(content, str):
                parts = [{"text": content}]
            elif isinstance(content, list) and content:
                if any(not isinstance(part, dict) or part.get("type") != "input_text"
                       or not isinstance(part.get("text"), str) for part in content):
                    raise GeminiLiveError()
                parts = [{"text": part["text"]} for part in content]
            else:
                raise GeminiLiveError()
            turns.append({"role": "user", "parts": parts})
        return turns

    def _tool_responses(self, input) -> list[dict]:
        if not isinstance(input, list) or not self._pending:
            raise GeminiLiveError()
        responses = []
        ids = set()
        for item in input:
            if not isinstance(item, dict) or item.get("type") != "function_call_output":
                continue
            call_id = item.get("call_id")
            if not isinstance(call_id, str) or not call_id or call_id in ids or "output" not in item:
                raise GeminiLiveError()
            ids.add(call_id)
            output = item["output"]
            if call_id in self._completed:
                if self._completed[call_id] != output:
                    raise GeminiLiveError()
                continue  # Runner supplies the complete history; never resend older outputs.
            if call_id not in self._pending:
                raise GeminiLiveError()
            result = output
            if isinstance(output, str):
                try:
                    result = json.loads(output)
                except json.JSONDecodeError:
                    pass
            if not isinstance(result, dict):
                result = {"result": result}
            responses.append({"id": call_id, "name": self._pending[call_id], "response": result})
        if {response["id"] for response in responses} != set(self._pending):
            raise GeminiLiveError()
        for item in input:
            if isinstance(item, dict) and item.get("type") == "function_call_output" and item["call_id"] in self._pending:
                self._completed[item["call_id"]] = item["output"]
        self._pending.clear()
        return responses

    async def _send(self, event: dict) -> None:
        await self._ws.send(json.dumps(event, ensure_ascii=False))

    async def _receive(self) -> dict:
        event = json.loads(await self._ws.recv())
        if not isinstance(event, dict):
            raise GeminiLiveError()
        if "error" in event:
            error = event["error"]
            raise GeminiLiveError(error.get("code") if isinstance(error, dict) else None)
        if "toolCallCancellation" in event or "goAway" in event:
            raise GeminiLiveError()
        return event

    async def _next_response(self) -> ModelResponse:
        text = []
        usage = Usage(requests=1)
        while True:
            event = await self._receive()
            metadata = event.get("usageMetadata", {})
            if isinstance(metadata, dict):
                usage.input_tokens = self._token_count(metadata.get("promptTokenCount", usage.input_tokens))
                usage.output_tokens = self._token_count(metadata.get("responseTokenCount", usage.output_tokens))
                usage.total_tokens = self._token_count(metadata.get("totalTokenCount", usage.total_tokens))
            if "toolCall" in event:
                calls = event["toolCall"].get("functionCalls") if isinstance(event["toolCall"], dict) else None
                if not isinstance(calls, list) or not calls:
                    raise GeminiLiveError()
                output = []
                new_ids = set()
                for call in calls:
                    if not isinstance(call, dict):
                        raise GeminiLiveError()
                    call_id, name, args = call.get("id"), call.get("name"), call.get("args", {})
                    if (not isinstance(call_id, str) or not call_id.strip() or call_id in self._seen_calls
                            or call_id in new_ids or name not in self._tool_names or not isinstance(args, dict)):
                        raise GeminiLiveError()
                    new_ids.add(call_id)
                    output.append(ResponseFunctionToolCall(
                        type="function_call", call_id=call_id, name=name,
                        arguments=json.dumps(args, ensure_ascii=False),
                    ))
                self._seen_calls.update(new_ids)
                self._pending = {call.call_id: call.name for call in output}
                return ModelResponse(output=output, usage=usage, response_id=None)
            content = event.get("serverContent", {})
            if not isinstance(content, dict) or content.get("interrupted"):
                raise GeminiLiveError()
            transcription = content.get("outputTranscription", {})
            if isinstance(transcription, dict) and isinstance(transcription.get("text"), str):
                text.append(transcription["text"])
            # Audio bytes never leave the transport. Model text is not trusted tool evidence.
            # Live can mark an audio turn complete while background reasoning
            # continues. Wait for the actual tool call or an idle completion.
            if content.get("turnComplete") and content.get("interactionStatus") != "IN_PROGRESS":
                message = ResponseOutputMessage(
                    id="live-message-" + uuid4().hex, type="message", role="assistant", status="completed",
                    content=[ResponseOutputText(type="output_text", text="".join(text), annotations=[])],
                )
                return ModelResponse(output=[message], usage=usage, response_id=None)

    @staticmethod
    def _token_count(value) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
