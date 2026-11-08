"""Deterministic serialization and atomic individual-file writes."""

import hashlib
import json
import os
import tempfile
from pathlib import Path


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def atomic_write(path: Path, payload: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".writing-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def write_json(path: Path, value):
    atomic_write(path, json_bytes(value))


def safe_relative(root: Path, value: str) -> Path:
    path = root / value
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Artifact path escapes the collection directory")
    return path
