"""Docker may opt into one internal model host without enabling remote URLs."""
import pytest
from pydantic import ValidationError

from backend.config import Settings


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    monkeypatch.delenv("OLLAMA_ALLOW_DOCKER_HOST", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)


def settings(**overrides):
    return Settings(
        _env_file=None,
        database_url="sqlite://",
        allow_sqlite_for_tests=True,
        jwt_secret="synthetic-docker-ollama-test-secret",
        **overrides,
    )


def test_compose_host_requires_explicit_opt_in():
    with pytest.raises(ValidationError):
        settings(ollama_base_url="http://ollama:11434")
    config = settings(ollama_allow_docker_host=True, ollama_base_url="http://ollama:11434/")
    assert config.ollama_base_url == "http://ollama:11434"


def test_compose_opt_in_from_environment(monkeypatch):
    monkeypatch.setenv("OLLAMA_ALLOW_DOCKER_HOST", "true")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
    assert settings().ollama_base_url == "http://ollama:11434"


@pytest.mark.parametrize("url", [
    "http://ollama.com:11434", "http://ollama.evil.example:11434",
    "http://host.docker.internal:11434", "http://192.168.1.2:11434",
    "http://ollama.:11434", "http://user:password@ollama:11434",
    "http://@ollama:11434", "http://ollama:11434/api",
    "http://ollama:11434?token=example", "http://ollama:11434#example",
    "http://ollama:bad", "http://ollama:0", "http://ollama:65536",
    "file://ollama/model",
])
def test_docker_opt_in_does_not_allow_other_hosts_or_unsafe_urls(url):
    with pytest.raises(ValidationError):
        settings(ollama_allow_docker_host=True, ollama_base_url=url)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:11434", "http://localhost:11435/", "http://[::1]:11434",
])
def test_compose_opt_in_preserves_loopback_support(url):
    assert settings(ollama_allow_docker_host=True, ollama_base_url=url).ollama_base_url == url.rstrip("/")
