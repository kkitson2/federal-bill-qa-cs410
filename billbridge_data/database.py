"""Local database primitives shared by the stage, model and publication steps."""

import json
import os
from contextlib import contextmanager
from datetime import date, datetime
from importlib.resources import files

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

MODEL_VERSION = "sources-sql-1"
TABLES = {
    "congress_bills": "bill_id",
    "congress_text_versions": "source_resource, source_ordinal",
    "govinfo_packages": "package_id",
    "govinfo_sections": "package_id, record_ordinal",
}
JSON_COLUMNS = {"source_payload", "formats", "short_titles", "hierarchy", "blocks", "annotations"}


def database_url():
    return os.getenv("DATABASE_URL", "postgresql://billbridge:billbridge-local-only@127.0.0.1:55433/billbridge_data")


@contextmanager
def connect():
    try:
        connection = psycopg.connect(database_url(), row_factory=dict_row, connect_timeout=5)
    except psycopg.OperationalError:
        raise RuntimeError("PostgreSQL is unavailable. Start your local PostgreSQL server and check DATABASE_URL in .env") from None
    with connection:
        connection.execute("SET TIME ZONE 'UTC'")
        yield connection


def ensure_schema():
    with connect() as connection:
        connection.execute(files("billbridge_data").joinpath("sql/schema.sql").read_text())


def serializable(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Unsupported database export type: {type(value).__name__}")


def jsonl(records):
    return b"".join((json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                                default=serializable) + "\n").encode() for r in records)


def table_payloads(connection):
    payloads = {}
    for table, ordering in TABLES.items():
        query = sql.SQL("SELECT * FROM staging.{} ORDER BY " + ordering).format(sql.Identifier(table))
        payloads[table + ".jsonl"] = jsonl(connection.execute(query).fetchall())
    return payloads


def insert_rows(connection, table, rows):
    if not rows:
        return
    columns = list(rows[0])
    query = sql.SQL("INSERT INTO staging.{} ({}) VALUES ({})").format(
        sql.Identifier(table), sql.SQL(",").join(map(sql.Identifier, columns)),
        sql.SQL(",").join(sql.Placeholder() for _ in columns))
    values = [[Jsonb(row[c]) if c in JSON_COLUMNS else row[c] for c in columns] for row in rows]
    with connection.cursor() as cursor:
        cursor.executemany(query, values)
