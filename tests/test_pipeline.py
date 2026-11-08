import gzip
import json
from pathlib import Path

import httpx
import pytest

from billbridge_data.contracts import SourceSpec
from billbridge_data.files import digest, write_json
from ingestion.client import ArchiveClient
from ingestion.collect import collect
from staging.parser import parse_xml
from staging.fidelity import verify_text


SPEC = SourceSpec(congress=118, bill_type="hr", number=1, version="ih")
META = {"title": "Verified title", "version_label": "Introduced in House",
        "source_url": "https://www.govinfo.gov/app/details/BILLS-118hr1ih",
        "source_xml_url": "https://www.govinfo.gov/content/pkg/BILLS-118hr1ih/xml/BILLS-118hr1ih.xml"}


def test_marked_text_references_and_exact_offsets():
    xml = b'''<bill><legis-body><title changed="added"><header>Duties</header>
    <section><enum>1.</enum><text>The <term>reviewing court</term>, not <phrase changed="deleted">agency</phrase>,
    may<term> inspect</term> <external-xref legal-doc="usc">records</external-xref>.</text>
    <quoted-block><section><enum>99.</enum><text>Keep this quotation.</text></section></quoted-block>
    </section></title></legis-body></bill>'''
    records = parse_xml(xml, SPEC)
    section = next(r for r in records if r.record_type == "section")
    assert len([r for r in records if r.record_type == "section"]) == 1
    assert "reviewing court, not" in section.text
    assert "may inspect records." in section.text
    assert "[DELETED] agency [/DELETED]" in section.text
    assert section.text.startswith("[ADDED]")
    assert "Keep this quotation." in section.text
    assert {a.value for a in section.annotations if a.kind == "editorial_change"} == {"added", "deleted"}
    assert any(a.kind == "reference" and a.value == "usc" for a in section.annotations)
    assert "".join(b.text for b in section.blocks) == section.text
    assert verify_text(xml, records)["verified_records"] == len(records)


def test_amendment_instructions_and_title_change_are_preserved():
    xml = b'''<amendment-doc><engrossed-amendment-body><amendment-instruction>
    Strike all after the enacting clause and insert:</amendment-instruction>
    <section><enum>1.</enum><text>Replacement text.</text></section>
    </engrossed-amendment-body><title-amends>Amend the title to read New Title.</title-amends></amendment-doc>'''
    records = parse_xml(xml, SPEC)
    assert records[0].document_type == "amendment-doc"
    assert "Strike all after" in records[0].amendment_context
    assert "Amend the title" in records[0].amendment_context
    assert {r.record_type for r in records} == {"section", "document_context"}
    verify_text(xml, records)


def test_table_boundaries_and_distinct_repeated_numbers():
    xml = b'''<bill><legis-body><division><enum>A</enum><section><enum>1.</enum>
    <table><tgroup><tbody><row><entry>Year</entry><entry>Amount</entry></row>
    <row><entry>2026</entry><entry>$100</entry></row></tbody></tgroup></table></section></division>
    <division><enum>B</enum><section><enum>1.</enum><text>Another section.</text></section></division>
    </legis-body></bill>'''
    records = [r for r in parse_xml(xml, SPEC) if r.record_type == "section"]
    assert "Year\tAmount\n2026\t$100" in records[0].text
    assert records[0].annotations[0].kind == "table"
    assert records[0].section_id != records[1].section_id
    assert records[0].hierarchy != records[1].hierarchy
    verify_text(xml, records)


def test_fidelity_check_catches_dropped_source_text():
    xml = b"<bill><legis-body><section><enum>1.</enum><text>Keep all words.</text></section></legis-body></bill>"
    records = parse_xml(xml, SPEC)
    records[0].text = records[0].text.replace("all ", "")
    with pytest.raises(ValueError, match="differs from source"):
        verify_text(xml, records)


