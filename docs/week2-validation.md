# Athul Week 2 validation — 15 October 2026

Final regression result: **151 passed**, including the two PostgreSQL migration tests enabled with the workspace's private `RESQ_TEST_POSTGRES_URL`. Those tests created and removed only unique temporary schemas. Existing Pydantic config and `datetime.utcnow` deprecation warnings remain from Week 1.

`pip check` reports no broken requirements. `git diff --check` passes. A silent comparison against the actual saved Gemini key found no occurrences in any of the 35 modified or new source/documentation files inspected.

The real OpenAI Agents SDK Runner executed both bound function tools under its `ScriptedModel` in tests. Tests verified tool order, turn budget, read-only tool schemas, model-prose rejection, sourced outputs, persistence/permissions, and redacted provider failure handling. This proves application tool execution, independently of provider availability.

Live requests used the requested `gemini-3.6-flash` model and the user's locally saved key. Gemini returned HTTP **503 UNAVAILABLE**, reporting high demand, before executing the tools. The CLI and HTMX card correctly returned labelled local fallback results. A successful live Gemini tool round trip was therefore **not verified**; no substitute model was selected. Run `python -m scripts.check_location_agent --live` to retry when the provider is available.

Browser checks against the actual PostgreSQL-backed app confirmed:

- Admin and citizen tabs have independent signed-in sessions.
- Admin creates an active synthetic alert for Aluva and edits its level.
- Citizen submits a clearly labelled synthetic report; admin sees its automatic saved location check and a matching active alert.
- Admin triggers the Gemini path and sees truthful local fallback after the provider error.
- Admin expires the demo alert, refreshes analysis, and sees no matching active alert.
- A second synthetic report at Pallippuram displays uncertainty and four district-qualified candidates, without selecting one.

The expired demo alert and two clearly labelled synthetic reports remain locally for review. The application continues running at `http://127.0.0.1:8013`. No operational team assignment or incident status changes were made during these checks.

## Flash Live model migration — 15 October 2026

The selected model is now **`gemini-3.1-flash-live-preview`**, Google's documented Flash Live model identifier. The user's model catalog includes this model. The OpenAI Agents SDK uses a native server-side WebSocket model adapter; Chat Completions is retained only for explicitly configured non-Live models.

A real call with the saved key **succeeded** using Flash Live. It returned `mode=agent`, resolved Aluva, returned `NO_MATCH` against the current database, and executed both `extract_report_location` and `check_active_alerts` with no warning. This supersedes the earlier unsuccessful Gemini 3.6 Flash live check described above.

Final regression result after the migration: **185 passed**, including the isolated PostgreSQL migration checks. The new tests cover native Live message conversion, actual SDK Runner/function-tool integration over a simulated socket, tool correlation/history, incomplete Live turn handling, cancellation, safe errors, cleanup, and routing to the Live transport. `pip check` and `git diff --check` pass.

After restart, a read-only authenticated status check confirmed `configured=true`, `model=gemini-3.1-flash-live-preview`, and PostgreSQL connected. An optional additional POST to analyze the saved synthetic report was rejected by automatic approval review on report-export authorization grounds, so it was skipped. The successful real Live test above used the standalone synthetic smoke command and did not persist an incident analysis.
