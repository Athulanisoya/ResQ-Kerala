# syntax=docker/dockerfile:1
FROM python:3.11-slim-bookworm AS dependencies

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

FROM dependencies AS runtime-base
RUN groupadd --gid 10001 resq \
    && useradd --uid 10001 --gid resq --create-home resq \
    && mkdir -p /app/.runtime \
    && chown -R resq:resq /app
COPY --chown=resq:resq backend/ ./backend/
COPY --chown=resq:resq web/ ./web/
COPY --chown=resq:resq frontend/ ./frontend/
COPY --chown=resq:resq data/ ./data/
COPY --chown=resq:resq scripts/ ./scripts/
USER resq
EXPOSE 8013
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8013/health', timeout=3).close()"]
CMD ["python", "-m", "uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8013", "--workers", "1", "--no-access-log"]

FROM runtime-base AS test
COPY --chown=resq:resq tests/ ./tests/
COPY --chown=resq:resq pytest.ini ./
CMD ["python", "-m", "pytest"]

# Keep a plain `docker build .` production-oriented as well as Compose builds.
FROM runtime-base AS runtime
