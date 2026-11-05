"""Readiness must require every service check and hide failed private inputs."""
from io import BytesIO
import json
from urllib.error import URLError

import pytest
from pydantic import ValidationError

from backend.config import Settings
from scripts import verify_docker


@pytest.fixture
def stack(monkeypatch):
    state = {
        "health": b'{"status":"ok","database":"connected"}',
        "frontend": b'<script src="/static/vendor/htmx.min.js"></script>',
        "model": {"configured": True, "model": "gemma4:synthetic"},
        "http_calls": [],
        "model_calls": [],
    }
    config = object()

    def open_response(url, timeout):
        assert timeout == 5
        state["http_calls"].append(url)
        value = state["health"] if url.endswith("/health") else state["frontend"]
        if isinstance(value, Exception):
            raise value
        return BytesIO(value)

    async def model_status(settings):
        assert settings is config
        state["model_calls"].append(settings)
        return state["model"]

    monkeypatch.setattr(verify_docker, "urlopen", open_response)
    monkeypatch.setattr(verify_docker, "get_settings", lambda: config)
    monkeypatch.setattr(verify_docker, "get_ollama_status", model_status)
    return state


def test_ready_requires_http_database_frontend_and_current_model_checks(stack, capsys):
    verify_docker.main()
    assert stack["http_calls"] == [
        "http://127.0.0.1:8013/health", "http://127.0.0.1:8013/",
    ]
    assert len(stack["model_calls"]) == 1
    output = capsys.readouterr().out
    assert "Ready:" in output and "gemma4:synthetic" in output


@pytest.mark.parametrize("payload", [
    [], None, {}, {"status": "ok"}, {"database": "connected"},
    {"status": "unhealthy", "database": "connected"},
    {"status": "ok", "database": "unavailable"},
])
def test_missing_or_failed_database_evidence_never_reports_ready(stack, capsys, payload):
    stack["health"] = json.dumps(payload).encode()
    with pytest.raises(SystemExit, match="Application/database health check failed"):
        verify_docker.main()
    assert not stack["model_calls"]
    assert len(stack["http_calls"]) == 1
    assert "Ready:" not in capsys.readouterr().out


def test_served_non_htmx_page_cannot_pass_frontend_check(stack, capsys):
    stack["frontend"] = b"<html>Application startup error</html>"
    with pytest.raises(SystemExit, match="HTMX frontend check failed"):
        verify_docker.main()
    assert not stack["model_calls"]
    assert "Ready:" not in capsys.readouterr().out


@pytest.mark.parametrize("reason", [
    "Ollama is unavailable. Start the local Ollama server and retry.",
    "The selected Gemma 4 model is not installed. Run the Ollama setup command.",
    "The selected Ollama model does not support the required tools.",
])
def test_model_server_alone_does_not_establish_model_readiness(stack, capsys, reason):
    stack["model"] = {
        "configured": False, "reachable": True,
        "model_available": True, "reason": reason, "model": "synthetic",
    }
    with pytest.raises(SystemExit) as failure:
        verify_docker.main()
    assert str(failure.value) == reason
    assert len(stack["model_calls"]) == 1
    assert "Ready:" not in capsys.readouterr().out


@pytest.mark.parametrize("stage", ["health", "frontend"])
def test_http_failures_are_safe_and_never_continue_to_model(stack, capsys, stage):
    secret = "synthetic-private-connection-detail"
    stack[stage] = URLError(secret)
    with pytest.raises(SystemExit, match="Docker verification failed") as failure:
        verify_docker.main()
    output = capsys.readouterr()
    assert secret not in str(failure.value) + output.out + output.err
    assert failure.value.__suppress_context__
    assert not stack["model_calls"]
    assert "Ready:" not in output.out


def test_malformed_health_json_does_not_echo_response_or_report_ready(stack, capsys):
    secret = "synthetic-private-upstream-response"
    stack["health"] = secret.encode()
    with pytest.raises(SystemExit, match="Docker verification failed") as failure:
        verify_docker.main()
    output = capsys.readouterr()
    assert secret not in str(failure.value) + output.out + output.err
    assert not stack["model_calls"]
    assert "Ready:" not in output.out


def test_configuration_validation_inputs_are_not_printed(stack, monkeypatch, capsys):
    secret = "synthetic-private-database-password"

    def invalid_settings():
        # Use a real Pydantic error: its usual message repeats the rejected URL.
        return Settings(
            _env_file=None,
            database_url=f"invalid://user:{secret}@db/resq",
            jwt_secret="synthetic-verifier-valid-jwt-secret",
        )

    with pytest.raises(ValidationError) as original:
        invalid_settings()
    assert secret in repr(original.value.errors())
    monkeypatch.setattr(verify_docker, "get_settings", invalid_settings)
    with pytest.raises(SystemExit, match="Docker verification failed") as failure:
        verify_docker.main()
    output = capsys.readouterr()
    assert secret not in str(failure.value) + output.out + output.err
    assert failure.value.__suppress_context__
    assert not stack["model_calls"]
    assert "Ready:" not in output.out
