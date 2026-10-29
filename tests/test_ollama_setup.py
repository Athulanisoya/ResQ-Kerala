"""Keyless setup verifies local availability and preserves private configuration."""
import httpx
import pytest
from dotenv import dotenv_values

from scripts import configure_ollama as setup


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "ROOT", tmp_path)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    return tmp_path / ".env"


@pytest.mark.parametrize("value", ["http://localhost:11434", "http://127.0.0.1:11434", "http://[::1]:11434/"])
def test_local_url_accepts_loopback_server(value):
    assert setup.local_base_url(value) == value.rstrip("/")


@pytest.mark.parametrize("value", ["https://ollama.com", "http://127.0.0.1.evil.example", "http://user:secret@localhost:11434",
                                    "http://localhost:11434/api", "http://localhost:11434?token=secret", "file:///tmp/ollama"])
def test_setup_does_not_allow_remote_or_authenticated_server(value):
    with pytest.raises(ValueError, match="local Ollama URL"):
        setup.local_base_url(value)


def fake_ollama(monkeypatch, response, capabilities=None):
    original_client = httpx.Client

    def handler(request):
        if str(request.url) == "http://127.0.0.1:11434/api/tags":
            assert request.method == "GET"
            return response
        assert str(request.url) == "http://127.0.0.1:11434/api/show"
        assert request.method == "POST"
        return httpx.Response(200, json={"capabilities": capabilities if capabilities is not None else ["completion", "tools"]})

    def client(**kwargs):
        assert kwargs == {"timeout": 5, "trust_env": False}
        return original_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(setup.httpx, "Client", client)


def test_setup_checks_installed_model_and_preserves_credentials_and_comments(workspace, monkeypatch, capsys):
    original = """# Keep private values and comments.
DATABASE_URL='synthetic-database-url'
JWT_SECRET='synthetic-signing-secret'
GEMINI_API_KEY='synthetic-legacy-provider-key' # retain unrelated configuration
CUSTOM_NOTES='first line
second line # literal'
"""
    workspace.write_text(original, encoding="utf-8")
    fake_ollama(monkeypatch, httpx.Response(200, json={"models": [{"name": setup.DEFAULT_MODEL}]}))
    setup.main([])
    values = dotenv_values(workspace, interpolate=False)
    assert values["OLLAMA_MODEL"] == setup.DEFAULT_MODEL
    assert values["OLLAMA_BASE_URL"] == setup.DEFAULT_BASE_URL
    assert original in workspace.read_text(encoding="utf-8")
    assert values["JWT_SECRET"] == "synthetic-signing-secret"
    assert "No API key is required" in capsys.readouterr().out
    first = workspace.read_bytes()
    setup.main([])
    assert workspace.read_bytes() == first
    assert not list(workspace.parent.glob(".ollama-env-*.tmp"))


@pytest.mark.parametrize("response", [httpx.Response(200, json={"models": []}), httpx.Response(503),
                                     httpx.Response(200, json={"models": "invalid"})])
def test_unavailable_model_or_server_never_changes_private_configuration(workspace, monkeypatch, response):
    original = b"JWT_SECRET='synthetic-existing-secret'\nOLLAMA_MODEL='existing-model'\n"
    workspace.write_bytes(original)
    fake_ollama(monkeypatch, response)
    with pytest.raises(RuntimeError):
        setup.main(["--model", setup.DEFAULT_MODEL])
    assert workspace.read_bytes() == original


def test_setup_accepts_ollama_latest_tag_alias(monkeypatch):
    fake_ollama(monkeypatch, httpx.Response(200, json={"models": [{"model": "resq-gemma4:latest"}]}))
    setup.verify_model(setup.DEFAULT_BASE_URL, "resq-gemma4")


def test_embedding_model_cannot_replace_the_tool_agent(workspace, monkeypatch):
    original = b"JWT_SECRET='synthetic-existing-secret'\n"
    workspace.write_bytes(original)
    fake_ollama(monkeypatch, httpx.Response(200, json={"models": [{"name": "embedding:latest"}]}), ["embedding"])
    with pytest.raises(RuntimeError, match="does not support tools"):
        setup.main(["--model", "embedding"])
    assert workspace.read_bytes() == original


def test_failed_ollama_configuration_write_preserves_original_file(workspace, monkeypatch):
    original = b"# Private synthetic setup.\nJWT_SECRET='synthetic-existing-secret'\n"
    workspace.write_bytes(original)
    original_set_key = setup.set_key
    writes = []

    def fail_second_write(path, key, value, **kwargs):
        writes.append(key)
        if len(writes) == 2:
            raise OSError("Synthetic interrupted write")
        return original_set_key(path, key, value, **kwargs)

    monkeypatch.setattr(setup, "set_key", fail_second_write)
    with pytest.raises(OSError, match="interrupted write"):
        setup.write_configuration(setup.DEFAULT_BASE_URL, setup.DEFAULT_MODEL)
    assert workspace.read_bytes() == original
    assert not list(workspace.parent.glob(".ollama-env-*.tmp"))
