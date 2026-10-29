"""Verify a local Ollama model and save this workspace's keyless agent setup."""
import argparse
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

from dotenv import dotenv_values, set_key
import httpx


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "gemma4:e4b-it-q4_K_M"


def local_base_url(value: str) -> str:
    """Keep report content on the local Ollama server, without URL credentials."""
    value = value.strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
        loopback = host in {"localhost", "127.0.0.1", "::1"}
    except ValueError:
        raise ValueError("Use a local Ollama URL, such as http://127.0.0.1:11434, without a path or credentials.") from None
    if (not loopback or parsed.scheme not in {"http", "https"}
            or parsed.username or parsed.password or parsed.path
            or parsed.query or parsed.fragment or (port is not None and not 1 <= port <= 65535)):
        raise ValueError("Use a local Ollama URL, such as http://127.0.0.1:11434, without a path or credentials.")
    return value


def model_name(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}", value):
        raise ValueError("Choose one valid installed Ollama model name without whitespace.")
    return value


def verify_model(base_url: str, model: str) -> None:
    """Inspect installed models; setup does not download or replace a model."""
    try:
        with httpx.Client(timeout=5, trust_env=False) as client:
            response = client.get(f"{base_url}/api/tags")
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        raise RuntimeError("Cannot read local Ollama models. Start Ollama, then rerun this command.") from None
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        raise RuntimeError("The local server returned an invalid Ollama model list.")
    available = {name for entry in models if isinstance(entry, dict)
                 for name in [entry.get("name") or entry.get("model")] if isinstance(name, str)}
    tagged = model if ":" in model.rsplit("/", 1)[-1] else f"{model}:latest"
    if model not in available and tagged not in available:
        raise RuntimeError(f"Ollama model '{model}' is not installed. Run 'ollama pull {model}', then rerun setup.")
    try:
        with httpx.Client(timeout=5, trust_env=False) as client:
            response = client.post(f"{base_url}/api/show", json={"model": model})
            response.raise_for_status()
            details = response.json()
    except (httpx.HTTPError, ValueError):
        raise RuntimeError("Cannot verify the selected Ollama model. Start Ollama, then rerun this command.") from None
    capabilities = details.get("capabilities") if isinstance(details, dict) else None
    if not isinstance(capabilities, list) or "tools" not in capabilities:
        raise RuntimeError("The selected Ollama model does not support tools. Choose the Gemma 4 model documented in README.md.")


def write_configuration(base_url: str, model: str) -> bool:
    """Atomically edit only Ollama options, preserving credentials and comments."""
    destination = ROOT / ".env"
    values = {"OLLAMA_BASE_URL": base_url, "OLLAMA_MODEL": model}
    existing = dotenv_values(destination, interpolate=False)
    changes = {key: value for key, value in values.items() if existing.get(key) != value}
    if not changes:
        return False
    descriptor, temporary = tempfile.mkstemp(prefix=".ollama-env-", suffix=".tmp", dir=ROOT)
    pending = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(destination.read_bytes() if destination.exists()
                         else b"# Private local configuration. Keep this file outside commits.\n")
        for key, value in changes.items():
            set_key(pending, key, value, quote_mode="always", encoding="utf-8")
        os.replace(pending, destination)
    finally:
        pending.unlink(missing_ok=True)
    return True


def main(argv=None):
    existing = dotenv_values(ROOT / ".env", interpolate=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", type=local_base_url,
                        default=os.environ.get("OLLAMA_BASE_URL") or existing.get("OLLAMA_BASE_URL") or DEFAULT_BASE_URL)
    parser.add_argument("--model", type=model_name,
                        default=os.environ.get("OLLAMA_MODEL") or existing.get("OLLAMA_MODEL") or DEFAULT_MODEL)
    args = parser.parse_args(argv)
    verify_model(args.base_url, args.model)
    changed = write_configuration(args.base_url, args.model)
    print(f"Local Ollama ready: {args.model} at {args.base_url}. No API key is required.")
    if changed:
        print("Saved OLLAMA_BASE_URL and OLLAMA_MODEL. Restart the application to load these settings.")
    else:
        print("This workspace already uses these Ollama settings.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError) as error:
        raise SystemExit(str(error)) from None
