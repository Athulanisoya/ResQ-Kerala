"""Check geography tools; --live makes one bounded local Ollama agent run."""
import argparse
import asyncio
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Call the configured local Ollama Gemma 4 model")
    parser.add_argument("--message", default="Flood water is rising in Aluva.")
    parser.add_argument("--location", default="Aluva")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    linux_setup = root / ".runtime" / "linux-setup.json"
    if linux_setup.exists():
        setup = json.loads(linux_setup.read_text())
        for key, value in json.loads(Path(setup["environment"]).read_text()).items():
            os.environ.setdefault(key, value)
    from backend.ai.agent import analyze_location
    from backend.database.connection import SessionLocal, engine
    try:
        with SessionLocal() as db:
            result = asyncio.run(analyze_location(db, args.message, args.location, use_agent=args.live))
        print(json.dumps({"mode": result.mode, "model": result.model,
                          "location_status": result.extraction.status,
                          "place": result.extraction.place.name if result.extraction.place else None,
                          "alert_match": result.alert_match.status,
                          "tools_called": [call.name for call in result.tool_calls],
                          "warning": result.warning}, indent=2))
        if args.live and result.mode != "agent":
            raise SystemExit(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
