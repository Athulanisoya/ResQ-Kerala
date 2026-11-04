# Evidence and human review

The active frontend remains FastAPI/HTMX with the Coast & Canopy theme. These workflows use additive tables and preserve original citizen reports and earlier analysis revisions. They do not merge reports, send clarification requests or apply operational decisions automatically.

## Classifier suggestions

On an administrator's report page, **Predict severity** appends a suggestion with the loaded model artifact's SHA256 version, prediction time, requesting account and report-text hash. It does not create or modify a reviewed assessment or assign a reviewer. Each suggestion exposes **Accept**, **Edit and accept**, and **Reject**. Only an explicit accept/edit decision updates operational severity; other assessment fields are preserved. The original assessment snapshot and deciding administrator/time are audited. Repeated identical decisions cannot reapply an old value over a later manual assessment.

## Source-backed safety assistant

Shelter availability, emergency contacts and safety guidance are retrieved by application-controlled tools using the current question. Critical answers copy facts and reference passages directly from those results. Missing, ambiguous or failed lookups produce an explicit missing-evidence response. A model's free text, a prior turn or an instruction embedded in a question cannot fill a missing result. Report status and summaries still use account-scoped access. Saved evidence check times and source status are visible in conversations; older replies without evidence are labelled unverified.

These boundaries follow the deterministic output validation, least privilege and human review principles in [OWASP's prompt-injection guidance](https://genai.owasp.org/llmrisk/llm01-prompt-injection/). This mitigates unsupported critical facts; it does not establish that a retrieved source or shelter record is currently correct.

## Shelter record freshness

Shelter cards distinguish when the page checked the database from when the record was last updated. A record is **recent**, **stale**, or **unknown**; missing contact details are stated explicitly. `SHELTER_STALE_AFTER_MINUTES` defaults to 30 and accepts 1–1440 minutes. Polling does not update a shelter record's timestamp. Recent data is a recorded update, not an independently confirmed reservation or guaranteed capacity.

## Evidence-linked analysis

**Integrated analysis** presents the original report, administrator-only reporter account details, source-linked suggested values, extracted place names, alert matches, reference passages and shelter snapshots. Translation remains provisional. Available suggestions can be accepted, edited or rejected individually. Decisions are stored as revision-bound reviewed notes; operational severity is managed separately in **Reviewed assessment**. Rejection requires a reason. Later corrections append history, and stale revision or concurrent-tab decisions require a reload. Passwords, bearer tokens and password-reset information are never included in reporter details.

## Location and question clarification

An uncertain location exposes a short follow-up question, matched names and district choices to the report owner and administrators. Confirming a place appends a human confirmation and a sourced alert check without rewriting the original location. Confirming only a district leaves an unlisted locality explicitly unverified. Confirmations carry the original input hash and account/time provenance, and are used by subsequent location checks and integrated analysis.

The **Clarifications** panel suggests editable questions for missing or ambiguous locality, an unspecified people count, or unclear help. These are labelled local missing-fact rules, not unconstrained model-generated instructions. **Use this question** inserts a draft only; an administrator must review and select **Request clarification** to send it. Existing reply, notification and case-closure rules remain in force.

## Duplicate review and evaluation

Candidates are searched across the complete 72-hour window around a report, including known Kerala locality aliases. Matching combines wording with a bounded English/Malayalam incident-concept vocabulary. Explicit negations, conflicting human-confirmed places and different numbered addresses are handled conservatively. Comparisons show both original reports, times, people/help fields and match reasons. An administrator explicitly confirms a related link; both reports retain their independent owners, status and history.

Run the labelled synthetic evaluation with:

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate_duplicates --output .runtime/qa/duplicate-evaluation.json
```

The report includes true/false matches, missed duplicates, precision, recall, F1 and affected case IDs. The fixture includes aliases, English/Malayalam pairs, time boundaries, negation, address differences and deliberate vocabulary gaps. It is a regression benchmark, not a field accuracy estimate. General multilingual embeddings and unrestricted transliteration are not installed; unsupported language, synonyms, gazetteer gaps and different people reporting one event can still produce misses or false matches.

On 4 November 2026, the 21-pair fixture produced 9 true positives, 10 true negatives, 0 false positives and 2 false negatives: precision 1.0, recall 0.818182 and F1 0.9. The misses are `P10-uncovered-vocabulary` and `P11-uncovered-transliteration`; their positive labels remain in the fixture so these limitations remain visible.

## Verification

Focused tests cover assessment isolation, explicit review/audit decisions, missing evidence and injection attempts, record age, reporter privacy, revision races, confirmation permissions and unsent drafts. The duplicate evaluation and browser workflow suite complement those tests. `tests/test_evidence_review_postgres.py` exercises a two-transaction review race with a temporary database schema when `RESQ_TEST_POSTGRES_URL` is configured privately.
