"""Compatibility entry point for the managed single-server launcher."""
import subprocess
from pathlib import Path


if __name__ == "__main__":
    launcher = Path(__file__).resolve().parent / "start.ps1"
    raise SystemExit(subprocess.call([
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(launcher),
    ]))
