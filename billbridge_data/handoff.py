"""Export the validated current PostgreSQL tables for teammates."""

import os
import subprocess
import tempfile
from pathlib import Path

from psycopg.conninfo import conninfo_to_dict, make_conninfo

from billbridge_data.database import connect, database_url
from billbridge_data.files import atomic_write, digest, write_json
from curated.publish import load_collection, publish
from intermediate.model import checked_context, reconcile


def export_database(data: Path, output: Path):
    # Refresh the small file export from the validated tables before dumping.
    publish(data / "raw", data / "staging", data / "curated")
    manifest, records = load_collection(data / "curated")
    with connect() as connection:
        _, stage = checked_context(connection, data / "raw", data / "staging")
        bills, versions, sections, _ = reconcile(connection, data / "raw")
        if sections != records:
            raise ValueError("Database sections differ from the published collection; rerun publish")
        # Manual workflow: do not run stage/model concurrently with this export.
        server_major = connection.info.server_version // 10000
    options = conninfo_to_dict(database_url())
    environment = os.environ.copy()
    if "password" in options:
        environment["PGPASSWORD"] = options.pop("password")
    with tempfile.TemporaryDirectory(prefix="billbridge-export-") as temporary:
        path = Path(temporary) / "billbridge.dump"
        subprocess.run(["pg_dump", "--dbname", make_conninfo(**options), "--no-password",
                        "--format=custom", "--no-owner", "--no-acl",
                        "--schema=staging", "--schema=intermediate", "--file", str(path)],
                       env=environment, check=True)
        payload = path.read_bytes()
    result = {
        "file": "billbridge.dump", "sha256": digest(payload), "bytes": len(payload),
        "postgres_major": server_major, "snapshot_id": manifest["snapshot_id"],
        "staging_rows": stage["counts"],
        "intermediate_rows": {"bills": len(bills), "bill_versions": len(versions), "sections": len(sections)},
    }
    atomic_write(output / "billbridge.dump", payload)
    write_json(output / "manifest.json", result)
    return result
