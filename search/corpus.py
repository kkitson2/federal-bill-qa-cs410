"""Load bill sections from the restored Group 1 database."""

from __future__ import annotations

import os
from dataclasses import dataclass

# Matches the Docker setup in compose.yaml plus the restored `billbridge_shared` database.
DEFAULT_DATABASE_URL = "postgresql://billbridge:billbridge-local-only@127.0.0.1:55433/billbridge_shared"


@dataclass(frozen=True)
class Section:
    section_id: str
    package_id: str
    bill: str  # e.g. "HR 1165"
    version_label: str
    number: str
    heading: str
    title: str
    text: str
    citation: str
    source_url: str
    record_type: str


def database_url() -> str:
    return os.getenv("SEARCH_DATABASE_URL") or DEFAULT_DATABASE_URL


_QUERY = """
SELECT section_id, package_id, upper(bill_type) || ' ' || bill_number AS bill,
       coalesce(version_label, version, ''), coalesce(number, ''), coalesce(heading, ''),
       coalesce(title, ''), coalesce(text, ''), coalesce(citation, ''),
       coalesce(source_url, ''), coalesce(record_type, '')
FROM intermediate.sections
ORDER BY package_id, record_ordinal
"""


def load_sections(url: str | None = None) -> list[Section]:
    """Read every record of intermediate.sections, in a stable order."""
    import psycopg  # imported lazily so the rest of the package works without a database

    try:
        with psycopg.connect(url or database_url(), connect_timeout=5) as conn:
            rows = conn.execute(_QUERY).fetchall()
    except psycopg.Error as error:
        raise RuntimeError(
            "Could not read intermediate.sections. Is the database running and restored? "
            "(`docker compose up -d db`, see search/README.md; or set SEARCH_DATABASE_URL). "
            f"Driver said: {str(error).strip().splitlines()[0] if str(error).strip() else type(error).__name__}"
        ) from error
    if not rows:
        raise RuntimeError("intermediate.sections is empty; restore database/billbridge.dump first")
    return [Section(*row) for row in rows]
