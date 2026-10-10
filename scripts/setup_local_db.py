"""Own an isolated, reusable PostgreSQL cluster for this Week 1 workspace."""
import argparse
import os
import secrets
import socket
import subprocess
from pathlib import Path

import psycopg
from psycopg import sql
from dotenv import dotenv_values
from sqlalchemy import URL


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
DATA = RUNTIME / "postgres"
BIN = Path(r"C:\Program Files\PostgreSQL\18\bin")
PORT = 5443
DATABASE = "resq_week1"
USER = "resq_local"
PASSFILE = RUNTIME / "pgpass.conf"


def pg_command(name, *arguments, capture=False):
    executable = BIN / f"{name}.exe"
    if not executable.is_file():
        raise RuntimeError(f"PostgreSQL executable is missing: {executable}")
    return subprocess.run(
        [str(executable), *map(str, arguments)], check=False,
        capture_output=capture, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def is_running():
    return (DATA / "PG_VERSION").exists() and pg_command(
        "pg_ctl", "-D", DATA, "status", capture=True
    ).returncode == 0


def port_is_busy():
    with socket.socket() as probe:
        probe.settimeout(1)
        return probe.connect_ex(("127.0.0.1", PORT)) == 0


def write_private_configuration():
    existing = dotenv_values(ROOT / ".env")
    url = URL.create(
        "postgresql+psycopg", username=USER, host="127.0.0.1", port=PORT,
        database=DATABASE, query={"passfile": PASSFILE.as_posix()},
    ).render_as_string(hide_password=False)
    if existing.get("DATABASE_URL") and existing["DATABASE_URL"] != url:
        raise RuntimeError("Existing .env uses a different database. Preserve it before configuring this workspace.")
    values = {
        "DATABASE_URL": url,
        "DATABASE_SCHEMA": "resq_week1",
        "JWT_SECRET": existing.get("JWT_SECRET") or secrets.token_hex(48),
        "JWT_EXPIRE_MINUTES": existing.get("JWT_EXPIRE_MINUTES") or "30",
        "CORS_ORIGINS": "http://127.0.0.1:8013,http://localhost:8013",
        "APP_VERSION": "1.0.0-week1",
    }
    pending = RUNTIME / "env.tmp"
    pending.write_text(
        "# Generated local configuration. Keep this file private.\n"
        + "".join(f"{key}={value}\n" for key, value in values.items()),
        encoding="utf-8",
    )
    os.replace(pending, ROOT / ".env")


def initialize_cluster():
    if (DATA / "PG_VERSION").exists():
        if not (DATA / "global" / "pg_control").is_file() or not (DATA / "pg_hba.conf").is_file():
            raise RuntimeError("PostgreSQL initialization is incomplete. Preserve .runtime/postgres before retrying setup.")
        if not PASSFILE.is_file():
            raise RuntimeError("The cluster exists but its private .runtime/pgpass.conf is missing.")
        return
    if port_is_busy():
        raise RuntimeError(f"Port {PORT} is occupied. This setup will not reuse another project's PostgreSQL.")
    if not PASSFILE.exists():
        PASSFILE.write_text(
            f"127.0.0.1:{PORT}:*:{USER}:{secrets.token_urlsafe(32)}\n",
            encoding="utf-8",
        )
    password = PASSFILE.read_text(encoding="utf-8").strip().rsplit(":", 1)[-1]
    password_file = RUNTIME / "initdb-password.tmp"
    password_file.write_text(password, encoding="utf-8")
    try:
        result = pg_command(
            "initdb", "-D", DATA, "-U", USER, "--pwfile", password_file,
            "--auth-host=scram-sha-256", "--auth-local=scram-sha-256",
            "--encoding=UTF8", "--locale=C",
        )
        if result.returncode:
            raise RuntimeError("PostgreSQL initialization failed. Preserve the runtime directory for diagnosis.")
    finally:
        password_file.unlink(missing_ok=True)
    with (DATA / "postgresql.conf").open("a", encoding="utf-8") as configuration:
        configuration.write(
            "\n# ResQ Kerala Week 1 workspace\nlisten_addresses = '127.0.0.1'\n"
            "port = 5443\nshared_buffers = '64MB'\nmax_connections = 30\n"
        )


def start_cluster():
    if is_running():
        return
    if port_is_busy():
        raise RuntimeError(f"Port {PORT} is occupied by another server; this workspace's cluster was not started.")
    result = pg_command("pg_ctl", "-D", DATA, "-l", RUNTIME / "postgres.log", "-w", "-t", "25", "start")
    if result.returncode:
        raise RuntimeError("PostgreSQL did not start. Check .runtime/postgres.log.")


def database_connection(database):
    return psycopg.connect(
        host="127.0.0.1", port=PORT, user=USER, dbname=database,
        passfile=str(PASSFILE), connect_timeout=5, autocommit=True,
    )


def ensure_database():
    with database_connection("postgres") as connection:
        actual_directory = Path(connection.execute("SHOW data_directory").fetchone()[0]).resolve()
        if actual_directory != DATA.resolve():
            raise RuntimeError("The server on the expected port belongs to another data directory.")
        if connection.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DATABASE,)).fetchone() is None:
            connection.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(DATABASE), sql.Identifier(USER),
            ))
    with database_connection(DATABASE) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {} AUTHORIZATION {}").format(
            sql.Identifier("resq_week1"), sql.Identifier(USER),
        ))
        connection.execute("SELECT 1")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument("--start-only", action="store_true")
    operation.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    if not DATA.resolve().is_relative_to(ROOT.resolve()):
        raise RuntimeError("Refusing to operate on a PostgreSQL data directory outside this workspace.")
    if args.stop:
        if is_running():
            result = pg_command("pg_ctl", "-D", DATA, "-w", "-t", "25", "-m", "fast", "stop")
            if result.returncode:
                raise RuntimeError("PostgreSQL did not stop. Check .runtime/postgres.log.")
        print("This workspace's PostgreSQL cluster is stopped.")
        return
    RUNTIME.mkdir(exist_ok=True)
    if args.start_only:
        if not (DATA / "PG_VERSION").exists() or not PASSFILE.is_file():
            raise RuntimeError("Run scripts/setup.ps1 before starting the application.")
    else:
        write_private_configuration()
        initialize_cluster()
    start_cluster()
    ensure_database()
    print(f"Workspace PostgreSQL ready: 127.0.0.1:{PORT}/{DATABASE}, schema resq_week1.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError) as error:
        raise SystemExit(str(error)) from None
    except psycopg.Error:
        raise SystemExit("PostgreSQL connection/setup failed. Check .runtime/postgres.log and the private pgpass file.") from None
