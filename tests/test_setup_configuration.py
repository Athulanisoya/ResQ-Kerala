"""Setup reruns preserve private provider configuration and generated credentials."""
import pytest
from dotenv import dotenv_values
from sqlalchemy import URL

from scripts import setup_local_db as setup


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "Synthetic ResQ's workspace #1"
    runtime = root / ".runtime"
    runtime.mkdir(parents=True)
    monkeypatch.setattr(setup, "ROOT", root)
    monkeypatch.setattr(setup, "RUNTIME", runtime)
    monkeypatch.setattr(setup, "PASSFILE", runtime / "pgpass.conf")
    return root / ".env"


def expected_database_url():
    return URL.create("postgresql+psycopg", username=setup.USER, host="127.0.0.1", port=setup.PORT,
                      database=setup.DATABASE, query={"passfile": setup.PASSFILE.as_posix()}).render_as_string(hide_password=False)


def test_new_configuration_generates_credentials_once_and_is_idempotent(workspace, monkeypatch):
    generated = []

    def synthetic_secret(size):
        generated.append(size)
        return "a1" * size

    monkeypatch.setattr(setup.secrets, "token_hex", synthetic_secret)
    setup.write_private_configuration()
    values = dotenv_values(workspace)
    assert values["DATABASE_URL"] == expected_database_url()
    assert values["DATABASE_SCHEMA"] == "resq_week1"
    assert values["JWT_SECRET"] == "a1" * 48
    assert values["JWT_EXPIRE_MINUTES"] == "30"
    assert values["CORS_ORIGINS"] == "http://127.0.0.1:8013,http://localhost:8013"
    assert values["APP_VERSION"] == "2.0.0-integrated"
    first = workspace.read_bytes()
    setup.write_private_configuration()
    assert generated == [48]
    assert workspace.read_bytes() == first
    assert not setup.PASSFILE.exists()
    assert not (setup.RUNTIME / "env.tmp").exists()


def test_rerun_preserves_gemini_custom_values_comments_and_multiline_configuration(workspace):
    setup.write_private_configuration()
    initial = workspace.read_text(encoding="utf-8").replace(
        "APP_VERSION='2.0.0-integrated'", "APP_VERSION='old-synthetic-version'")
    options = r'''
# Keep this provider configuration and its comments.
GEMINI_API_KEY='synthetic-key-with-#-punctuation' # a synthetic test value
GEMINI_API_KEY_FILE='C:\synthetic\new\private key.txt'
GEMINI_MODEL='synthetic-custom-live-model'
AGENT_TIMEOUT_SECONDS=73
AGENT_MAX_TURNS=9
CUSTOM_ENDPOINT="https://synthetic.example/path?q=test#fragment"
CUSTOM_NOTES='first line # is part of the value
second line with "quotes" and \\ backslash'
# A trailing custom comment.
'''
    workspace.write_text(initial + options, encoding="utf-8")
    before = dotenv_values(workspace, interpolate=False)
    setup.write_private_configuration()
    after = dotenv_values(workspace, interpolate=False)
    assert after == {**before, "APP_VERSION": "2.0.0-integrated"}
    assert options in workspace.read_text(encoding="utf-8")
    assert after["JWT_SECRET"] == before["JWT_SECRET"]
    assert after["DATABASE_URL"] == before["DATABASE_URL"]
    assert not (setup.RUNTIME / "env.tmp").exists()


def test_generated_values_round_trip_quotes_backslashes_hashes_and_newlines(workspace, monkeypatch):
    synthetic = "synthetic 'quoted' \\ secret # literal\nsecond line $VALUE"
    monkeypatch.setattr(setup.secrets, "token_hex", lambda _size: synthetic)
    setup.write_private_configuration()
    assert dotenv_values(workspace)["JWT_SECRET"] == synthetic
    assert dotenv_values(workspace)["DATABASE_URL"] == expected_database_url()
    first = workspace.read_bytes()
    setup.write_private_configuration()
    assert workspace.read_bytes() == first


def test_database_mismatch_leaves_existing_configuration_intact(workspace, monkeypatch):
    original = b"# Keep this synthetic external configuration.\nDATABASE_URL='postgresql+psycopg://synthetic@localhost:5555/other'\nGEMINI_MODEL='synthetic-custom-model'\n"
    workspace.write_bytes(original)

    def unexpected_secret(_size):
        pytest.fail("A database mismatch must be checked before generating credentials.")

    monkeypatch.setattr(setup.secrets, "token_hex", unexpected_secret)
    with pytest.raises(RuntimeError, match="Existing .env uses a different database") as failure:
        setup.write_private_configuration()
    assert "synthetic@" not in str(failure.value)
    assert workspace.read_bytes() == original
    assert not (setup.RUNTIME / "env.tmp").exists()


def test_failed_configuration_update_keeps_original_file_and_removes_pending_copy(workspace, monkeypatch):
    original = b"# Synthetic configuration before setup.\nGEMINI_MODEL='synthetic-custom-model'\n"
    workspace.write_bytes(original)
    original_set_key = setup.set_key
    calls = []

    def fail_second_write(path, key, value, **kwargs):
        calls.append(key)
        if len(calls) == 2:
            raise OSError("Synthetic update failure")
        return original_set_key(path, key, value, **kwargs)

    monkeypatch.setattr(setup, "set_key", fail_second_write)
    with pytest.raises(OSError, match="Synthetic update failure"):
        setup.write_private_configuration()
    assert len(calls) == 2
    assert workspace.read_bytes() == original
    assert not (setup.RUNTIME / "env.tmp").exists()
