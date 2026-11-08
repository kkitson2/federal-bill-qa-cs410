"""Replace the current source tables transactionally; export files for inspection."""

import json
from pathlib import Path

from psycopg import sql

from billbridge_data.database import MODEL_VERSION, TABLES, connect, ensure_schema, insert_rows, table_payloads
from billbridge_data.files import atomic_write, digest, safe_relative, write_json
from staging.parser import PARSER_VERSION
from ingestion.archive import validate_raw
from staging.sources import extract
from intermediate.tables import clear


def load_stage(root):
    manifest = json.loads((root / "manifest.json").read_text())
    if set(manifest["files"]) != {name + ".jsonl" for name in TABLES}:
        raise ValueError("Incomplete staging table exports")
    for name, checksum in manifest["files"].items():
        if digest(safe_relative(root, name).read_bytes()) != checksum:
            raise ValueError(f"Staging checksum mismatch: {name}")
    return manifest


def build(raw: Path, out: Path):
    source = validate_raw(raw)
    tables, documents = extract(raw, source)
    ensure_schema()
    with connect() as connection:
        clear(connection)
        for table in TABLES:
            connection.execute(sql.SQL("DELETE FROM staging.{}").format(sql.Identifier(table)))
            insert_rows(connection, table, tables[table])
        payloads = table_payloads(connection)
    report = {
        "raw_manifest_sha256": digest((raw / "manifest.json").read_bytes()),
        "parser_version": PARSER_VERSION, "model_version": MODEL_VERSION,
        "files": {name: digest(payload) for name, payload in payloads.items()},
        "counts": {table: len(tables[table]) for table in TABLES}, "documents": documents,
    }
    for name, payload in payloads.items():
        atomic_write(out / name, payload)
    # Write the manifest last. A partial export is detected by checksum checks;
    # rerunning stage repairs it without duplicating database rows.
    write_json(out / "manifest.json", report)
    load_stage(out)
    return {"counts": report["counts"]}
