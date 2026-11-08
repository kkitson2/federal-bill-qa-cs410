"""Build and reconcile physical intermediate tables in one transaction."""

import json

from billbridge_data.contracts import Section
from billbridge_data.database import MODEL_VERSION, connect, table_payloads
from billbridge_data.files import digest
from ingestion.archive import validate_raw
from staging.build import load_stage
from staging.parser import PARSER_VERSION
from intermediate.tables import materialize, verify_materialized


def checked_context(connection, raw, staged):
    source = validate_raw(raw)
    stage = load_stage(staged)
    if stage["model_version"] != MODEL_VERSION or stage["parser_version"] != PARSER_VERSION:
        raise ValueError("Use the parser/model code matching this build, or rerun stage")
    if digest((raw / "manifest.json").read_bytes()) != stage["raw_manifest_sha256"]:
        raise ValueError("Staging belongs to a different raw archive")
    actual = {name: digest(payload) for name, payload in table_payloads(connection).items()}
    if actual != stage["files"]:
        raise ValueError("Staging database rows differ from the verified source export")
    return source, stage


def reconcile(connection, raw):
    selected = {f"{b['congress']}-{b['bill_type']}-{b['number']}"
                for b in json.loads((raw / "selection.json").read_text())["bills"]}
    bills = connection.execute("SELECT * FROM intermediate.bills ORDER BY bill_id").fetchall()
    if {b["bill_id"] for b in bills} != selected:
        raise ValueError("Selected bill coverage differs from staged Congress metadata")
    duplicates = connection.execute("""SELECT package_id FROM staging.congress_text_versions
        WHERE package_id IS NOT NULL GROUP BY package_id HAVING count(*) <> 1""").fetchall()
    if duplicates:
        raise ValueError("Ambiguous Congress-to-GovInfo version match: duplicate package listing")
    listed = connection.execute("""SELECT bill_id, package_id FROM staging.congress_text_versions
        WHERE package_id IS NOT NULL""").fetchall()
    if {v["bill_id"] for v in listed} != selected:
        raise ValueError("Selected bill lacks a supported text version or listing references an unknown bill")
    expected_packages = {v["package_id"] for v in listed}
    packages = {r["package_id"] for r in connection.execute(
        "SELECT package_id FROM staging.govinfo_packages")}
    parsed = {r["package_id"] for r in connection.execute(
        "SELECT DISTINCT package_id FROM staging.govinfo_sections")}
    if expected_packages != packages or expected_packages != parsed:
        raise ValueError("Missing or orphaned source relationship between version listings, packages and sections")
    versions = connection.execute("SELECT * FROM intermediate.bill_versions ORDER BY package_id").fetchall()
    if len(versions) != len(expected_packages) or {v["package_id"] for v in versions} != expected_packages:
        raise ValueError("Cross-source bill/version identity disagreement")
    rows = connection.execute("SELECT * FROM intermediate.sections ORDER BY package_id, record_ordinal").fetchall()
    count = connection.execute("SELECT count(*) AS n FROM staging.govinfo_sections").fetchone()["n"]
    if len(rows) != count or {r["package_id"] for r in rows} != expected_packages:
        raise ValueError("Section identity disagreement or incomplete intermediate join")
    sections = [Section.model_validate({field: row[field] for field in Section.model_fields}) for row in rows]
    if len({s.section_id for s in sections}) != len(sections):
        raise ValueError("Intermediate joins duplicated section records")
    excluded = connection.execute("""SELECT bill_id,version_label,version_date_source AS date,
        exclusion_reason AS reason,formats FROM staging.congress_text_versions
        WHERE package_id IS NULL ORDER BY bill_id, source_resource, source_ordinal""").fetchall()
    verify_materialized(connection)
    return bills, versions, sections, excluded


def model(raw, staged):
    with connect() as connection:
        checked_context(connection, raw, staged)
        materialize(connection)
        bills, versions, sections, excluded = reconcile(connection, raw)
    return {"bills": len(bills), "versions": len(versions),
            "records": len(sections), "excluded_text_listings": len(excluded)}
