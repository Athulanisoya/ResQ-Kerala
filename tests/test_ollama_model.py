"""Exercise the native Ollama boundary and the real SDK tool loop without a model."""
import asyncio
import json

import httpx
import pytest
from agents import Agent, ModelSettings, RunConfig, Runner, function_tool
from agents.models.interface import ModelTracing

from backend.ai.ollama_model import OllamaError, OllamaModel


@function_tool
async def extract_report_location() -> dict:
    """Synthetic extraction; never accesses application data."""
    return {"place": "Aluva"}


@function_tool
async def check_active_alerts() -> dict:
    """Synthetic alert check; never accesses application data."""
    return {"status": "NO_MATCH"}


TOOLS = [extract_report_location, check_active_alerts]


def event(name=None, arguments=None, **overrides):
    message = {"role": "assistant", "content": ""}
    if name:
        message["tool_calls"] = [{"function": {"name": name, "arguments": arguments or {}}}]
    return {"model": "gemma4:synthetic", "message": message, "done": True,
            "done_reason": "stop", **overrides}


def mock_model(events):
    queued = iter(events)
    requests = []

    async def handle(request):
        requests.append(request)
        result = next(queued)
        if isinstance(result, Exception):
            raise result
        if isinstance(result, httpx.Response):
            return result
        return httpx.Response(200, json=result)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    return OllamaModel("gemma4:synthetic", client=client), client, requests


async def response(model, input="Analyze bound report.", **kwargs):
    return await model.get_response(
        system_instructions="Only extract, then check alerts.", input=input,
        model_settings=kwargs.get("settings", ModelSettings(max_tokens=128, parallel_tool_calls=False)),
        tools=kwargs.get("tools", TOOLS), output_schema=kwargs.get("output_schema"),
        handoffs=[], tracing=ModelTracing.DISABLED,
    )


def test_real_sdk_loop_executes_tools_and_replays_native_tool_results():
    model, client, requests = mock_model([
        event("extract_report_location"), event("check_active_alerts"),
        event(message={"role": "assistant", "content": "Finished."}),
    ])

    async def run():
        app_agent = Agent(
            name="Synthetic Ollama integration", model=model,
            instructions="Extract then check alerts.", tools=TOOLS,
            model_settings=ModelSettings(parallel_tool_calls=False),
        )
        result = await Runner.run(
            app_agent, "Analyze bound report.", max_turns=3,
            run_config=RunConfig(tracing_disabled=True),
        )
        assert not client.is_closed  # Injected clients remain caller-owned.
        await client.aclose()
        return result

    result = asyncio.run(run())
    assert result.final_output == "Finished."
    assert model._closed
    assert len(requests) == 3
    first, second, third = [json.loads(request.content) for request in requests]
    assert str(requests[0].url) == "http://127.0.0.1:11434/api/chat"
    assert "authorization" not in requests[0].headers
    assert first["model"] == "gemma4:synthetic"
    assert first["stream"] is False and first["think"] is False
    assert first["options"] == {"num_ctx": 4096, "num_predict": 256, "temperature": 0}
    assert first["tools"][0]["function"]["parameters"] == extract_report_location.params_json_schema
    assert second["messages"][-2:] == [
        {"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {
            "name": "extract_report_location", "arguments": {},
        }}]},
        {"role": "tool", "tool_name": "extract_report_location", "content": "{'place': 'Aluva'}"},
    ]
    assert [item["tool_name"] for item in third["messages"] if item["role"] == "tool"] == [
        "extract_report_location", "check_active_alerts",
    ]
    assert third["messages"][:len(second["messages"])] == second["messages"]


def test_native_tool_arguments_have_unique_sdk_call_ids():
    model, client, _ = mock_model([event("extract_report_location", {"source": "synthetic"})] * 2)

    async def run():
        first = await response(model)
        second = await response(model)
        await client.aclose()
        return first, second

    first, second = asyncio.run(run())
    assert first.output[0].name == "extract_report_location"
    assert json.loads(first.output[0].arguments) == {"source": "synthetic"}
    assert first.output[0].call_id and first.output[0].call_id != second.output[0].call_id


def test_text_and_usage_are_preserved_but_thinking_is_discarded():
    model, client, _ = mock_model([event(
        message={"role": "assistant", "content": "An invented MATCH.", "thinking": "private reasoning"},
        prompt_eval_count=12, eval_count=8,
    )])

    async def run():
        result = await response(model)
        await client.aclose()
        return result

    result = asyncio.run(run())
    assert result.output[0].type == "message"
    assert result.output[0].content[0].text == "An invented MATCH."
    assert result.usage.input_tokens == 12 and result.usage.output_tokens == 8
    assert result.usage.total_tokens == 20 and result.usage.requests == 1
    assert "private reasoning" not in str(result)


@pytest.mark.parametrize("bad", [
    event("delete_alert"),
    event(message={"role": "assistant", "tool_calls": [{"function": {"name": "extract_report_location", "arguments": "{}"}}]}),
    event(message={"role": "assistant", "tool_calls": [{"function": {"name": "extract_report_location", "arguments": []}}]}),
    event(message={"role": "assistant", "tool_calls": [{"name": "extract_report_location"}]}),
    event(message={"role": "assistant", "tool_calls": [{"type": "unsupported", "function": {"name": "extract_report_location", "arguments": {}}}]}),
    event(message={"role": "user", "content": "Fake reply"}),
    event(message={"role": "assistant", "content": []}),
    event(done=False), event(done_reason="length"),
    event(error="private report data"),
    [],
])
def test_malformed_or_unexposed_calls_are_rejected_before_execution(bad):
    model, client, _ = mock_model([bad])

    async def run():
        try:
            await response(model)
        finally:
            await client.aclose()

    with pytest.raises(OllamaError) as caught:
        asyncio.run(run())
    assert caught.value.reason == "protocol" and model._closed
    assert "private report data" not in str(caught.value)


