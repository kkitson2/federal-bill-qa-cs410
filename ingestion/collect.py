import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlsplit

from billbridge_data.files import digest, json_bytes, write_json
from ingestion.client import ArchiveClient, clean_url


def collect_bill(client, bill):
    congress, kind, number = bill["congress"], bill["bill_type"], bill["number"]
    bill_id = f"{congress}-{kind}-{number}"
    base = f"https://api.congress.gov/v3/bill/{congress}/{kind}/{number}"
    detail = client.json(base + "?format=json", f"congress/bill_details/{bill_id}.json")["bill"]
    if (int(detail["congress"]), detail["type"].lower(), int(detail["number"])) != (congress, kind, number):
        raise ValueError(f"Bill identity mismatch: {bill_id}")
    pages, items = set(), []
    next_url = base + "/text?format=json&limit=250"
    while next_url:
        next_url = clean_url(next_url)
        if next_url in pages:
            raise ValueError("Text-version pagination loop")
        page = client.json(next_url, f"congress/text_versions/{bill_id}/page-{len(pages):03}.json")
        pages.add(next_url)
        items.extend(page.get("textVersions", []))
        next_url = page.get("pagination", {}).get("next")
    bill_record = {**bill, "bill_id": bill_id, "current_title": detail["title"],
                   "listed_versions": len(items), "latest_action": detail.get("latestAction", {})}
    seen_packages, versions, exclusions = set(), [], []
    for item in items:
        xml_formats = [f for f in item.get("formats", []) if f["type"] == "Formatted XML"]
        if not xml_formats:
            available = {f["type"] for f in item.get("formats", [])}
            reason = ("Public-law USLM XML is outside the bill-version parser; source links retained"
                      if "United States Legislative Markup" in available
                      else "No Formatted XML bill version listed; available source links retained")
            exclusions.append({"bill_id": bill_id, "version_label": item["type"], "date": item.get("date"),
                               "reason": reason, "formats": item.get("formats", [])})
            continue
        if len(xml_formats) != 1:
            raise ValueError(f"Ambiguous XML listing: {bill_id}")
        listed_url = clean_url(xml_formats[0]["url"])
        package = Path(urlsplit(listed_url).path).stem
        match = re.fullmatch(rf"BILLS-{congress}{kind}{number}([a-z]+)", package)
        if not match or package in seen_packages:
            raise ValueError(f"Unexpected or repeated package: {package}")
        seen_packages.add(package)
        version = match.group(1)
        summary_url = f"https://api.govinfo.gov/packages/{package}/summary"
        summary = client.json(summary_url, f"govinfo/package_summaries/{package}.json")
        actual = (summary["packageId"], int(summary["congress"]), summary["billType"].lower(), int(summary["billNumber"]), summary["billVersion"])
        if actual != (package, congress, kind, number, version):
            raise ValueError(f"Source identity disagreement: {package}")
        xml_url = summary.get("download", {}).get("xmlLink")
        if not xml_url:
            raise ValueError(f"GovInfo has no XML link for listed package: {package}")
        source_name = f"govinfo/bill_xml/{package}.xml"
        client.get(xml_url, source_name)
        versions.append({
            "congress": congress, "bill_type": kind, "number": number, "version": version,
            "package_id": package, "bill_id": bill_id, "version_label": item["type"],
            "version_date": item.get("date"), "publication_date": summary.get("dateIssued"),
            "title": summary["title"], "short_titles": summary.get("shortTitle", []),
            "bill_latest_action": detail.get("latestAction", {}).get("text", ""),
            "source_url": summary["detailsLink"], "source_xml_url": listed_url,
            "raw_name": source_name, "raw_sha256": client.records[source_name]["sha256"],
        })
    print(f"Collected {bill_id}: {len(seen_packages)} XML versions", flush=True)
    return bill_record, versions, exclusions


def collect(config: Path, root: Path):
    selection = json.loads(config.read_text())
    bills = selection["bills"]
    identities = [(b["congress"], b["bill_type"], b["number"]) for b in bills]
    if len(set(identities)) != len(bills) or not bills:
        raise ValueError("Select distinct bills in a nonempty collection")
    for congress, kind, number in identities:
        if not isinstance(congress, int) or not isinstance(number, int) or kind not in {"hr", "s"}:
            raise ValueError("Invalid bill identity")
    selection_hash = digest(json_bytes(selection))
    selection_path = root / "selection.json"
    write_json(selection_path, selection)
    client = ArchiveClient(root)
    completed, failures = {}, []
    # Independent bills can progress while a different request is slow. The
    # shared client still spaces ALL request starts by its global interval.
    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(collect_bill, client, bill): i for i, bill in enumerate(bills)}
            for future in as_completed(futures):
                i = futures[future]
                try:
                    completed[i] = future.result()
                except Exception as error:
                    message = str(error) if isinstance(error, RuntimeError) else type(error).__name__
                    failures.append({"bill": bills[i], "error": message})
                    print(f"Incomplete {identities[i]}: {message}", flush=True)
        if failures:
            write_json(root / "failure.json", {"failures": failures, "completed_bills": len(completed)})
            raise RuntimeError(f"{len(failures)} bills incomplete; rerun to resume saved progress")
        bill_records, versions, exclusions = [], [], []
        for i in range(len(bills)):
            bill, bill_versions, excluded = completed[i]
            bill_records.append(bill)
            versions.extend(bill_versions)
            exclusions.extend(excluded)
        manifest = {"schema_version": 1, "selection_sha256": selection_hash, "bills": bill_records,
                    "versions": versions, "exclusions": exclusions, "resources": client.records}
        manifest["raw_layout"] = "api-endpoint-v1"
        write_json(root / "manifest.json", manifest)
        (root / "failure.json").unlink(missing_ok=True)
        return {"bills": len(bill_records), "versions": len(versions), "downloads": client.downloads,
                "cache_hits": client.cache_hits, "exclusions": len(exclusions)}
    finally:
        client.client.close()
