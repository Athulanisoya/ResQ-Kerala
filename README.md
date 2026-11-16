# ResQ Kerala

ResQ Kerala brings flood reporting, response coordination, shelter access, alerts, and community support into one workspace. Citizens report incidents and follow their progress. Administrators review reports and coordinate services. Response teams carry out assignments, record field progress, and deliver relief.

The application uses FastAPI, PostgreSQL, and an HTMX frontend with the Coast & Canopy theme. The web app serves the interface and JSON API together.

## Run locally

### Docker

Install Docker with Compose and Python 3.11 or later, then run from the repository root.

```powershell
python -m scripts.configure_docker
docker compose --env-file .env.docker up -d --build
```

Open the app at [localhost:8013](http://127.0.0.1:8013). Compose runs the application, PostgreSQL, and Ollama. The first start downloads the default Gemma 4 model (`gemma4:e4b-it-q4_K_M`, about 6.6 GB). Later starts reuse the saved model and database volumes. To run Docker alongside the Windows instance, use `python -m scripts.configure_docker --port 8014` when creating the configuration, or set `WEB_PORT=8014` in the existing private `.env.docker`.

After startup, provision the three demo roles and copy their generated credentials to a local file.

```powershell
docker compose --env-file .env.docker exec app python -m backend.seed
New-Item -ItemType Directory -Force .runtime | Out-Null
docker compose --env-file .env.docker cp app:/app/.runtime/demo-accounts.json .runtime/docker-demo-accounts.json
```

Keep `.env.docker` and the demo credentials private. For GPU setup, model import, troubleshooting, and stopping the stack while retaining data, see the [Docker guide](docs/DOCKER.md).

### Windows

Install Python 3.11 or later and PostgreSQL 18 with binaries at `C:\Program Files\PostgreSQL\18\bin`. Run the setup and start scripts from the repository root.

```powershell
.\scripts\setup.ps1 -PythonCommand python
.\scripts\start.ps1
```

Setup installs dependencies in `.venv`, prepares the workspace database on port 5443, and writes demo credentials to `.runtime/demo-accounts.json`. Open [localhost:8013](http://127.0.0.1:8013). Run `.\scripts\stop.ps1` to stop the workspace services. If startup fails, check `.runtime/postgres.log`, `.runtime/web.log`, and `.runtime/web-error.log`.

### Sign in

Use the demo credential file for your setup to open citizen, administrator, and response team accounts. Public registration creates a citizen account. To try the full workflow in one browser, sign in to each role in a separate tab. Sessions are scoped to the tab. **My account** shows the signed-in role and team, and **Notifications** in the header opens the private inbox. Password recovery requires a configured SMTP service. [Account and recovery setup](docs/CITIZEN-SERVICES.md#password-recovery)

## Follow a report from submission to closure

1. **Citizen submits a report.** Open **More services → New report**. Describe the flooding and give the location. Include an estimate of the people affected and the help needed when known. The application saves a draft summary and Kerala location check alongside the original report. Open **My reports** to search and filter submissions. Use **Messages & files** to add photos or audio to an open report after submission. [Attachments](docs/CITIZEN-SERVICES.md#photo-and-voice-attachments)
2. **Administrator reviews the report.** Open **Report queue** and read the original details in **Overview**. Use **Review** to update the status, record the assessment, and decide whether an investigation is needed. Use **Analysis** to review the draft summary, location and alert match, integrated analysis, and possible duplicates. Confirm related reports as links so each retains its own status and history.
3. **Citizen and administrator clarify missing facts.** The reporter or an administrator can confirm the location when the app finds several matches or needs more detail. **Messages & files** lets administrators edit a suggested question and send it, and lets citizens reply to open requests. The original report, location confirmation, and replies remain available for review.
4. **Administrator assigns a verified report.** In **Response**, choose an available team. Suggestions use the incident location, declared operating areas, and required capabilities. The administrator confirms the assignment.
5. **Response team records field progress.** Open **Assignments**, select the report, and use **Response** to accept the task, mark it **En Route**, start field work, and mark it **Resolved**. Add notes as the work progresses. Citizens can follow progress in their report, and teams can review earlier assignments in **Past tasks**.
6. **Administrator reviews and closes the case.** Open **Response** after the team resolves the incident. Complete outstanding relief work and investigations and resolve any required clarification requests before closing the report. The progress bar shows the current stage, and **History** shows recorded status changes and notes.

### Report offline

Open **New report** while connected to prepare it for offline use. **Save draft** stores an unsent draft in the current browser. **Submit report** queues a completed report when the connection is unavailable. The open app retries when connectivity returns with the same citizen account. If the app was closed or the session expired, reopen it and sign in to resume. Retries use the same submission ID, and the queue shows **Submitted** when the server confirms receipt. [Offline reporting workflow](docs/OFFLINE-REPORTING.md)

### Coordinate relief and investigations

- **Relief & supplies** lets citizens request supply delivery or rescue support for a report they own. Administrators maintain stock and its adjustment history, create linked requests, and assign eligible teams. Assigned teams can record partial deliveries, see remaining demand, and complete rescue support. Supply deliveries validate and deduct stock in the recorded item unit.
- An administrator can hand an in-progress rescue case to a Relief team from **Response**. The former team retains its assignment snapshot in **Past tasks**.
- In **Review**, administrators can assign an investigation to an eligible team or record a reviewer and findings. Assigned Investigation teams use **More services → Investigations** to review their cases and record findings and actions. Completed findings remain available for review.

## Use alerts, maps, and shelters

- **Official alerts** lets administrators create, edit, schedule, and expire district or locality alerts using Indian Standard Time. All roles can view active alerts and follow districts or localities for private in-app notifications. The **Overview** map shows active red, orange, and yellow alert levels. Green indicates no active alert recorded in the app, and grey indicates unavailable coverage. Zoom in for mapped locality centres and shelter pins. [Map coverage](docs/OVERVIEW-MAP.md#explore-alerts)
- **Shelters** and map pins show recorded spaces, contacts, and update and staff confirmation times. Use location, availability, or confirmed facility filters to narrow the list. Browser location is optional, and map distances are straight-line estimates. Check with reception about current availability and support. [Shelter facilities](docs/SHELTER-FACILITIES.md)
- **Register to join** lets a citizen reserve spaces for a group. Citizens can review their registrations and cancel before arrival. When spaces are unavailable, citizens can join a waiting list, receive an expiring offer, and accept it to reserve the held spaces. [Shelter registration](docs/OVERVIEW-MAP.md#find-and-register-for-a-shelter) · [Waiting lists and offers](docs/AUTOMATIONS.md#shelter-waiting-lists)
- In **Shelters → Add shelter**, administrators can create a shelter and designate a Shelter team. Administrators and the designated team can update and confirm capacity and facilities, manage reservations, and record arrivals and departures. The app refreshes listings while open and can remind staff when a capacity confirmation is overdue. [Capacity confirmation reminders](docs/AUTOMATIONS.md#capacity-confirmation-reminders)

## Use community and household services

| Service | Workflow |
| --- | --- |
| **Community updates** | Administrators draft, verify, and publish news. Signed-in users can read published updates on **Community**. |
| **Donation pledges** | From **Community**, pledge money in INR or supplies for general relief or an active campaign. Administrators manage campaigns and manually mark pledges received or rejected. Pledges are records for reconciliation. Payment collection takes place outside the app. |
| **Volunteer hub** | Citizens submit applications. Administrators review them, publish shifts, and record attendance. Approved volunteers can join eligible shifts with available places and cancel future signups. [Volunteer workflow](docs/VOLUNTEERS.md) |
| **Family safety** | Create a private circle, invite existing accounts, and share your own check-in with members who accept. Location and shelter details are optional and shared with consent. [Family circles](docs/FAMILY-SAFETY.md) |
| **Household preparedness** | Save a private English or Malayalam checklist, meeting points, household contacts, and assistance notes. Print the saved plan from the browser. [Preparedness plans](docs/PREPAREDNESS.md) |

## Manage the workspace

Open **More services → Administration** as an administrator.

| Section | What you can do |
| --- | --- |
| **Create a team** | Create a Rescue, Relief, Shelter, or Investigation team and provision member logins. |
| **Account management** | Search by name or email, then update a role, team membership, or account access. Access changes revoke affected sessions. |
| **Response teams** | Manage team names and availability, and configure operating areas and capabilities for assignment suggestions. |
| **Aggregate reports** | Review incidents, teams, shelter occupancy, relief, campaigns, and pledges. Each relief ledger and donation unit has its own totals. |

Use **Automation settings** to review job status, adjust reminder and offer timing, or run checks immediately. Scheduled jobs deliver followed-area alerts and capacity reminders and manage waiting-list offers while the application is running. [Automation workflows](docs/AUTOMATIONS.md)

## Safety assistant and analysis

- **Safety assistant.** Open the floating chat button from any signed-in workspace. Ask about shelters, emergency contacts, safety guidance, or reports you can access. Follow-up questions use recent conversation context and check fresh records for critical facts. **Sources and evidence** shows source links and review information. Chats are private to the account, and **Conversations** and **New chat** let you resume or start a conversation.
- **Location and summary.** The local geography check recognizes catalog aliases, including Malayalam, and records uncertainty. **Analyze location** checks active alert evidence, and **Run Gemma 4 agent** can use the configured local model for the location and alert checks. **Generate summary** and **Refresh summary** produce local drafts for review. The original and reviewed assessment are stored separately.
- **Severity.** **Predict severity** adds a separate suggestion with the model version and timestamp. An administrator can accept, edit and accept, or reject it. The reviewed severity changes only through an explicit assessment or acceptance action.
- **Integrated analysis.** In **Analysis**, run the evidence checks and review the versioned results next to the original report. Administrators can inspect allowed reporter account details, review provisional translations and extracted values, and accept, edit, or reject individual suggestions. The optional local model can help with draft translation and summary. An administrator makes the final assessment and assignment decisions. [Analysis workflow](docs/AI-WORKFLOW.md#integrated-analysis-shelters-and-safety-assistant) · [Evidence and review](docs/REVIEW-EVIDENCE.md)

Docker configures the default local model. For optional model features in the Windows setup, start Ollama, install the model, and configure the app before starting it.

```powershell
ollama pull gemma4:e4b-it-q4_K_M
.\.venv\Scripts\python.exe -m scripts.configure_ollama
```

If the app is running, restart it after configuration. See the [local model guide](docs/OLLAMA-MIGRATION.md) for model settings and verification.

## Verify and explore

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m scripts.verify_local
node --test tests/session_client.cjs
node tests/offline_worker.cjs
```

The Windows readiness check requires a running app. For Docker, use `docker compose --env-file .env.docker exec app python -m scripts.verify_docker`. The Python suite uses isolated fixtures, and optional PostgreSQL checks use disposable schemas configured through `RESQ_TEST_POSTGRES_URL`. Browser workflows in `tests/` use Playwright and a local demo instance. The [Docker guide](docs/DOCKER.md#verify-and-inspect) also covers running the isolated test image.

Open [API documentation](http://127.0.0.1:8013/docs) on the running app, using your configured port. The API groups endpoints by reporting, operations, alerts, shelters, community services, and administration. Protected endpoints use the signed-in account's bearer session and role permissions. Keep generated configuration and runtime data out of version control. Back up existing PostgreSQL data before upgrading a deployment.
