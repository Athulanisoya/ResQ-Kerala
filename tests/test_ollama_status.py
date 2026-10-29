"""Readiness is model capability evidence, never an API-key presence check."""
import asyncio

import httpx
import pytest
from pydantic import ValidationError

from backend.ai.ollama_status import get_ollama_status
from backend.config import Settings


def settings(**overrides):
    return Settings(_env_file=None, database_url="sqlite://", allow_sqlite_for_tests=True,
                    jwt_secret="synthetic-ollama-status-secret-2026", **overrides)


def check(handler):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await get_ollama_status(settings(), client=client)
    return asyncio.run(run())


def test_status_requires_installed_model_with_tools():
    def handler(request):
        assert request.method == "POST" and request.url.path == "/api/show"
        assert request.url.host == "127.0.0.1"
        assert request.headers.get("authorization") is None
        assert request.read() == b'{"model":"gemma4:e4b-it-q4_K_M"}'
        return httpx.Response(200, json={"capabilities": ["completion", "tools", "thinking"]})
    result = check(handler)
    assert result["provider"] == "ollama"
    assert result["configured"] and result["reachable"] and result["model_available"]


@pytest.mark.parametrize("code,body,available", [
    (404, {"error": "synthetic-private-server-message"}, False),
    (200, {"capabilities": ["embedding"]}, True),
    (200, [], False),
    (200, {"capabilities": "tools"}, False),
    (503, {"error": "synthetic-private-server-message"}, False),
])
def test_status_disables_agent_for_missing_or_incompatible_models(code, body, available):
    result = check(lambda _: httpx.Response(code, json=body))
    assert result["configured"] is False
    assert result["reachable"] is True
    assert result["model_available"] is available
    assert "synthetic-private" not in str(result)


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ReadTimeout])
def test_status_handles_offline_ollama_without_leaking_error(error):
    def handler(request):
        raise error("synthetic-private-server-message", request=request)
    result = check(handler)
    assert not result["configured"] and not result["reachable"]
    assert "Start the local Ollama server" in result["reason"]
    assert "synthetic-private" not in str(result)


@pytest.mark.parametrize("url", [
    "https://ollama.com", "http://127.0.0.1.evil.example:11434", "file:///tmp/model",
    "http://user:password@localhost:11434", "http://localhost:11434/api",
    "http://localhost:11434?secret=example", "http://localhost:11434#example",
    "http://localhost:bad",
])
def test_settings_reject_nonlocal_or_credential_bearing_urls(url):
    with pytest.raises(ValidationError):
        settings(ollama_base_url=url)


@pytest.mark.parametrize("url", ["http://127.0.0.1:11434/", "http://localhost:11434", "http://[::1]:11434"])
def test_settings_accept_local_ollama_without_any_provider_key(url):
    config = settings(ollama_base_url=url)
    assert config.ollama_base_url == url.rstrip("/")
    assert config.ollama_model == "gemma4:e4b-it-q4_K_M"
    assert config.agent_timeout_seconds == 120
