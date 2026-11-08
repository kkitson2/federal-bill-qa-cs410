"""Independently standardize archived Congress JSON, GovInfo JSON and XML."""

import gzip
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from billbridge_data.contracts import SourceSpec
from billbridge_data.files import safe_relative
from ingestion.client import clean_url
from staging.fidelity import verify_text
from staging.parser import parse_xml

PACKAGE = re.compile(r"BILLS-(\d+)(hr|s)(\d+)([a-z]+)")


def package_spec(package):
    match = PACKAGE.fullmatch(package)
    if not match:
        raise ValueError(f"Unrecognized bill package identity: {package}")
    congress, kind, number, version = match.groups()
    return SourceSpec(congress=int(congress), bill_type=kind, number=int(number), version=version)


def extract(raw, manifest):
    tables = {name: [] for name in ("congress_bills", "congress_text_versions", "govinfo_packages", "govinfo_sections")}
    documents = []
    for resource, receipt in sorted(manifest["resources"].items()):
        body = gzip.decompress(safe_relative(raw, receipt["path"]).read_bytes())
        provenance = {"source_resource": resource, "source_hash": receipt["sha256"]}
        try:
            parts = resource.split("/")
            if parts[0] == "congress":
                endpoint = parts[1]
                requested_bill = Path(parts[2]).stem
                congress, kind, number = requested_bill.split("-")
                identity = {"bill_id": requested_bill, "congress": int(congress), "bill_type": kind, "bill_number": int(number)}
                data = json.loads(body)
                if endpoint == "bill_details":
                    bill = data["bill"]
                    actual = f"{int(bill['congress'])}-{bill['type'].lower()}-{int(bill['number'])}"
                    if actual != requested_bill:
                        raise ValueError("Congress metadata disagrees with its requested source identity")
                    action = bill.get("latestAction", {})
                    tables["congress_bills"].append({**provenance, **identity, "current_title": bill["title"],
                        "introduced_date": bill.get("introducedDate"), "latest_action_date": action.get("actionDate"),
                        "latest_action_text": action.get("text", ""), "source_payload": bill})
                elif endpoint == "text_versions":
                    for ordinal, version in enumerate(data["textVersions"]):
                        formats = version.get("formats", [])
                        xml = [f for f in formats if f["type"] == "Formatted XML"]
                        if len(xml) > 1:
                            raise ValueError("Ambiguous XML formats in one source listing")
                        package = spec = url = reason = None
                        if xml:
                            url = clean_url(xml[0]["url"])
                            package = Path(urlsplit(url).path).stem
                            spec = package_spec(package)
                        else:
                            reason = ("Public-law USLM XML is outside the bill-version parser; source links retained"
                                      if any(f["type"] == "United States Legislative Markup" for f in formats)
                                      else "No Formatted XML bill version listed; available source links retained")
                        tables["congress_text_versions"].append({**provenance, **identity,
                            "source_ordinal": ordinal, "package_id": package, "version": spec.version if spec else None,
                            "version_label": version["type"], "version_date": version.get("date"),
                            "version_date_source": version.get("date"), "source_xml_url": url,
                            "formats": formats, "exclusion_reason": reason, "source_payload": version})
                else:
                    raise ValueError("Unrecognized Congress resource")
            elif parts[0] == "govinfo":
                endpoint, package = parts[1], Path(parts[2]).stem
                if endpoint == "package_summaries":
                    summary = json.loads(body)
                    tables["govinfo_packages"].append({**provenance, "package_id": summary["packageId"],
                        "congress": int(summary["congress"]), "bill_type": summary["billType"].lower(),
                        "bill_number": int(summary["billNumber"]), "version": summary["billVersion"],
                        "version_title": summary["title"], "publication_date": summary.get("dateIssued"),
                        "short_titles": summary.get("shortTitle", []), "source_url": summary["detailsLink"],
                        "download_url": clean_url(summary["download"]["xmlLink"]), "source_payload": summary})
                elif endpoint == "bill_xml":
                    records = parse_xml(body, package_spec(package))
                    fidelity = verify_text(body, records)
                    documents.append({"package_id": package, **fidelity})
                    for ordinal, record in enumerate(records):
                        tables["govinfo_sections"].append({**record.model_dump(),
                            "source_resource": resource, "record_ordinal": ordinal})
                else:
                    raise ValueError("Unrecognized GovInfo resource")
            else:
                raise ValueError("Unrecognized archived source")
        except Exception as error:
            raise ValueError(f"Unable to stage {resource}: {type(error).__name__}: {error}") from error
    return tables, documents