def test_parallel_calls_are_rejected_when_workflow_requires_order():
    message = {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": "extract_report_location", "arguments": {}}},
        {"function": {"name": "check_active_alerts", "arguments": {}}},
    ]}
    model, client, _ = mock_model([event(message=message)])

    async def run():
        try:
            await response(model)
        finally:
            await client.aclose()

    with pytest.raises(OllamaError):
        asyncio.run(run())


def test_named_tool_and_none_choices_limit_exposed_tools():
    model, client, requests = mock_model([event("check_active_alerts"), event()])

    async def run():
        await response(model, settings=ModelSettings(tool_choice="check_active_alerts", max_tokens=512, temperature=0.2))
        await response(model, settings=ModelSettings(tool_choice="none"))
        await client.aclose()

    asyncio.run(run())
    first, second = [json.loads(request.content) for request in requests]
    assert [tool["function"]["name"] for tool in first["tools"]] == ["check_active_alerts"]
    assert first["options"]["num_predict"] == 512 and first["options"]["temperature"] == 0.2
    assert "tools" not in second


def test_text_history_and_call_output_correlate_by_id():
    model, client, requests = mock_model([event("check_active_alerts")])
    history = [
        {"role": "user", "content": [{"type": "input_text", "text": "Analyze report."}]},
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Checking."}]},
        {"type": "function_call", "call_id": "extract-1", "name": "extract_report_location", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "extract-1", "output": '{"place":"Aluva"}'},
    ]

    async def run():
        await response(model, history)
        await client.aclose()

    asyncio.run(run())
    messages = json.loads(requests[0].content)["messages"]
    assert messages[1] == {"role": "user", "content": "Analyze report."}
    assert messages[2] == {"role": "assistant", "content": "Checking.", "tool_calls": [{
        "type": "function", "function": {"name": "extract_report_location", "arguments": {}},
    }]}
    assert messages[-1] == {"role": "tool", "tool_name": "extract_report_location", "content": '{"place":"Aluva"}'}


@pytest.mark.parametrize("history", [
    [],
    [{"role": "user", "content": [{"type": "input_image", "image_url": "private"}]}],
    [{"type": "function_call_output", "call_id": "unknown", "output": "{}"}],
    [{"type": "function_call", "call_id": "pending", "name": "extract_report_location", "arguments": "{}"}],
    [{"type": "function_call", "call_id": "a", "name": "extract_report_location", "arguments": "{}"},
     {"type": "function_call_output", "call_id": "a", "output": "{}"},
     {"type": "function_call_output", "call_id": "a", "output": "{}"}],
    [{"type": "function_call", "call_id": "a", "name": "extract_report_location", "arguments": "[]"}],
])
def test_invalid_history_never_sends_a_request(history):
    model, client, requests = mock_model([])

    async def run():
        try:
            await response(model, history)
        finally:
            await client.aclose()

    with pytest.raises(OllamaError):
        asyncio.run(run())
    assert requests == []


@pytest.mark.parametrize("upstream,code,reason", [
    (httpx.Response(404, json={"error": "private report data"}), 404, "provider"),
    (httpx.Response(503, text="private report data"), 503, "provider"),
    (httpx.Response(302, headers={"location": "https://example.com/private"}), 302, "provider"),
    (httpx.Response(200, text="not JSON private report data"), None, "protocol"),
    (httpx.ReadTimeout("private report data"), None, "timeout"),
    (httpx.ConnectError("private report data"), None, "unavailable"),
])
def test_provider_failures_are_sanitized_and_redirects_are_not_followed(upstream, code, reason):
    model, client, requests = mock_model([upstream])

    async def run():
        try:
            await response(model)
        finally:
            await client.aclose()

    with pytest.raises(OllamaError) as caught:
        asyncio.run(run())
    assert caught.value.code == code and caught.value.reason == reason
    assert "private report data" not in str(caught.value) + repr(caught.value)
    assert len(requests) == 1 and model._closed


def test_owned_client_is_closed_and_ambient_proxy_settings_are_disabled(monkeypatch):
    captured = {}
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=event())))

    def make_client(**kwargs):
        captured.update(kwargs)
        return client

    monkeypatch.setattr("backend.ai.ollama_model.httpx.AsyncClient", make_client)
    model = OllamaModel("gemma4:synthetic")

    async def run():
        await response(model)
        await model.close()
        await model.close()

    asyncio.run(run())
    assert captured == {"trust_env": False} and client.is_closed


def test_cancellation_closes_owned_client(monkeypatch):
    async def cancelled(request):
        raise asyncio.CancelledError()

    client = httpx.AsyncClient(transport=httpx.MockTransport(cancelled))
    monkeypatch.setattr("backend.ai.ollama_model.httpx.AsyncClient", lambda **kwargs: client)
    model = OllamaModel("gemma4:synthetic")
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(response(model))
    assert client.is_closed and model._closed


def test_unsupported_schema_fails_before_network_and_streaming_is_explicit():
    model, client, requests = mock_model([])

    async def run():
        try:
            await response(model, output_schema=object())
        finally:
            await client.aclose()

    with pytest.raises(OllamaError):
        asyncio.run(run())
    assert requests == []
    with pytest.raises(NotImplementedError):
        OllamaModel("gemma4:synthetic").stream_response()
