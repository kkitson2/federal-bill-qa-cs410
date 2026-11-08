import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from ingestion.collect import collect
from curated.publish import load_collection, publish
from intermediate.model import model
from staging.build import build
from .handoff import export_database
from .database import ensure_schema


def main():
    load_dotenv(Path.cwd() / ".env", override=False)
    parser = argparse.ArgumentParser(description="Prepare and load the bill collection")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("run", "ingest", "stage", "model", "publish", "export"):
        subparser = commands.add_parser(command)
        subparser.add_argument("--config", type=Path, default=Path("config/first20.json"))
        subparser.add_argument("--data", type=Path, default=Path("data"))
    for command in ("validate", "catalog"):
        subparser = commands.add_parser(command)
        subparser.add_argument("--corpus", type=Path, default=Path("data/curated"))
    args = parser.parse_args()

    if args.command in {"run", "ingest", "stage", "model", "publish", "export"}:
        raw = args.data / "raw"
        staged = args.data / "staging"
        curated = args.data / "curated"
        result = {}
        if args.command == "run":
            ensure_schema()  # Fail before fetching data if the required database is unavailable.
        if args.command in {"run", "ingest"}:
            result["ingestion"] = collect(args.config, raw)
        if args.command in {"run", "stage"}:
            result["staging"] = build(raw, staged)
        if args.command in {"run", "model"}:
            result["model"] = model(raw, staged)
        if args.command in {"run", "publish"}:
            result["publication"] = publish(raw, staged, curated)
        if args.command in {"run", "export"}:
            result["handoff"] = export_database(args.data, Path("database"))
    else:
        manifest, sections = load_collection(args.corpus)
        if args.command == "catalog":
            for section in sections:
                print(json.dumps({
                    "section_id": section.section_id,
                    "package_id": section.package_id,
                    "citation": section.citation,
                    "heading": section.heading,
                    "source_url": section.source_url,
                    "record_type": section.record_type,
                }, ensure_ascii=False))
            return
        result = {
            "snapshot_id": manifest["snapshot_id"],
            "bills": len({(s.congress, s.bill_type, s.bill_number) for s in sections}),
            "versions": len({s.package_id for s in sections}),
            "records": len(sections),
            "sections": sum(s.record_type == "section" for s in sections),
            "document_context_records": sum(s.record_type == "document_context" for s in sections),
            "sections_without_headings": sum(not s.heading for s in sections if s.record_type == "section"),
            "canonical_characters": sum(len(section.text) for section in sections),
        }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
