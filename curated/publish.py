"""Publish SQL model results as an current, database-independent collection."""

import json
from collections import Counter, defaultdict
from pathlib import Path

from billbridge_data.contracts import Section
from billbridge_data.database import connect, jsonl
from billbridge_data.files import atomic_write, digest, json_bytes, safe_relative, write_json
from intermediate.model import checked_context, reconcile

IDENTITY_FIELDS = ("schema_version", "parser_version", "model_version", "files")
COLLECTION_FILES = {"bills.jsonl", "versions.jsonl", "sections.jsonl", "catalog.jsonl", "validation.json"}


def publish(raw: Path, staged: Path, out: Path):
    with connect() as connection:
        source, stage = checked_context(connection, raw, staged)
        bills, version_rows, sections, exclusions = reconcile(connection, raw)
        groups, duplicates = defaultdict(list), defaultdict(list)
        for section in sections:
            groups[section.package_id].append(section)
        versions = []
        for row in version_rows:
            records = groups[row["package_id"]]
            text_hash = digest("\n".join(s.text for s in records).encode())
            versions.append({
                "bill_id": row["bill_id"], "package_id": row["package_id"], "congress": row["congress"],
                "bill_type": row["bill_type"], "number": row["bill_number"], "version": row["version"],
                "title": row["title"], "version_label": row["version_label"], "version_date": row["version_date_source"],
                "publication_date": row["publication_date"].isoformat() if row["publication_date"] else None,
                "short_titles": row["short_titles"], "bill_latest_action": row["bill_latest_action"],
                "source_url": row["source_url"], "source_xml_url": row["source_xml_url"],
                "raw_name": f"govinfo/bill_xml/{row['package_id']}.xml", "raw_sha256": records[0].source_hash,
                "text_sha256": text_hash, "record_count": len(records),
                "section_count": sum(s.record_type == "section" for s in records),
                "document_type": records[0].document_type, "characters": sum(len(s.text) for s in records),
            })
            duplicates[text_hash].append(row["package_id"])
        catalog = [{"section_id": s.section_id, "package_id": s.package_id, "title": s.title,
                    "version_label": s.version_label, "record_type": s.record_type, "heading": s.heading,
                    "citation": s.citation, "source_url": s.source_url,
                    "editorial_changes": sorted({a.value for a in s.annotations if a.kind == "editorial_change"})}
                   for s in sections]
        report = {
            "bills": len(bills), "xml_versions": len(versions), "records": len(sections),
            "sections": sum(s.record_type == "section" for s in sections),
            "document_context_records": sum(s.record_type == "document_context" for s in sections),
            "canonical_characters": sum(len(s.text) for s in sections),
            "sections_without_headings": sum(not s.heading for s in sections if s.record_type == "section"),
            "editorial_annotations": sum(a.kind == "editorial_change" for s in sections for a in s.annotations),
            "tables": sum(a.kind == "table" for s in sections for a in s.annotations),
            "document_types": dict(Counter(v["document_type"] for v in versions)),
            "identical_text_version_groups": [p for p in duplicates.values() if len(p) > 1],
            "excluded_text_listings": exclusions, "raw_resources": len(source["resources"]),
            "raw_uncompressed_bytes": sum(r["bytes"] for r in source["resources"].values()),
            "verified_nonwhitespace_characters": sum(d["verified_nonwhitespace_characters"] for d in stage["documents"]),
            "quality_scope": "Structural, source-text and relational validation; not an exhaustive legal or retrieval-quality review.",
        }
        payloads = {"bills.jsonl": jsonl(bills),
                    "versions.jsonl": jsonl(versions), "sections.jsonl": jsonl(s.model_dump() for s in sections),
                    "catalog.jsonl": jsonl(catalog), "validation.json": json_bytes(report)}
        identity = {"schema_version": 4, **{k: stage[k] for k in IDENTITY_FIELDS if k in stage},
                    "files": {name: digest(payload) for name, payload in payloads.items()}}
        manifest = {**identity, "snapshot_id": digest(json_bytes(identity)), "record_count": len(sections),
                    "section_count": report["sections"], "context_count": report["document_context_records"],
                    "bill_count": len(bills), "version_count": len(versions)}

        for name, payload in payloads.items():
            atomic_write(out / name, payload)
        write_json(out / "manifest.json", manifest)
    load_collection(out)
    return {"snapshot_id": manifest["snapshot_id"], **report}


def load_collection(root: Path):
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest["schema_version"] != 4 or set(manifest["files"]) != COLLECTION_FILES:
        raise ValueError("Unrecognized curated collection contract")
    for name, checksum in manifest["files"].items():
        if digest(safe_relative(root, name).read_bytes()) != checksum:
            raise ValueError(f"Collection checksum mismatch: {name}")
    if digest(json_bytes({k: manifest[k] for k in IDENTITY_FIELDS})) != manifest["snapshot_id"]:
        raise ValueError("Snapshot identity mismatch")
    records = [Section.model_validate_json(line) for line in (root / "sections.jsonl").read_bytes().splitlines()]
    versions = [json.loads(line) for line in (root / "versions.jsonl").read_bytes().splitlines()]
    bills = [json.loads(line) for line in (root / "bills.jsonl").read_bytes().splitlines()]
    if len(records) != manifest["record_count"] or len({r.section_id for r in records}) != len(records):
        raise ValueError("Record count or identity mismatch")
    if (sum(r.record_type == "section" for r in records) != manifest["section_count"] or
        sum(r.record_type == "document_context" for r in records) != manifest["context_count"]):
        raise ValueError("Record type counts disagree")
    if len(versions) != manifest["version_count"] or len({v["package_id"] for v in versions}) != len(versions):
        raise ValueError("Version count or identity mismatch")
    if (len(bills) != manifest["bill_count"] or len({b["bill_id"] for b in bills}) != len(bills) or
        {v["bill_id"] for v in versions} != {b["bill_id"] for b in bills}):
        raise ValueError("Bill/version relationship mismatch")
    if Counter(r.package_id for r in records) != {v["package_id"]: v["record_count"] for v in versions}:
        raise ValueError("Section/version coverage mismatch")
    return manifest, records
