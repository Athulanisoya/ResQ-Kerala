"""Start the project database and API as hidden background processes."""
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
DATA = RUNTIME / "postgres"
PG_CTL = Path(r"C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe")


def main():
    RUNTIME.mkdir(exist_ok=True)
    if (DATA / "PG_VERSION").exists():
        status = subprocess.run([str(PG_CTL), "-D", str(DATA), "status"], capture_output=True)
        if status.returncode != 0:
            subprocess.run([
                str(PG_CTL), "-D", str(DATA), "-l", str(RUNTIME / "postgres.log"), "-w", "start",
            ], check=True)
    try:
        with urlopen("http://127.0.0.1:8000/openapi.json", timeout=2) as response:
            if json.load(response)["info"]["title"] == "ResQ Kerala API":
                print("ResQ Kerala API already running: http://127.0.0.1:8000/docs")
                return
        raise SystemExit("Port 8000 is occupied by another application.")
    except OSError:
        pass
    with (RUNTIME / "api.log").open("a", encoding="utf-8") as output:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=ROOT, stdout=output, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        )
    for _ in range(40):
        if process.poll() is not None:
            raise SystemExit("API failed to start; see .runtime/api.log.")
        try:
            with urlopen("http://127.0.0.1:8000/health", timeout=1) as response:
                if json.load(response).get("status") == "healthy":
                    (RUNTIME / "api-process.json").write_text(json.dumps({"pid": process.pid}), encoding="utf-8")
                    print("ResQ Kerala API running: http://127.0.0.1:8000/docs")
                    return
        except OSError:
            time.sleep(0.5)
    raise SystemExit("API startup timed out; see .runtime/api.log.")


if __name__ == "__main__":
    main()
