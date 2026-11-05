"""Docker setup never replaces host settings or persistent database credentials."""
from dotenv import dotenv_values
import pytest

from scripts.configure_docker import DEFAULT_MODEL, configure


def test_docker_credentials_are_independent_random_and_preserved(tmp_path):
    host = tmp_path / ".env"
    host.write_text("JWT_SECRET=synthetic-host-secret\n", encoding="utf-8")
    destination = tmp_path / ".env.docker"
    assert configure(destination, port=8014)
    values = dotenv_values(destination)
    assert values["WEB_PORT"] == "8014"
    assert values["OLLAMA_MODEL"] == DEFAULT_MODEL
    assert len(bytes.fromhex(values["POSTGRES_PASSWORD"])) == 32
    assert len(bytes.fromhex(values["JWT_SECRET"])) == 48
    before = destination.read_bytes()
    assert not configure(destination, port=8015)
    assert destination.read_bytes() == before
    assert host.read_text(encoding="utf-8") == "JWT_SECRET=synthetic-host-secret\n"
    other = tmp_path / ".env.other"
    assert configure(other)
    assert dotenv_values(other)["POSTGRES_PASSWORD"] != values["POSTGRES_PASSWORD"]


@pytest.mark.parametrize("port", [0, -1, 65536])
def test_invalid_port_does_not_create_credentials(tmp_path, port):
    destination = tmp_path / ".env.docker"
    with pytest.raises(ValueError, match="port"):
        configure(destination, port=port)
    assert not destination.exists()
