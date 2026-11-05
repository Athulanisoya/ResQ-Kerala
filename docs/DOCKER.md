# Docker setup

The Compose stack contains the existing FastAPI/HTMX application, PostgreSQL 18, an Ollama server and a one-shot model installer. The application image uses Python 3.11 and runs as a non-root user. Ollama runs inside Docker with the project's configured local model, `gemma4:e4b-it-q4_K_M`; inference does not require an OpenAI or Gemini API key.

## Requirements

- Docker Engine with Docker Compose, or Docker Desktop using Linux containers. On Windows, enable the WSL 2 backend.
- Python 3.11+ to generate the initial private Docker configuration. The generator uses the standard library; the Windows virtual environment can also run it.
- Allow at least 12 GB of memory for Docker and 20 GB of free disk space as a starting point. The default quantized model download is approximately 6.6 GB. Model inference, context size, image builds and retained database records need additional space and memory.
- Internet access for the first image build and model download. Installed model files persist across subsequent starts.

CPU inference is supported and may be slow. Optional NVIDIA GPU configuration is described below.

## Start

Run these commands from the repository directory:

```powershell
python -m scripts.configure_docker
docker compose --env-file .env.docker up -d --build
```

The generator creates the ignored `.env.docker` file with independent random database and JWT secrets. Keep it private and retain it when restarting an existing database. The Windows `.env`, PostgreSQL cluster and Ollama model cache are separate from this setup.

Use `--env-file .env.docker` on every Compose command so Compose uses the Docker settings rather than the Windows application's `.env`.

