"""Integrity checks for frozen raw response archives."""

import gzip
import json
from pathlib import Path

from billbridge_data.files import digest, json_bytes, safe_relative


def validate_raw(root: Path):
    manifest = json.loads((root / "manifest.json").read_text())
    selection = json.loads((root / "selection.json").read_text())
    if digest(json_bytes(selection)) != manifest["selection_sha256"]:
        raise ValueError("Raw selection checksum mismatch")
    for name, resource in manifest["resources"].items():
        payload = gzip.decompress(safe_relative(root, resource["path"]).read_bytes())
        if digest(payload) != resource["sha256"] or len(payload) != resource["bytes"]:
            raise ValueError(f"Raw checksum mismatch: {name}")
        receipt = json.loads(safe_relative(root, name + ".receipt.json").read_text())
        if receipt != resource:
            raise ValueError(f"Raw receipt mismatch: {name}")
    return manifest
