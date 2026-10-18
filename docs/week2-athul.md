# Athul's Week 2: location and alerts

Scope follows slide 11 of the supplied member guide: location extraction/geography lookup, alert management, current-area matching, and a demonstration of `MATCH`, `NO_MATCH`, and `UNCERTAIN`. The user's requested Agents SDK integration is included now. React references in the guide are implemented as HTMX templates. Other members' urgency model, summary generation and investigation work are not implemented here.

## Features

- The curated gazetteer contains all 14 Kerala districts and 100 selected localities. Each place records its official district source, known aliases, kind and district. It is deliberately incomplete; it provides no invented coordinates or ward boundaries.
- Extraction matches whole aliases in the citizen message and location field. Repeated names can be resolved with a district qualifier. Conflicting districts/localities, ambiguous names, and unknown places retain uncertainty. A district-only result does not claim to have verified a street or locality.
- Admins create, edit, schedule and expire Yellow/Orange/Red alerts at `/alerts`. Form times use IST; API dates require an explicit timezone and are stored as UTC. Citizens and response teams see currently active alerts. Explicit expiry is final; create a new alert to reissue it.
- A district alert covers its recognised localities; a locality alert covers that locality. A district-only report with only narrower alerts is uncertain. Expired and future alerts do not match. `NO_MATCH` never establishes that a report is false or an area is safe.
- New reports save deterministic extraction and alert evidence in the same transaction as the report. Existing reports get a check when an admin selects **Analyze location**. Reruns append analysis records; the detail card shows the latest saved result and when it checked alerts. Original location, status and team assignment are preserved.

## Gemini key and model

From the project directory, run the command below in your own terminal. Input is hidden and the key is saved with private file permissions on the native Linux filesystem, outside Git and the exFAT workspace.

```bash
.venv/bin/python -m scripts.configure_gemini
```

The server reads that file on each agent request, so key setup does not need a restart. Alternatively supply `GEMINI_API_KEY` through the process environment or private `.env`, or set `GEMINI_API_KEY_FILE` to a private file. `GEMINI_MODEL` defaults to `gemini-3.1-flash-live-preview`; the application does not silently substitute another model or provider. No OpenAI API key is needed.

Google lists the requested Flash Live variant as `gemini-3.1-flash-live-preview`. It uses the stateful Live API rather than Chat Completions. The OpenAI Agents SDK runs it through the project's `GeminiLiveModel` adapter, which converts native Live function calls into SDK tool requests and forwards tool responses over the same server-side WebSocket. The saved API key is sent only in Google's authentication header. The HTMX text workflow remains the same. Sources: [Google's Flash Live model specification](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-live-preview), [Live API overview](https://ai.google.dev/gemini-api/docs/live-api), [Live tool use](https://ai.google.dev/gemini-api/docs/live-api/tools), and [Agents SDK model interfaces](https://openai.github.io/openai-agents-python/models/).

## Agent and tools

`backend/ai/agent.py` builds one SDK `Agent` and executes `Runner.run` with two `@function_tool` functions:

1. `extract_report_location` reads the original report bound to the run's application context and returns sourced geography candidates.
2. `check_active_alerts` requires extraction first, queries current PostgreSQL alerts, and returns a structured match result. The SDK stops after this tool and closes the Live connection. The application uses text input and tool results; it does not add microphone access or an audio interface.

The Live adapter only transports model requests; the OpenAI Agents SDK executes the allowlisted tools. The model selects tools; application code determines their results. Tools accept no model-supplied report text, user ID, location ID, SQL or operational action. Model prose is not accepted as analysis evidence. Only completed tool outputs are persisted. There are no tools to create alerts, change incident status, assign teams or run shell commands. The tools use the report locally; Gemini receives the orchestration prompt and tool results, not the raw citizen message or account credentials. OpenAI trace export is disabled.

Agent runs have a six-turn and 45-second default budget, configurable as `AGENT_MAX_TURNS` and `AGENT_TIMEOUT_SECONDS`. Missing keys, provider failures, cancelled calls, invalid tool sequences and incomplete runs return explicitly labelled local fallback results with a safe explanation. The configured model name does not imply a successful model run: `mode=agent` requires both SDK tools to complete. Local fallback never claims Gemini completed. Keys and raw provider errors are not included in API responses or saved analysis.

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
| `GET /api/agent/status` | Admin | Key presence and model, never the key |
| `GET /api/incidents/{id}/location-analysis` | Admin | Latest saved geography analysis |
| `POST /api/incidents/{id}/location-analysis` | Admin | Run `{use_agent: false}` locally or `{use_agent: true}` through Gemini |

API docs at `/docs` contain exact schemas. Existing bearer sessions, role permissions and CSRF-protected HTMX form conventions apply. Startup creates only the new `alerts` and `location_analyses` tables; existing incident columns and data remain intact. Analysis records reference their incident and are removed if that incident is deleted by maintenance tools. Normal application flows do not delete incidents.

## Demonstration

1. Sign in as admin and create an active **demo** alert covering Aluva or Ernakulam.
2. In a separate tab, sign in as the citizen and submit a clearly labelled synthetic flood report located in Aluva.
3. Open that report as admin: the initial check shows Aluva and `MATCH`. Select **Run Gemini agent**, then expand **Agent actions** to see both actual tool calls.
4. Expire the demo alert and select **Analyze location** again: the new check is `NO_MATCH`.
5. Submit a report with an unsupported location such as `Unlisted bridge`, or the repeated name `Pallippuram` without a district: it returns `UNCERTAIN`. Adding a recognised district disambiguates repeated names where the catalog supports it.

## Verification commands

```bash
.venv/bin/python -m pip check
.venv/bin/python -m pytest
.venv/bin/python -m scripts.check_location_agent
# One real Gemini run; reads the configured key and current DB, writes no report.
.venv/bin/python -m scripts.check_location_agent --live
```

The smoke command also loads this Fedora workspace's private Linux environment manifest when present; standard installations use `.env` or process environment. SDK tests use the SDK's `ScriptedModel` to execute the real Runner and function tools without a network request. Tests cover location aliases and ambiguity, alert dates/coverage/permissions, automatic snapshot persistence, tool order and turn budget, model-prose rejection, key rotation, fallback redaction, and HTMX validation/CSRF/role behavior. Existing Week 1 authentication and reporting tests remain in the full suite.

Dependencies pin the Agents SDK and compatible FastAPI, PyJWT and multipart releases. The upgrade is necessary for the current SDK's Starlette requirements and is covered by the existing web regression tests.
