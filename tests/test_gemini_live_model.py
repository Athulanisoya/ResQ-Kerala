"""Verify the actual Live transport / SDK boundary using synthetic socket events."""
import asyncio
import json

import pytest
from agents import Agent, ModelSettings, RunConfig, Runner, function_tool
from agents.models.interface import ModelTracing

from backend.ai import gemini_live_model as live


class FakeSocket:
    def __init__(self, events):
        self.events = iter(events)
        self.sent = []
        self.closed = False

    async def send(self, event):
        self.sent.append(json.loads(event))

    async def recv(self):
        event = next(self.events)
        if isinstance(event, Exception):
            raise event
        return event if isinstance(event, str) else json.dumps(event)

    async def close(self):
        self.closed = True


@function_tool
async def extract_report_location() -> dict:
    """Synthetic extraction; no application data or network access."""
    return {"place": "Aluva"}


@function_tool
async def check_active_alerts() -> dict:
    """Synthetic alert check; no application data or network access."""
    return {"status": "NO_MATCH"}


TOOLS = [extract_report_location, check_active_alerts]


def tool_call(name="extract_report_location", call_id="extract-1", args=None):
    return {"toolCall": {"functionCalls": [{"name": name, "id": call_id, "args": args or {}}]}}


def socket_model(monkeypatch, events):
    socket = FakeSocket(events)
    connections = []

    async def connect(url, **kwargs):
        connections.append((url, kwargs))
        return socket

    monkeypatch.setattr(live, "connect", connect)
    return live.GeminiLiveModel("gemini-3.1-flash-live-preview", "synthetic-private-key"), socket, connections


async def response(model, input="Analyze bound report.", **kwargs):
    return await model.get_response(
        system_instructions=kwargs.get("system_instructions", "Only extract, then check alerts."),
        input=input, model_settings=ModelSettings(max_tokens=1024, parallel_tool_calls=False),
        tools=TOOLS, output_schema=kwargs.get("output_schema"), handoffs=[],
        tracing=ModelTracing.DISABLED,
    )


def test_real_sdk_loop_sends_tool_result_in_same_session_and_closes(monkeypatch):
    model, socket, connections = socket_model(monkeypatch, [
        {"setupComplete": {}},
        tool_call(),
        tool_call("check_active_alerts", "alerts-2"),
    ])
    app_agent = Agent(
        name="Synthetic Live integration", model=model, instructions="Extract then check alerts.",
        tools=TOOLS, tool_use_behavior={"stop_at_tool_names": ["check_active_alerts"]},
    )
    result = asyncio.run(Runner.run(
        app_agent, "Analyze bound report.", max_turns=3, run_config=RunConfig(tracing_disabled=True),
    ))
    assert result.final_output == "{'status': 'NO_MATCH'}"
    assert len(connections) == 1
    url, options = connections[0]
    assert url == live.GEMINI_LIVE_URL and "?" not in url
    assert options["additional_headers"] == {"x-goog-api-key": "synthetic-private-key"}
    assert options["max_size"] == 1024 * 1024 and options["max_queue"] == 16
    assert options["logger"].disabled
    assert socket.closed and model._api_key == ""
    setup, client, tool_response = socket.sent
    assert setup["setup"]["model"] == "models/gemini-3.1-flash-live-preview"
    assert setup["setup"]["generationConfig"] == {"responseModalities": ["AUDIO"]}
    declarations = setup["setup"]["tools"][0]["functionDeclarations"]
    assert [tool["name"] for tool in declarations] == [tool.name for tool in TOOLS]
    assert declarations[0]["parametersJsonSchema"] == extract_report_location.params_json_schema
    assert client == {"clientContent": {"turns": [{"role": "user", "parts": [{"text": "Analyze bound report."}]}], "turnComplete": True}}
    assert tool_response == {"toolResponse": {"functionResponses": [{
        "id": "extract-1", "name": "extract_report_location", "response": {"result": "{'place': 'Aluva'}"},
    }]}}
    assert "synthetic-private-key" not in json.dumps(socket.sent)


def test_tool_call_ids_arguments_and_json_results_are_correlated(monkeypatch):
    model, socket, _ = socket_model(monkeypatch, [
        {"setupComplete": {}},
        tool_call(args={"source": "synthetic"}),
        tool_call("check_active_alerts", "alerts-2"),
    ])

    async def run():
        first = await response(model)
        call = first.output[0]
        assert call.call_id == "extract-1" and call.name == "extract_report_location"
        assert json.loads(call.arguments) == {"source": "synthetic"}
        second = await response(model, [
            {"role": "user", "content": "Analyze bound report."},
            {"type": "function_call", "call_id": call.call_id, "name": call.name, "arguments": call.arguments},
            {"type": "function_call_output", "call_id": call.call_id, "output": '{"place":"Aluva"}'},
        ])
        assert second.output[0].call_id == "alerts-2"
        await model.close()

    asyncio.run(run())
    assert socket.sent[-1]["toolResponse"]["functionResponses"] == [
        {"id": "extract-1", "name": "extract_report_location", "response": {"place": "Aluva"}},
    ]


