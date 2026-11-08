"""Opt-in end-to-end restore against a disposable native PostgreSQL cluster."""

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile

import psycopg
import pytest


@pytest.mark.skipif(os.getenv("BILLBRIDGE_TEST_LOCAL_RESTORE") != "1", reason="Set BILLBRIDGE_TEST_LOCAL_RESTORE=1 with native PostgreSQL 17+ installed")
def test_native_restore_without_docker_and_existing_database_protection():
    root = Path(__file__).resolve().parents[1]
    required = ("initdb", "pg_ctl", "pg_restore", "createdb", "dropdb", "psql")
    if any(not shutil.which(tool) for tool in required):
        pytest.fail("Native PostgreSQL binaries are required for this integration test")
    binaries = Path(shutil.which("pg_ctl")).parent
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    # A short socket path also works on macOS, whose Unix socket paths are limited.
    with tempfile.TemporaryDirectory(prefix="bb-local-", dir="/tmp") as directory:
        work = Path(directory)
        cluster = work / "cluster"
        password = "disposable-local-restore-test"
        pwfile = work / "password"
        pwfile.write_text(password + "\n")
        pwfile.chmod(0o600)
        environment = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
        environment.update(PATH=str(binaries) + os.pathsep + os.defpath, PGHOST="127.0.0.1",
                           PGPORT=str(port), PGUSER="billbridge_test", PGPASSWORD=password)
        assert shutil.which("docker", path=environment["PATH"]) is None
        def command(*args):
            return subprocess.run(args, cwd=root, env=environment, capture_output=True, text=True, check=True)
        command(str(binaries / "initdb"), "-D", str(cluster), "-U", "billbridge_test",
                "--auth-local=trust", "--auth-host=scram-sha-256", "--pwfile=" + str(pwfile))
        started = False
        try:
            command(str(binaries / "pg_ctl"), "-D", str(cluster), "-l", str(work / "server.log"),
                    "-o", f"-h 127.0.0.1 -p {port} -k {work}", "-w", "start")
            started = True
            result = command(sys.executable, str(root / "scripts/restore_database.py"))
            assert "Restored billbridge_shared" in result.stdout
            prompted_environment = {k: v for k, v in environment.items() if k != "PGPASSWORD"}
            prompted = subprocess.run([sys.executable, str(root / "scripts/restore_database.py"),
                "--database", "billbridge_prompted", "--password"], cwd=root, env=prompted_environment,
                input=password + "\n", capture_output=True, text=True, check=True)
            assert "Restored billbridge_prompted" in prompted.stdout
            assert password not in prompted.stdout + prompted.stderr
            manifest = json.loads((root / "database/manifest.json").read_text())
            with psycopg.connect(host="127.0.0.1", port=port, user="billbridge_test", password=password,
                                 dbname="billbridge_shared") as connection:
                for schema in ("staging", "intermediate"):
                    for table, expected in manifest[schema + "_rows"].items():
                        from psycopg import sql
                        actual = connection.execute(sql.SQL("SELECT count(*) FROM {}.{}").format(
                            sql.Identifier(schema), sql.Identifier(table))).fetchone()[0]
                        assert actual == expected
                assert connection.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema IN ('staging','intermediate','ops') AND table_type='BASE TABLE'").fetchone()[0] == 7
            repeated = subprocess.run([sys.executable, str(root / "scripts/restore_database.py")],
                                      cwd=root, env=environment, capture_output=True, text=True)
            assert repeated.returncode != 0 and "already exists" in repeated.stderr
            assert password not in result.stdout + result.stderr + repeated.stdout + repeated.stderr
            assert command(str(binaries / "psql"), "-X", "-d", "billbridge_shared", "-At", "-c",
                           "SELECT count(*) FROM intermediate.sections").stdout.strip() == "408"
        finally:
            if started:
                command(str(binaries / "pg_ctl"), "-D", str(cluster), "-m", "fast", "-w", "stop")
