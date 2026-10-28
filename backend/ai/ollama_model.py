"""Native Ollama transport for the Agents SDK's local, text-only tool loop.

The SDK executes every tool. This adapter only translates messages and function
calls; model prose never becomes application tool evidence.
Protocol: https://docs.ollama.com/api/chat
"""
import asyncio
import json
from typing import Any
from uuid import uuid4

import httpx
from agents.items import ModelResponse
from agents.models.interface import Model
from agents.tool import FunctionTool
from agents.usage import Usage
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText


class OllamaError(Exception):
    """Safe provider failure: never includes report data or upstream messages."""

    def __init__(self, code: int | None = None, *, reason: str = "provider"):
        self.code = code if isinstance(code, int) and not isinstance(code, bool) else None
        self.reason = reason if reason in {"unavailable", "timeout", "provider", "protocol"} else "provider"
        super().__init__("The local Ollama model could not complete the tool workflow.")


class OllamaModel(Model):
    """Single-run, non-streaming SDK model backed by Ollama's native chat API."""

    def __init__(
        self, model: str, base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: float = 120, *, client: httpx.AsyncClient | None = None,
        context_window: int = 4096,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.context_window = context_window
        self._client = client
        self._owns_client = client is None
        self._closed = False

    async def _cleanup_on_run_end(self, owner: object) -> None:
        await self.close()

    async def close(self) -> None:
        self._closed = True
        if self._owns_client and self._client is not None:
            client, self._client = self._client, None
            try:
                await asyncio.wait_for(client.aclose(), timeout=3)
            except Exception:
                # Cleanup must not replace a safe workflow failure with transport data.
                pass

    async def get_response(
        self, system_instructions, input, model_settings, tools, output_schema,
        handoffs, tracing, *, previous_response_id=None, conversation_id=None,
        prompt=None,
    ) -> ModelResponse:
        try:
            if (self._closed or output_schema is not None or handoffs
                    or previous_response_id or conversation_id or prompt):
                raise OllamaError(reason="protocol")
            declarations = self._declarations(tools, model_settings.tool_choice)
            names = {tool["function"]["name"] for tool in declarations}
            messages = self._messages(system_instructions, input, {tool.name for tool in tools})
            payload = {
                "model": self.model, "messages": messages, "stream": False,
                "think": False, "keep_alive": "5m",
                "options": {
                    "num_ctx": self.context_window,
                    "num_predict": max(256, model_settings.max_tokens or 256),
                    "temperature": model_settings.temperature if model_settings.temperature is not None else 0,
                },
            }
            if declarations:
                payload["tools"] = declarations
            if self._client is None:
                # Do not send local requests through ambient HTTP proxy settings.
                self._client = httpx.AsyncClient(trust_env=False)
            response = await self._client.post(
                self.base_url + "/api/chat", json=payload, follow_redirects=False,
                timeout=httpx.Timeout(self.timeout_seconds, connect=min(5, self.timeout_seconds)),
            )
            if response.status_code != 200:
                raise OllamaError(response.status_code)
            return self._response(response.json(), names, model_settings.parallel_tool_calls)
        except asyncio.CancelledError:
            await self.close()
            raise
        except OllamaError:
            await self.close()
            raise
        except httpx.TimeoutException:
            await self.close()
            raise OllamaError(reason="timeout") from None
        except httpx.NetworkError:
            await self.close()
            raise OllamaError(reason="unavailable") from None
        except Exception:
            await self.close()
            raise OllamaError(reason="protocol") from None

    def stream_response(self, *args, **kwargs):
        raise NotImplementedError("Ollama streaming is not exposed by this text tool workflow.")

    @staticmethod
    def _declarations(tools, choice) -> list[dict]:
        declarations = []
        names = set()
        for tool in tools:
            if not isinstance(tool, FunctionTool) or tool.name in names:
                raise OllamaError(reason="protocol")
            names.add(tool.name)
            declarations.append({"type": "function", "function": {
                "name": tool.name, "description": tool.description,
                "parameters": tool.params_json_schema,
            }})
        if choice == "none":
            return []
        if choice not in (None, "auto", "required"):
            if not isinstance(choice, str) or choice not in names:
                raise OllamaError(reason="protocol")
            declarations = [tool for tool in declarations if tool["function"]["name"] == choice]
        return declarations

    @classmethod
    def _messages(cls, instructions, input, tool_names: set[str]) -> list[dict]:
        messages = []
        if instructions:
            if not isinstance(instructions, str):
                raise OllamaError(reason="protocol")
            messages.append({"role": "system", "content": instructions})
        if isinstance(input, str):
            return messages + [{"role": "user", "content": input}]
        if not isinstance(input, list) or not input:
            raise OllamaError(reason="protocol")
        calls: dict[str, str] = {}
        completed: set[str] = set()
        for item in input:
            if not isinstance(item, dict):
                raise OllamaError(reason="protocol")
            kind = item.get("type")
            if kind == "function_call":
                name, call_id = item.get("name"), item.get("call_id")
                if (name not in tool_names or not isinstance(call_id, str)
                        or not call_id.strip() or call_id in calls):
                    raise OllamaError(reason="protocol")
                arguments = json.loads(item["arguments"])
                if not isinstance(arguments, dict):
                    raise OllamaError(reason="protocol")
                calls[call_id] = name
                call = {"type": "function", "function": {"name": name, "arguments": arguments}}
                if messages and messages[-1]["role"] == "assistant":
                    messages[-1].setdefault("tool_calls", []).append(call)
                else:
                    messages.append({"role": "assistant", "content": "", "tool_calls": [call]})
            elif kind == "function_call_output":
                call_id = item.get("call_id")
                if (not isinstance(call_id, str) or call_id not in calls
                        or call_id in completed or "output" not in item):
                    raise OllamaError(reason="protocol")
                completed.add(call_id)
                output = item["output"]
                if not isinstance(output, str):
                    raise OllamaError(reason="protocol")
                messages.append({"role": "tool", "tool_name": calls[call_id], "content": output})
            elif kind in (None, "message") and item.get("role") in {"user", "assistant", "system", "developer"}:
                role = item["role"]
                messages.append({
                    "role": "system" if role == "developer" else role,
                    "content": cls._text(item.get("content")),
                })
            else:
                raise OllamaError(reason="protocol")
        if set(calls) != completed:
            raise OllamaError(reason="protocol")
        return messages

    @staticmethod
    def _text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list) and content:
            if all(isinstance(part, dict) and part.get("type") in {"input_text", "output_text"}
                   and isinstance(part.get("text"), str) for part in content):
                return "\n".join(part["text"] for part in content)
        raise OllamaError(reason="protocol")

    @staticmethod
    def _response(event, names: set[str], parallel_tool_calls) -> ModelResponse:
        if (not isinstance(event, dict) or event.get("error") is not None
                or event.get("done") is not True or event.get("done_reason") == "length"):
            raise OllamaError(reason="protocol")
        message = event.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise OllamaError(reason="protocol")
        text = message.get("content", "")
        calls = message.get("tool_calls", [])
        if (not isinstance(text, str) or not isinstance(calls, list)
                or (parallel_tool_calls is False and len(calls) > 1)):
            raise OllamaError(reason="protocol")
        output = []
        # Thinking content is intentionally discarded. Only visible text and actual
        # native tool-call objects are translated into SDK output items.
        if text or not calls:
            output.append(ResponseOutputMessage(
                id="ollama-message-" + uuid4().hex, type="message", role="assistant", status="completed",
                content=[ResponseOutputText(type="output_text", text=text, annotations=[])],
            ))
        for call in calls:
            function = call.get("function") if isinstance(call, dict) else None
            if (not isinstance(call, dict) or call.get("type", "function") != "function"
                    or not isinstance(function, dict) or function.get("name") not in names
                    or not isinstance(function.get("arguments"), dict)):
                raise OllamaError(reason="protocol")
            output.append(ResponseFunctionToolCall(
                type="function_call", call_id="ollama-call-" + uuid4().hex,
                name=function["name"], arguments=json.dumps(function["arguments"], ensure_ascii=False, allow_nan=False),
            ))
        input_tokens = OllamaModel._token_count(event.get("prompt_eval_count"))
        output_tokens = OllamaModel._token_count(event.get("eval_count"))
        usage = Usage(requests=1, input_tokens=input_tokens, output_tokens=output_tokens,
                      total_tokens=input_tokens + output_tokens)
        return ModelResponse(output=output, usage=usage, response_id=None)

    @staticmethod
    def _token_count(value) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
