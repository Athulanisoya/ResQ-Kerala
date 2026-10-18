"""Enter a Gemini API key securely on this computer, outside the shared drive."""
import getpass
import os
from pathlib import Path
import tempfile

from backend.config import default_gemini_key_file


def main():
    destination = default_gemini_key_file()
    print("Save a Gemini API key for this workspace. Input is hidden.")
    key = getpass.getpass("Gemini API key: ").strip()
    if not key or any(char.isspace() for char in key):
        raise SystemExit("No key saved: enter one nonempty API key without whitespace.")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination.parent.chmod(0o700)
    fd, pending = tempfile.mkstemp(prefix="gemini-", dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(key + "\n")
        os.replace(pending, destination)
        destination.chmod(0o600)
    finally:
        Path(pending).unlink(missing_ok=True)
    print(f"Key saved privately to {destination}. The app will detect it on the next agent run.")


if __name__ == "__main__":
    main()
