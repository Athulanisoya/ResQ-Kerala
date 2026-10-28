# Local Gemma 4 setup and verification

Verified on 23 October 2026. The active location agent now uses local Ollama instead of Gemini. It needs no Gemini or OpenAI API key. Existing saved analyses retain their model names.

## Configuration

- Server: `http://127.0.0.1:11434`
- Model: `gemma4:e4b-it-q4_K_M` (already installed on this computer)
- Setup: `.\.venv\Scripts\python.exe -m scripts.configure_ollama`
- Start application: `.\scripts\start.ps1`
- Application: <http://127.0.0.1:8013>

Setup verifies the installed model and its tool capability, then atomically saves only `OLLAMA_BASE_URL` and `OLLAMA_MODEL` to the private `.env`. Restart the application after changing these settings. The former `configure_gemini` command delegates to Ollama setup without requesting a key. Old provider configuration is ignored by the active agent.

The native adapter calls local `/api/chat` with streaming and thinking disabled, a 4,096-token context, bounded generation, and a 120-second default workflow budget. Ambient proxies and redirects are disabled. The Agents SDK still executes the two application tools: `extract_report_location`, followed by `check_active_alerts`. Their results remain deterministic geography and current database evidence. Model prose cannot replace tool results or perform response operations. Tracing export remains disabled.

The admin status endpoint checks local `/api/show`, including installed model/tool capability. Offline servers, missing models, provider failures, incomplete tool workflows, and timeouts produce safe, explicitly labelled local fallback results.

## Verification

- Full Python suite: **391 passed**, no failures, errors or skipped tests, including isolated PostgreSQL transaction checks. Report: `.runtime/ollama-regression.xml`.
- Browser-session JavaScript suite: **19 passed**.
- `pip check` and `git diff --check`: passed.
- Real Gemma 4 smoke run: `mode=agent`, Aluva resolved, both required tools executed, no warning or fallback.
- Live authenticated admin form: submitted a temporary synthetic report, rendered the enabled Gemma 4 action, posted the CSRF-protected form, executed both model-requested tools, and verified the saved result in PostgreSQL and the API. The report remained `SUBMITTED` with its original location. The temporary report and its related records were removed; test sessions were revoked. Evidence: `.runtime/ollama-live-validation.json`.
- Live authenticated HTML/API checks passed for citizen, admin, and response-team workspaces. This is HTTP/form verification; it does not claim a visual browser inspection.

The application and Ollama were left running locally. Earlier Week 2 merge/audit records and Week 1–4 validation notes describe their original baselines; this record documents the current provider migration.