@pytest.mark.parametrize("transient_status", [429, 520])
def test_archive_retries_redacts_and_uses_verified_cache(tmp_path, monkeypatch, transient_status):
    monkeypatch.setenv("API_DATA_GOV_KEY", "synthetic-personal-secret")
    monkeypatch.delenv("GOVINFO_API_KEY", raising=False)
    waits, requests = [], []
    monkeypatch.setattr("ingestion.client.time.sleep", waits.append)

    def respond(request):
        requests.append(request)
        assert "api_key" not in str(request.url)
        assert request.headers["X-Api-Key"] == "synthetic-personal-secret"
        if len(requests) == 1:
            return httpx.Response(transient_status, headers={"Retry-After": "2"})
        return httpx.Response(200, json={"echo": "synthetic-personal-secret"})

    archive = ArchiveClient(tmp_path, httpx.Client(transport=httpx.MockTransport(respond)), interval=0)
    url = "https://api.govinfo.gov/packages/BILLS-118hr1ih/summary?api_key=synthetic-personal-secret"
    first = archive.get(url, "summary.json")
    assert b"synthetic-personal-secret" not in first
    assert archive.get(url, "summary.json") == first
    assert len(requests) == 2 and 2 in waits and archive.cache_hits == 1
    (tmp_path / "summary.json.gz").write_bytes(gzip.compress(b"modified"))
    with pytest.raises(ValueError, match="mismatch"):
        archive.get(url, "summary.json")


def test_congress_query_auth_is_never_archived(tmp_path, monkeypatch):
    key = "synthetic-congress-secret"
    monkeypatch.setenv("API_DATA_GOV_KEY", key)
    monkeypatch.delenv("CONGRESS_API_KEY", raising=False)

    def respond(request):
        assert request.url.params["api_key"] == key
        assert request.url.params["format"] == "json"
        assert request.url.params["limit"] == "250"
        return httpx.Response(200, json={"request": {"url": str(request.url)}})

    archive = ArchiveClient(tmp_path, httpx.Client(transport=httpx.MockTransport(respond)), interval=0)
    archive.get("https://api.congress.gov/v3/bill/118/s/1/text?format=json&limit=250", "versions.json")
    assert key.encode() not in gzip.decompress((tmp_path / "versions.json.gz").read_bytes())
    assert key not in (tmp_path / "versions.json.receipt.json").read_text()
    assert archive.records["versions.json"]["credential_redacted"]


@pytest.fixture
def raw_collection(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    write_json(config, {"bills": [{"congress": 118, "bill_type": "hr", "number": 1}]})
    calls = []

    def respond(request):
        path = request.url.path
        calls.append(str(request.url))
        if path.endswith("/text"):
            offset = request.url.params.get("offset")
            if not offset:
                return httpx.Response(200, json={"textVersions": [{"type": "Introduced in House", "date": "2023-01-01",
                    "formats": [{"type": "Formatted XML", "url": META["source_xml_url"]}]}],
                    "pagination": {"next": "https://api.congress.gov/v3/bill/118/hr/1/text?offset=1&api_key=DEMO_KEY"}})
            return httpx.Response(200, json={"textVersions": [{"type": "Unavailable XML", "formats": []}]})
        if path == "/v3/bill/118/hr/1":
            return httpx.Response(200, json={"bill": {"congress": 118, "type": "HR", "number": "1", "title": "Test bill"}})
        if path.endswith("/summary"):
            return httpx.Response(200, json={"packageId": "BILLS-118hr1ih", "congress": "118", "billType": "hr",
                "billNumber": "1", "billVersion": "ih", "title": "Test bill", "detailsLink": META["source_url"],
                "download": {"xmlLink": "https://api.govinfo.gov/packages/BILLS-118hr1ih/xml"}})
        if path.endswith("/xml"):
            return httpx.Response(200, content=b"<bill><legis-body><section><enum>1.</enum><text>Example law.</text></section></legis-body></bill>")
        raise AssertionError(path)

    client = httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr("ingestion.collect.ArchiveClient", lambda root: ArchiveClient(root, client, interval=0))
    raw = tmp_path / "raw"
    first = collect(config, raw)
    assert first["downloads"] == 5 and first["versions"] == 1 and first["exclusions"] == 1
    second = collect(config, raw)
    assert second["downloads"] == 0 and second["cache_hits"] == 5 and len(calls) == 5
    return raw


def test_run_checks_database_before_ingestion(monkeypatch):
    from billbridge_data import cli
    monkeypatch.setattr("sys.argv", ["billbridge-data", "run"])
    def unavailable():
        raise RuntimeError("Database unavailable")
    monkeypatch.setattr(cli, "ensure_schema", unavailable)
    monkeypatch.setattr(cli, "collect", lambda *a, **k: pytest.fail("Ingestion started without database"))
    with pytest.raises(RuntimeError, match="Database unavailable"):
        cli.main()
