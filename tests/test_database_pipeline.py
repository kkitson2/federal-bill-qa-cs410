"""Real PostgreSQL integration checks, using a disposable database only."""

import gzip
import json
import os
import uuid
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import pytest

from test_pipeline import raw_collection  # Shared mock government API fixture.
from billbridge_data.database import TABLES, connect, ensure_schema
from billbridge_data.files import digest, json_bytes, write_json
from curated.publish import load_collection, publish
from intermediate.model import model
from staging.build import build


@pytest.fixture(scope="session")
def test_database_url():
    target = os.getenv("BILLBRIDGE_TEST_DATABASE_URL")
    if not target:
        pytest.skip("Set BILLBRIDGE_TEST_DATABASE_URL to a local cluster to run PostgreSQL integration tests")
    parameters = conninfo_to_dict(target)
    if parameters.get("host") not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("Disposable test databases are created on a local PostgreSQL cluster only")
    name = "billbridge_test_" + uuid.uuid4().hex[:16]
    with psycopg.connect(target, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        yield make_conninfo(target, dbname=name)
    finally:
        with psycopg.connect(target, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def db(test_database_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    ensure_schema()


def change_resource(raw, name, change):
    manifest = json.loads((raw / "manifest.json").read_text())
    receipt = manifest["resources"][name]
    body = gzip.decompress((raw / receipt["path"]).read_bytes())
    value = json.loads(body) if name.endswith(".json") else body
    value = change(value)
    body = json_bytes(value) if name.endswith(".json") else value
    (raw / receipt["path"]).write_bytes(gzip.compress(body, mtime=0))
    receipt.update(sha256=digest(body), bytes=len(body))
    write_json(raw / (name + ".receipt.json"), receipt)
    write_json(raw / "manifest.json", manifest)


def counts():
    with connect() as connection:
        return {table: connection.execute(sql.SQL("SELECT count(*) AS n FROM staging.{}").format(
            sql.Identifier(table))).fetchone()["n"] for table in TABLES}


def test_sql_sources_reconcile_and_publish(db, tmp_path, raw_collection, monkeypatch):
    raw = raw_collection
    change_resource(raw, "congress/bill_details/118-hr-1.json", lambda j: {"bill": {**j["bill"], "title": "Current Congress title"}})
    change_resource(raw, "govinfo/package_summaries/BILLS-118hr1ih.json", lambda j: {**j, "title": "GovInfo version title"})
    xml = b'''<bill><legis-body><section><enum>1.</enum><text>Protect <phrase changed="added">all</phrase> records.</text></section></legis-body></bill>'''
    change_resource(raw, "govinfo/bill_xml/BILLS-118hr1ih.xml", lambda _: xml)
    # The raw manifest's old enrichment must not drive any staging/model values.
    metadata = json.loads((raw / "manifest.json").read_text())
    metadata["versions"][0]["title"] = "WRONG MERGED TITLE"
    metadata["bills"][0]["current_title"] = "WRONG MERGED BILL TITLE"
    write_json(raw / "manifest.json", metadata)
    staged, curated = tmp_path / "stage", tmp_path / "curated"
    first = build(raw, staged)
    assert build(raw, staged) == first
    assert counts() == {"congress_bills": 1, "congress_text_versions": 2, "govinfo_packages": 1, "govinfo_sections": 1}
    with connect() as connection:
        b = connection.execute("SELECT current_title FROM staging.congress_bills").fetchone()
        s = connection.execute("SELECT * FROM staging.govinfo_sections").fetchone()
        assert b["current_title"] == "Current Congress title"
        assert "title" not in s and "version_label" not in s
        assert s["annotations"][0]["value"] == "added"
    with pytest.raises(ValueError, match="Selected bill coverage"):
        publish(raw, staged, curated)
    assert model(raw, staged)["records"] == 1
    publish(raw, staged, curated)
    manifest, records = load_collection(curated)
    assert records[0].title == "GovInfo version title" and records[0].heading == ""
    assert records[0].publication_date is None
    assert records[0].annotations[0].value == "added"
    assert json.loads((curated / "bills.jsonl").read_text())["current_title"] == "Current Congress title"
    before = {p.name: p.read_bytes() for p in curated.iterdir()}
    build(raw, staged)
    model(raw, staged)
    publish(raw, staged, curated)
    assert {p.name: p.read_bytes() for p in curated.iterdir()} == before
    (curated / "sections.jsonl").write_text("corrupted")
    with pytest.raises(ValueError, match="checksum"):
        load_collection(curated)
    publish(raw, staged, curated)
    assert load_collection(curated)[0] == manifest


def test_nullable_source_dates(db, tmp_path, raw_collection):
    change_resource(raw_collection, "congress/text_versions/118-hr-1/page-000.json",
                    lambda j: {**j, "textVersions": [{**v, "date": None} for v in j["textVersions"]]})
    staged, curated = tmp_path / "stage", tmp_path / "curated"
    build(raw_collection, staged)
    model(raw_collection, staged)
    publish(raw_collection, staged, curated)
    assert load_collection(curated)[1][0].version_date is None


@pytest.mark.parametrize("problem,expected", [
    ("duplicate", "Ambiguous"), ("identity", "identity disagreement"),
    ("missing_package", "Missing or orphaned"), ("missing_xml", "Missing or orphaned"),
    ("missing_bill", "Selected bill coverage"),
])
def test_model_rejects_incomplete_and_ambiguous_sources(db, tmp_path, raw_collection, problem, expected):
    raw = raw_collection
    if problem == "duplicate":
        change_resource(raw, "congress/text_versions/118-hr-1/page-000.json", lambda j: {**j, "textVersions": j["textVersions"] * 2})
    elif problem == "identity":
        change_resource(raw, "govinfo/package_summaries/BILLS-118hr1ih.json", lambda j: {**j, "congress": "119"})
    else:
        resource = {"missing_package": "govinfo/package_summaries/BILLS-118hr1ih.json", "missing_xml": "govinfo/bill_xml/BILLS-118hr1ih.xml",
                    "missing_bill": "congress/bill_details/118-hr-1.json"}[problem]
        manifest = json.loads((raw / "manifest.json").read_text())
        del manifest["resources"][resource]
        write_json(raw / "manifest.json", manifest)
    staged = tmp_path / "stage"
    result = build(raw, staged)
    with pytest.raises(ValueError, match=expected):
        model(raw, staged)
    with pytest.raises(ValueError):
        publish(raw, staged, tmp_path / "curated")
    assert not (tmp_path / "curated").exists()


def test_staging_cast_failure_rolls_back_all_tables(db, tmp_path, raw_collection):
    raw = raw_collection
    build(raw, tmp_path / "stage")
    model(raw, tmp_path / "stage")
    change_resource(raw, "govinfo/package_summaries/BILLS-118hr1ih.json", lambda j: {**j, "dateIssued": "not-a-date"})
    previous = counts()
    with pytest.raises(psycopg.DataError):
        build(raw, tmp_path / "stage")
    assert counts() == previous
    with connect() as connection:
        assert connection.execute("SELECT count(*) AS n FROM intermediate.sections").fetchone()["n"] == 1
    assert (raw / "govinfo/package_summaries/BILLS-118hr1ih.json.gz").exists()


def test_modified_database_rows_cannot_be_published(db, tmp_path, raw_collection):
    staged = tmp_path / "stage"
    result = build(raw_collection, staged)
    with connect() as connection:
        connection.execute("UPDATE staging.govinfo_sections SET heading='modified'")
    with pytest.raises(ValueError, match="differ from the verified"):
        model(raw_collection, staged)
    build(raw_collection, staged)  # Rebuild from the verified archive, not the edited row.
    assert model(raw_collection, staged)["records"] == 1


def test_changed_collection_replaces_current_files_without_new_directory(db, tmp_path, raw_collection):
    raw, staged, curated = raw_collection, tmp_path / "stage", tmp_path / "curated"
    build(raw, staged)
    model(raw, staged)
    publish(raw, staged, curated)
    original_id = load_collection(curated)[1][0].section_id
    change_resource(raw, "govinfo/package_summaries/BILLS-118hr1ih.json",
                    lambda j: {**j, "title": "Corrected version title"})
    build(raw, staged)
    with pytest.raises(ValueError):
        publish(raw, staged, curated)  # Must model the replaced staging tables first.
    model(raw, staged)
    publish(raw, staged, curated)
    records = load_collection(curated)[1]
    assert len(records) == 1 and records[0].title == "Corrected version title"
    assert records[0].section_id == original_id


def test_interrupted_publication_is_detected_and_retry_repairs_it(db, tmp_path, raw_collection, monkeypatch):
    import importlib
    module = importlib.import_module("curated.publish")
    raw, staged, curated = raw_collection, tmp_path / "stage", tmp_path / "curated"
    build(raw, staged)
    model(raw, staged)
    publish(raw, staged, curated)
    change_resource(raw, "govinfo/package_summaries/BILLS-118hr1ih.json",
                    lambda j: {**j, "title": "Updated title"})
    build(raw, staged)
    model(raw, staged)
    original = module.atomic_write
    def interrupted(path, payload):
        if path.name == "sections.jsonl":
            raise OSError("Simulated disk interruption")
        original(path, payload)
    monkeypatch.setattr(module, "atomic_write", interrupted)
    with pytest.raises(OSError, match="Simulated"):
        publish(raw, staged, curated)
    with pytest.raises(ValueError, match="checksum"):
        load_collection(curated)
    monkeypatch.setattr(module, "atomic_write", original)
    publish(raw, staged, curated)
    assert load_collection(curated)[1][0].title == "Updated title"


def test_intermediate_tables_store_rows_and_publication_checks_freshness(db, tmp_path, raw_collection):
    staged, curated = tmp_path / "stage", tmp_path / "curated"
    build(raw_collection, staged)
    model(raw_collection, staged)
    with connect() as connection:
        types = connection.execute("SELECT table_type FROM information_schema.tables WHERE table_schema='intermediate'").fetchall()
        assert len(types) == 3 and {r["table_type"] for r in types} == {"BASE TABLE"}
        title = connection.execute("SELECT current_title FROM intermediate.bills").fetchone()["current_title"]
        connection.execute("UPDATE staging.congress_bills SET current_title='Not yet modeled'")
        assert connection.execute("SELECT current_title FROM intermediate.bills").fetchone()["current_title"] == title
        connection.rollback()
    with connect() as connection:
        connection.execute("UPDATE intermediate.bill_versions SET title='Wrong title'")
    with pytest.raises(ValueError, match="differ from staging-derived"):
        publish(raw_collection, staged, curated)
    model(raw_collection, staged)
    publish(raw_collection, staged, curated)
    assert load_collection(curated)[1][0].title == "Test bill"


def test_intermediate_rebuild_rolls_back_and_restage_invalidates_it(db, tmp_path, raw_collection, monkeypatch):
    import importlib
    module = importlib.import_module("intermediate.model")
    staged = tmp_path / "stage"
    build(raw_collection, staged)
    model(raw_collection, staged)
    with connect() as connection:
        connection.execute("UPDATE intermediate.sections SET heading='Previous stored value'")
    original = module.reconcile
    def fail_after_materialization(connection, raw):
        assert connection.execute("SELECT heading FROM intermediate.sections").fetchone()["heading"] == ""
        raise ValueError("Simulated model validation failure")
    monkeypatch.setattr(module, "reconcile", fail_after_materialization)
    with pytest.raises(ValueError, match="Simulated"):
        model(raw_collection, staged)
    with connect() as connection:
        assert connection.execute("SELECT heading FROM intermediate.sections").fetchone()["heading"] == "Previous stored value"
    monkeypatch.setattr(module, "reconcile", original)
    build(raw_collection, staged)
    with connect() as connection:
        for name in ("bills", "bill_versions", "sections"):
            assert connection.execute(sql.SQL("SELECT count(*) AS n FROM intermediate.{}").format(sql.Identifier(name))).fetchone()["n"] == 0
    assert model(raw_collection, staged)["records"] == 1