Open [the application](http://127.0.0.1:8013) or [API documentation](http://127.0.0.1:8013/docs). If the Windows application is already running on port 8013, use `python -m scripts.configure_docker --port 8014` when creating the configuration and open `http://127.0.0.1:8014` instead. The generator preserves an existing file, including its port. To change that port later, edit only `WEB_PORT` in `.env.docker` and rerun the Compose start command.

Only the application is published to the host, bound to `127.0.0.1`. PostgreSQL and Ollama are accessible to the other containers without publishing their ports. The app explicitly opts into the internal `ollama` hostname; ordinary local configuration continues to allow only loopback model URLs.

Compose waits for the database and Ollama health checks, and for the model installer to finish, before starting the application. On first boot the installer downloads the configured model. Later starts reuse it from the model volume. The application initializes its schema and applies the existing data-preserving migrations during startup.

## Reuse the installed host model

To copy the already installed default model into Docker before the first full start, use this sequence instead of downloading it again:

```powershell
python -m scripts.configure_docker
docker compose --env-file .env.docker up -d db ollama
python -m scripts.import_ollama_model
docker compose --env-file .env.docker up -d --build
```

The importer reads `OLLAMA_MODELS` when set, otherwise `~/.ollama/models`. Use `--source "C:\path\to\models"` for another host cache. It verifies the selected model's manifest and each referenced SHA256 blob before copying, then streams only those files into the container's model volume. It leaves the host files unchanged and does not copy Ollama identity files or other models. The checksum pass and local copy can take several minutes for large weights and temporarily need both host and Docker copies on disk.

This helper supports official library models using a simple `name:tag`; its default matches the stack's `gemma4:e4b-it-q4_K_M`. If choosing another installed model with `--model`, also set the same `OLLAMA_MODEL` in `.env.docker`. The model must support the application's tools. Symbolic links, directory junctions, incomplete downloads and mismatched checksums are rejected. Finish any host model download before importing. On a later full start, the one-shot installer sees the imported model and skips its registry download.

## Demo accounts

Provision the demonstration accounts explicitly after the stack is ready:

```powershell
docker compose --env-file .env.docker exec app python -m backend.seed
New-Item -ItemType Directory -Force .runtime | Out-Null
docker compose --env-file .env.docker cp app:/app/.runtime/demo-accounts.json .runtime/docker-demo-accounts.json
```

Open the copied private file locally for the generated password and citizen, administrator and response-team account details. Do not commit it. The seed command is a demonstration setup action: repeated runs can reset the demo users' names and roles. Normal container startup does not run it automatically.

The database starts empty. Existing Windows accounts, reports and shelters are not imported automatically. Attachments are stored in PostgreSQL alongside their report records. The runtime volume retains the container's generated demo-account details.

## Verify and inspect

```powershell
docker compose --env-file .env.docker ps -a
docker compose --env-file .env.docker logs --tail=100 app ollama-pull
docker compose --env-file .env.docker exec app python -m scripts.verify_docker
docker compose --env-file .env.docker exec ollama ollama list
```

The verification command checks application/database health, the served HTMX frontend and the installed model's tool capability. It prints `Ready` only when these checks pass. A successful one-shot `ollama-pull` container exits with code 0; it does not remain running. Confirm the configured model appears in `ollama list`.

For a bounded real model run using a synthetic location message:

```powershell
docker compose --env-file .env.docker exec app python -m scripts.check_location_agent --live
```

This makes an actual local Ollama inference request and exits unsuccessfully if the agent falls back. It does not submit an incident. Sign in as the demo administrator, submit or open a synthetic report, and check the local model status before running the Gemma agent or integrated analysis. Test the critical assistant's shelter and source checks separately: the app's health endpoint checks its database connection, not model generation quality or external-source freshness. AI results continue to require the application's explicit human review.

Run the isolated Python test suite in its separate image:

```powershell
docker build --target test -t resq-kerala:test .
docker run --rm resq-kerala:test
```

These tests use isolated SQLite databases and mock provider responses. PostgreSQL-only checks skip unless their separate test prerequisites are supplied. This command does not attach the running stack's database, model or runtime volumes. It verifies application behavior without proving that a live model answer is correct.

If startup fails, inspect the relevant service logs:

```powershell
docker compose --env-file .env.docker logs --tail=100 db ollama ollama-pull app
```

- A port-in-use error requires a free `WEB_PORT`.
- A model download failure requires working network access and enough disk space. Retry the start command after correcting the cause.
- An out-of-memory error requires more Docker memory or a smaller tool-capable model configured in `.env.docker`. Model compatibility must be verified before relying on its analyses.
- Database authentication failures after replacing `.env.docker` usually mean its new password does not match the existing volume. Restore the original configuration rather than deleting data.

## Optional NVIDIA GPU

The default stack runs on CPU. For a supported NVIDIA GPU with working Docker GPU access, include the override on every Compose command for that stack:

```powershell
docker compose --env-file .env.docker -f compose.yaml -f compose.gpu.yaml up -d --build
docker compose --env-file .env.docker -f compose.yaml -f compose.gpu.yaml exec ollama ollama ps
```

The override reserves an NVIDIA GPU only for Ollama. It does not install GPU drivers or the NVIDIA Container Toolkit. Follow [Ollama's official Docker instructions](https://docs.ollama.com/docker) for host support and prerequisites. The override does not enable AMD or Apple GPU acceleration.

Keep both `-f compose.yaml -f compose.gpu.yaml` options on subsequent start, stop and recreate commands for a GPU stack. The model import helper targets the same Compose project, but its printed start command uses the CPU defaults; use the GPU start command above after importing when GPU acceleration is intended.

## Stop, restart and preserve data

```powershell
docker compose --env-file .env.docker down
docker compose --env-file .env.docker up -d --build
```

Named volumes retain PostgreSQL records, Ollama models and runtime credentials across these commands. Rebuilding the application image does not replace the database or download an already installed model again.

**`docker compose down -v` deletes this stack's named volumes, including all database records and installed model files.** Use it only when intentionally discarding the Docker installation's data. Back up the database and private configuration before migrations or an intentional reset. Do not attach the Windows PostgreSQL data directory to the Linux database container; use a PostgreSQL logical dump and restore for a deliberate migration.

The image excludes private environment files, local runtime data, virtual environments and Git history. Model weights are installed into the Ollama volume on first boot rather than copied into the application image. This avoids bundling the host's private configuration and keeps the model reusable when rebuilding the app.

Compose dependency behavior follows Docker's documented [startup and shutdown order](https://docs.docker.com/compose/how-tos/startup-order/).
