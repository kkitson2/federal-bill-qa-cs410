"""Restore the committed dump into a new local database; never overwrite one."""

import argparse
import getpass
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="billbridge_shared", help="New local database name")
    parser.add_argument("--host", help="Local PostgreSQL host (default: PGHOST or localhost)")
    parser.add_argument("--port", type=int, help="Local PostgreSQL port (default: PGPORT or 5432)")
    parser.add_argument("--user", help="Local PostgreSQL role (default: PGUSER or your OS username)")
    parser.add_argument("--maintenance-db", help="Existing database used to create the new one (default: postgres)")
    parser.add_argument("--password", action="store_true", help="Prompt once for the local PostgreSQL password; never save it")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", args.database):
        parser.error("Use a lowercase database name with letters, digits or underscores, up to 63 characters")
    if args.port is not None and not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    dump = ROOT / "database/billbridge.dump"
    manifest = json.loads((dump.parent / "manifest.json").read_text())
    if hashlib.sha256(dump.read_bytes()).hexdigest() != manifest["sha256"]:
        raise ValueError("Database dump checksum mismatch")
    required = ("pg_restore", "psql", "createdb", "dropdb")
    missing = [tool for tool in required if not shutil.which(tool)]
    if missing:
        parser.error("Install PostgreSQL 17+ and add its bin directory to PATH. Missing: " + ", ".join(missing))
    version = subprocess.run(["pg_restore", "--version"], check=True, capture_output=True, text=True).stdout
    major = re.search(r"(\d+)\.", version)
    if not major or int(major[1]) < manifest["postgres_major"]:
        parser.error(f"Use pg_restore {manifest['postgres_major']} or newer for this dump")
    host = args.host or os.getenv("PGHOST") or "localhost"
    port = args.port or os.getenv("PGPORT") or "5432"
    user = args.user or os.getenv("PGUSER") or getpass.getuser()
    maintenance = args.maintenance_db or "postgres"
    environment = os.environ.copy()
    if args.password:
        environment["PGPASSWORD"] = getpass.getpass("PostgreSQL password: ")
    location = f"{host}:{port}"
    def run(tool, *options, **kwargs):
        return subprocess.run([tool, "-h", host, "-p", str(port), "-U", user, "--no-password", *options],
                              cwd=ROOT, env=environment, check=True, **kwargs)
    server = run("psql", "-X", "-d", maintenance, "-At", "-v", "ON_ERROR_STOP=1",
                 "-c", "SHOW server_version_num", capture_output=True, text=True)
    if int(server.stdout.strip()) // 10000 < manifest["postgres_major"]:
        parser.error(f"Use a PostgreSQL {manifest['postgres_major']} or newer server for this dump")
    # createdb fails if the destination already exists, protecting local work.
    run("createdb", "--maintenance-db=" + maintenance, args.database)
    try:
        with dump.open("rb") as handle:
            run("pg_restore", "-d", args.database,
                   "--single-transaction", "--exit-on-error", "--no-owner", "--no-acl", stdin=handle)
        for schema, allowed in {
            "staging": {"congress_bills", "congress_text_versions", "govinfo_packages", "govinfo_sections"},
            "intermediate": {"bills", "bill_versions", "sections"},
        }.items():
            for table, expected in manifest[schema + "_rows"].items():
                if table not in allowed:
                    raise ValueError("Unexpected table in manifest")
                count = run("psql", "-X", "-d", args.database, "-At", "-v", "ON_ERROR_STOP=1", "-c",
                               f"SELECT count(*) FROM {schema}.{table}", capture_output=True, text=True)
                if int(count.stdout.strip()) != expected:
                    raise ValueError(f"Restored row count differs for {schema}.{table}")
    except BaseException:
        # Only this newly created destination can be removed on failure.
        run("dropdb", "--maintenance-db=" + maintenance, args.database)
        raise
    print(f"Restored {args.database} on {location}. Four staging tables, three intermediate tables.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        if error.stderr:
            print(error.stderr.strip(), file=sys.stderr)
        raise SystemExit(f"PostgreSQL command failed (exit {error.returncode}). Check the connection settings, authentication and server status.") from None