@pytest.mark.parametrize("bad_call", [
    {"name": "delete_alert", "id": "evil", "args": {}},
    {"name": "extract_report_location", "args": {}},
    {"name": "extract_report_location", "id": "", "args": {}},
    {"name": "extract_report_location", "id": "  ", "args": {}},
    {"name": "extract_report_location", "id": "x", "args": "not-an-object"},
])
def test_invalid_or_unexposed_tool_calls_fail_before_execution(monkeypatch, bad_call):
    model, socket, _ = socket_model(monkeypatch, [
        {"setupComplete": {}}, {"toolCall": {"functionCalls": [bad_call]}},
    ])
    with pytest.raises(live.GeminiLiveError):
        asyncio.run(response(model))
    assert socket.closed


def test_duplicate_call_ids_in_one_event_are_rejected(monkeypatch):
    call = {"name": "extract_report_location", "id": "same", "args": {}}
    model, socket, _ = socket_model(monkeypatch, [
        {"setupComplete": {}}, {"toolCall": {"functionCalls": [call, call]}},
    ])
    with pytest.raises(live.GeminiLiveError):
        asyncio.run(response(model))
    assert socket.closed


def test_call_ids_cannot_be_reused_in_later_turn(monkeypatch):
    model, socket, _ = socket_model(monkeypatch, [{"setupComplete": {}}, tool_call(), tool_call()])

    async def run():
        await response(model)
        await response(model, [{"type": "function_call_output", "call_id": "extract-1", "output": "{}"}])

    with pytest.raises(live.GeminiLiveError):
        asyncio.run(run())
    assert socket.closed


def test_sdk_history_does_not_resend_completed_tool_outputs(monkeypatch):
    model, socket, _ = socket_model(monkeypatch, [
        {"setupComplete": {}}, tool_call(), tool_call("check_active_alerts", "alerts-2"),
        {"serverContent": {"turnComplete": True}},
    ])

    async def run():
        await response(model)
        history = [{"type": "function_call_output", "call_id": "extract-1", "output": "{}"}]
        await response(model, history)
        history.append({"type": "function_call_output", "call_id": "alerts-2", "output": '{"status":"NO_MATCH"}'})
        await response(model, history)
        await model.close()

    asyncio.run(run())
    assert len(socket.sent) == 4
    assert [call["id"] for call in socket.sent[-1]["toolResponse"]["functionResponses"]] == ["alerts-2"]


def test_changed_completed_tool_output_is_rejected(monkeypatch):
    model, socket, _ = socket_model(monkeypatch, [
        {"setupComplete": {}}, tool_call(), tool_call("check_active_alerts", "alerts-2"),
    ])

    async def run():
        await response(model)
        await response(model, [{"type": "function_call_output", "call_id": "extract-1", "output": "{}"}])
        await response(model, [
            {"type": "function_call_output", "call_id": "extract-1", "output": '{"changed":true}'},
            {"type": "function_call_output", "call_id": "alerts-2", "output": "{}"},
        ])

    with pytest.raises(live.GeminiLiveError):
        asyncio.run(run())
    assert len(socket.sent) == 3 and socket.closed


def test_live_session_configuration_cannot_change_between_sdk_turns(monkeypatch):
    model, socket, _ = socket_model(monkeypatch, [{"setupComplete": {}}, tool_call()])

    async def run():
        await response(model)
        await response(model, [{"type": "function_call_output", "call_id": "extract-1", "output": "{}"}],
                       system_instructions="Changed instructions.")

    with pytest.raises(live.GeminiLiveError):
        asyncio.run(run())
    assert len(socket.sent) == 2 and socket.closed


@pytest.mark.parametrize("outputs", [
    [],
    [{"type": "function_call_output", "call_id": "unknown", "output": "{}"}],
    [{"type": "function_call_output", "call_id": "extract-1"}],
    [{"type": "function_call_output", "call_id": "extract-1", "output": "{}"}] * 2,
])
def test_missing_unknown_or_duplicate_tool_outputs_are_rejected(monkeypatch, outputs):
    model, socket, _ = socket_model(monkeypatch, [{"setupComplete": {}}, tool_call()])

    async def run():
        await response(model)
        await response(model, outputs)

    with pytest.raises(live.GeminiLiveError):
        asyncio.run(run())
    assert len(socket.sent) == 2 and socket.closed


