# Athul's Week 2: location and alerts

Scope follows slide 11 of the supplied member guide: location extraction/geography lookup, alert management, current-area matching, and a demonstration of `MATCH`, `NO_MATCH`, and `UNCERTAIN`. The user's requested Agents SDK integration is included now. React references in the guide are implemented as HTMX templates. Other members' urgency model, summary generation and investigation work are not implemented here.

## Features

- The curated gazetteer contains all 14 Kerala districts and 100 selected localities. Each place records its official district source, known aliases, kind and district. It is deliberately incomplete; it provides no invented coordinates or ward boundaries.
- Extraction matches whole aliases in the citizen message and location field. Repeated names can be resolved with a district qualifier. Conflicting districts/localities, ambiguous names, and unknown places retain uncertainty. A district-only result does not claim to have verified a street or locality.
- Admins create, edit, schedule and expire Yellow/Orange/Red alerts at `/alerts`. Form times use IST; API dates require an explicit timezone and are stored as UTC. Citizens and response teams see currently active alerts. Explicit expiry is final; create a new alert to reissue it.
- A district alert covers its recognised localities; a locality alert covers that locality. A district-only report with only narrower alerts is uncertain. Expired and future alerts do not match. `NO_MATCH` never establishes that a report is false or an area is safe.
- New reports save deterministic extraction and alert evidence in the same transaction as the report. Existing reports get a check when an admin selects **Analyze location**. Reruns append analysis records; the detail card shows the latest saved result and when it checked alerts. Original location, status and team assignment are preserved.

## Local Gemma 4 model through Ollama

Install and start [Ollama](https://ollama.com/download). From the project directory in PowerShell, install the model if needed, then verify and save the local setup:

```powershell
ollama pull gemma4:e4b-it-q4_K_M
.\.venv\Scripts\python.exe -m scripts.configure_ollama
```

No Gemini or OpenAI API key is required. `OLLAMA_BASE_URL` defaults to `http://127.0.0.1:11434`, and `OLLAMA_MODEL` defaults to `gemma4:e4b-it-q4_K_M`. Setup checks the installed model and its tool capability before updating only those two settings in the private `.env`. It preserves database credentials and other configuration. Use `--model` for another installed model or `--base-url` for another loopback server port. Restart the application after changing settings. The previous `configure_gemini` command delegates to Ollama setup and no longer requests a key.

The OpenAI Agents SDK uses the project's Ollama adapter to convert Gemma 4's native function calls into SDK tool requests and send tool results back through local `/api/chat`. Model inference runs on the configured loopback server; it does not call Google's or OpenAI's model service. The admin location card checks live server/model readiness. Saved historical Gemini analyses keep their original model label. Sources: [Ollama Gemma 4 models](https://ollama.com/library/gemma4), [Ollama chat API](https://docs.ollama.com/api/chat), [Ollama tool calling](https://docs.ollama.com/capabilities/tool-calling), and [Agents SDK model interfaces](https://openai.github.io/openai-agents-python/models/).

## Agent and tools

`backend/ai/agent.py` builds one SDK `Agent` and executes `Runner.run` with two `@function_tool` functions:

1. `extract_report_location` reads the original report bound to the run's application context and returns sourced geography candidates.
2. `check_active_alerts` requires extraction first, queries current PostgreSQL alerts, and returns a structured match result. The SDK stops after this tool. The application uses text input and tool results; it does not add microphone access or an audio interface.

The Ollama adapter only transports model requests; the OpenAI Agents SDK executes the allowlisted tools. The model selects tools; application code determines their results. Tools accept no model-supplied report text, user ID, location ID, SQL or operational action. Model prose is not accepted as analysis evidence. Only completed tool outputs are persisted. There are no tools to create alerts, change incident status, assign teams or run shell commands. The tools use the report locally; the model receives the orchestration prompt and tool results, not the raw citizen message or account credentials. OpenAI trace export is disabled.

Agent runs have a six-turn and 120-second default budget, configurable as `AGENT_MAX_TURNS` and `AGENT_TIMEOUT_SECONDS`. An unavailable server/model, provider failures, cancelled calls, invalid tool sequences and incomplete runs return explicitly labelled local fallback results with a safe explanation. The configured model name does not imply a successful model run: `mode=agent` requires both SDK tools to complete. Local fallback never claims Gemma 4 completed. Raw provider errors are not included in API responses or saved analysis.

## API contracts

| Route | Permission | Purpose |
| --- | --- | --- |
| `GET /api/alerts` | Signed in | Current active alerts |
| `GET /api/alerts?include_inactive=true` | Admin | Full alert register |
| `GET /api/alerts/places` | Signed in | Canonical place catalog |
| `POST /api/alerts` | Admin | Create alert |
| `PATCH /api/alerts/{id}` | Admin | Edit alert |
| `POST /api/alerts/{id}/expire` | Admin | Explicitly expire alert |
| `POST /api/alerts/match` | Signed in | Match `{message, reported_location?}` |
| `GET /api/agent/status` | Admin | Local Ollama reachability, installed tool-capable model and readiness reason |
| `GET /api/incidents/{id}/location-analysis` | Admin | Latest saved geography analysis |
| `POST /api/incidents/{id}/location-analysis` | Admin | Run `{use_agent: false}` deterministically or `{use_agent: true}` through local Ollama |

API docs at `/docs` contain exact schemas. Existing bearer sessions, role permissions and CSRF-protected HTMX form conventions apply. Startup creates only the new `alerts` and `location_analyses` tables; existing incident columns and data remain intact. Analysis records reference their incident and are removed if that incident is deleted by maintenance tools. Normal application flows do not delete incidents.

## Demonstration

1. Sign in as admin and create an active **demo** alert covering Aluva or Ernakulam.
2. In a separate tab, sign in as the citizen and submit a clearly labelled synthetic flood report located in Aluva.
3. Open that report as admin: the initial check shows Aluva and `MATCH`. Select **Run Gemma 4 agent**, then expand **Agent actions** to see both actual tool calls.
4. Expire the demo alert and select **Analyze location** again: the new check is `NO_MATCH`.
5. Submit a report with an unsupported location such as `Unlisted bridge`, or the repeated name `Pallippuram` without a district: it returns `UNCERTAIN`. Adding a recognised district disambiguates repeated names where the catalog supports it.

## Verification commands

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m scripts.check_location_agent
# One real local Gemma 4 run; reads current DB alerts, writes no report.
.\.venv\Scripts\python.exe -m scripts.check_location_agent --live
```

The smoke command retains compatibility with the private Linux environment manifest from the original branch when present; the integrated Windows workspace uses `.env` or process environment. SDK tests use the SDK's `ScriptedModel` to execute the real Runner and function tools without a network request. Tests cover location aliases and ambiguity, alert dates/coverage/permissions, automatic snapshot persistence, tool order and turn budget, model-prose rejection, local model readiness, fallback redaction, and HTMX validation/CSRF/role behavior. Existing Week 1 authentication and reporting tests remain in the full suite.

Dependencies pin the Agents SDK and compatible FastAPI, PyJWT and multipart releases. The upgrade is necessary for the current SDK's Starlette requirements and is covered by the existing web regression tests.
