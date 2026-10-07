"""Create an isolated PostgreSQL database using the installed Windows binaries."""
import os
import secrets
import subprocess
from pathlib import Path

import psycopg2
from psycopg2 import sql
from sqlalchemy import URL

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
DATA = RUNTIME / "postgres"
BIN = Path(r"C:\Program Files\PostgreSQL\18\bin")
PORT = 5442


def main():
    if (DATA / "PG_VERSION").exists():
        raise SystemExit("Project database already exists; use scripts/start.ps1.")
    RUNTIME.mkdir(exist_ok=True)
    password = secrets.token_urlsafe(32)
    passfile = RUNTIME / "pgpass.conf"
    passfile.write_text(f"127.0.0.1:{PORT}:*:resq_local:{password}\n", encoding="utf-8")
    url = URL.create(
        "postgresql+psycopg2", username="resq_local",
        host="127.0.0.1", port=PORT, database="resq_kerala",
        query={"passfile": passfile.as_posix()},
    ).render_as_string(hide_password=False)
    temp = RUNTIME / "env.tmp"
    temp.write_text("# Local PostgreSQL database for this project.\nDATABASE_URL=" + url + "\n", encoding="utf-8")
    os.replace(temp, ROOT / ".env")
    password_file = RUNTIME / "initdb-password.tmp"
    password_file.write_text(password, encoding="utf-8")
    try:
        subprocess.run([
            str(BIN / "initdb.exe"), "-D", str(DATA), "-U", "resq_local",
            "--pwfile", str(password_file), "--auth-host=scram-sha-256",
            "--auth-local=scram-sha-256", "--encoding=UTF8", "--locale=C",
        ], check=True)
    finally:
        password_file.unlink(missing_ok=True)
    with (DATA / "postgresql.conf").open("a", encoding="utf-8") as config:
        config.write("\nlisten_addresses = '127.0.0.1'\nport = 5442\nshared_buffers = '64MB'\nmax_connections = 30\n")
    subprocess.run([
        str(BIN / "pg_ctl.exe"), "-D", str(DATA), "-l", str(RUNTIME / "postgres.log"),
        "-w", "start",
    ], check=True)
    connection = psycopg2.connect(
        host="127.0.0.1", port=PORT, user="resq_local", password=password, dbname="postgres"
    )
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier("resq_kerala"), sql.Identifier("resq_local")
            ))
    finally:
        connection.close()
    print("Configured .env for 127.0.0.1:5442/resq_kerala. Password saved in .runtime/pgpass.conf.")


if __name__ == "__main__":
    main()