def test_audio_is_discarded_and_prose_remains_only_a_message(monkeypatch):
    model, socket, _ = socket_model(monkeypatch, [
        {"setupComplete": {}},
        {"serverContent": {"modelTurn": {"parts": [{"inlineData": {"data": "synthetic-audio"}}]}}},
        {"serverContent": {"outputTranscription": {"text": "An invented "}}},
        {"serverContent": {"outputTranscription": {"text": "MATCH."}, "turnComplete": True},
         "usageMetadata": {"promptTokenCount": 12, "responseTokenCount": 8, "totalTokenCount": 20}},
    ])

    async def run():
        result = await response(model)
        await model.close()
        return result

    result = asyncio.run(run())
    assert result.output[0].type == "message"
    assert result.output[0].content[0].text == "An invented MATCH."
    assert result.usage.input_tokens == 12 and result.usage.total_tokens == 20
    assert "synthetic-audio" not in str(result) and socket.closed


def test_in_progress_turn_completion_waits_for_tool_call(monkeypatch):
    model, socket, _ = socket_model(monkeypatch, [
        {"setupComplete": {}},
        {"serverContent": {"turnComplete": True, "interactionStatus": "IN_PROGRESS",
                           "outputTranscription": {"text": "Checking the report."}}},
        tool_call(),
    ])

    async def run():
        result = await response(model)
        await model.close()
        return result

    result = asyncio.run(run())
    assert result.output[0].type == "function_call"
    assert result.output[0].call_id == "extract-1"
    assert socket.closed


@pytest.mark.parametrize("event", [
    {"toolCallCancellation": {"ids": ["extract-1"]}},
    {"goAway": {"timeLeft": "0s"}},
    {"serverContent": {"interrupted": True}},
    {"error": {"code": 503, "message": "synthetic-private-key provider error"}},
    "unparseable synthetic-private-key",
    RuntimeError("synthetic-private-key transport error"),
])
def test_provider_failures_are_sanitized_and_close_socket(monkeypatch, event):
    model, socket, _ = socket_model(monkeypatch, [{"setupComplete": {}}, event])
    with pytest.raises(live.GeminiLiveError) as caught:
        asyncio.run(response(model))
    assert "synthetic-private-key" not in str(caught.value)
    assert "synthetic-private-key" not in repr(caught.value)
    if isinstance(event, dict) and "error" in event:
        assert caught.value.code == 503
    assert socket.closed


def test_setup_must_complete_before_sending_text(monkeypatch):
    model, socket, _ = socket_model(monkeypatch, [tool_call()])
    with pytest.raises(live.GeminiLiveError):
        asyncio.run(response(model))
    assert len(socket.sent) == 1 and socket.closed


def test_connection_error_exposes_only_numeric_status(monkeypatch):
    class HTTPFailure(Exception):
        response = type("Response", (), {"status_code": 403})()

    async def fail(*args, **kwargs):
        raise HTTPFailure("synthetic-private-key leaked upstream")

    monkeypatch.setattr(live, "connect", fail)
    model = live.GeminiLiveModel("gemini-3.1-flash-live-preview", "synthetic-private-key")
    with pytest.raises(live.GeminiLiveError) as caught:
        asyncio.run(response(model))
    assert caught.value.code == 403
    assert "synthetic-private-key" not in str(caught.value) and model._api_key == ""


def test_cancelled_request_closes_live_connection(monkeypatch):
    model, socket, _ = socket_model(monkeypatch, [{"setupComplete": {}}])

    async def cancelled_recv():
        raise asyncio.CancelledError()

    socket.recv = cancelled_recv
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(response(model))
    assert socket.closed


def test_schema_and_nontext_inputs_fail_without_opening_connection(monkeypatch):
    model, _, connections = socket_model(monkeypatch, [])
    with pytest.raises(live.GeminiLiveError):
        asyncio.run(response(model, output_schema=object()))
    assert connections == []
    model, _, connections = socket_model(monkeypatch, [])
    with pytest.raises(live.GeminiLiveError):
        asyncio.run(response(model, [{"role": "user", "content": [{"type": "input_audio", "data": "invalid"}]}]))
    assert connections == []


def test_adapter_streaming_is_explicitly_unsupported():
    model = live.GeminiLiveModel("gemini-3.1-flash-live-preview", "synthetic-private-key")
    with pytest.raises(NotImplementedError):
        model.stream_response()
