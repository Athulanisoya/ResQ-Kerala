"""Compatibility entry point for the former Gemini key setup command."""
from scripts.configure_ollama import main


if __name__ == "__main__":
    print("Gemini key setup has been replaced by local Ollama. Use python -m scripts.configure_ollama.")
    try:
        main()
    except (RuntimeError, OSError) as error:
        raise SystemExit(str(error)) from None
