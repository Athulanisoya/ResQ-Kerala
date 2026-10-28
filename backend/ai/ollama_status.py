"""Bounded local readiness check; it never generates text or downloads models."""
import httpx

from backend.config import Settings


async def get_ollama_status(settings: Settings, *, client: httpx.AsyncClient | None = None) -> dict:
    status = {"provider": "ollama", "model": settings.ollama_model,
              "configured": False, "reachable": False, "model_available": False}
    owned = client is None
    client = client or httpx.AsyncClient(timeout=2, trust_env=False)
    try:
        response = await client.post(settings.ollama_base_url + "/api/show",
                                     json={"model": settings.ollama_model})
        status["reachable"] = True
        if response.status_code == 404:
            return {**status, "reason": "The selected Gemma 4 model is not installed. Run the Ollama setup command."}
        response.raise_for_status()
        details = response.json()
        if not isinstance(details, dict) or not isinstance(details.get("capabilities"), list):
            raise ValueError("Invalid model capabilities")
        status["model_available"] = True
        if "tools" not in details["capabilities"]:
            return {**status, "reason": "The selected Ollama model does not support the required tools."}
        return {**status, "configured": True, "reason": "Gemma 4 is available through local Ollama."}
    except (httpx.HTTPError, ValueError):
        return {**status, "reason": "Ollama is unavailable. Start the local Ollama server and retry."}
    finally:
        if owned:
            await client.aclose()
