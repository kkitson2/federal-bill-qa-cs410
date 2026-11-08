import gzip
import json
import os
import time
import threading
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from billbridge_data.files import atomic_write, digest, write_json


ALLOWED_HOSTS = {"api.congress.gov", "api.govinfo.gov", "www.govinfo.gov", "www.congress.gov"}


def clean_url(url):
    parts = urlsplit(url)
    query = [(key, value) for key, value in parse_qsl(parts.query) if key.lower() != "api_key"]
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS or parts.username:
        raise ValueError("Expected an HTTPS government source URL")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def retry_delay(value, attempt):
    if value:
        try:
            return max(0, float(value))
        except ValueError:
            try:
                return max(0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError):
                pass
    return min(60, 2 ** attempt)


class ArchiveClient:
    def __init__(self, root: Path, client=None, interval=0.8):
        self.root = root
        self.client = client or httpx.Client(timeout=45, follow_redirects=False)
        self.interval = interval
        self.previous_request = 0.0
        self.downloads = 0
        self.cache_hits = 0
        self.records = {}
        self.request_lock = threading.Lock()

    def get(self, url, name):
        url = clean_url(url)
        path = self.root / (name + ".gz")
        receipt_path = self.root / (name + ".receipt.json")
        if path.exists() and receipt_path.exists():
            receipt = json.loads(receipt_path.read_text())
            payload = gzip.decompress(path.read_bytes())
            if receipt["url"] != url or digest(payload) != receipt["sha256"]:
                raise ValueError(f"Cached source mismatch: {name}")
            self.records[name] = receipt
            self.cache_hits += 1
            return payload

        host = urlsplit(url).hostname
        service_key = "CONGRESS_API_KEY" if host == "api.congress.gov" else "GOVINFO_API_KEY"
        key = os.getenv(service_key) or os.getenv("API_DATA_GOV_KEY") or "DEMO_KEY"
        headers = {"X-Api-Key": key} if host == "api.govinfo.gov" else {}
        current = url
        for attempt in range(6):
            with self.request_lock:
                time.sleep(max(0, self.interval - (time.monotonic() - self.previous_request)))
                self.previous_request = time.monotonic()
            try:
                request_url = httpx.URL(current)
                # Congress.gov query authentication succeeded on endpoints
                # where header authentication repeatedly timed out. Keep the
                # authenticated URL ephemeral; receipts use clean URLs only.
                if host == "api.congress.gov" and request_url.host == host:
                    request_url = request_url.copy_set_param("api_key", key)
                with self.client.stream("GET", request_url, headers=headers) as response:
                    if response.is_redirect:
                        current = clean_url(str(response.url.join(response.headers["location"])))
                        headers = headers if urlsplit(current).hostname == host else {}
                        continue
                    if response.status_code == 429 or 500 <= response.status_code < 600:
                        delay = retry_delay(response.headers.get("Retry-After"), attempt)
                        if delay > 60:
                            raise RuntimeError(f"Rate limited by {host}; retry after {delay:.0f}s. Saved responses can be resumed.")
                        time.sleep(delay)
                        continue
                    if response.status_code != 200:
                        raise RuntimeError(f"{host} returned HTTP {response.status_code} for {name}")
                    chunks = []
                    size = 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > 25_000_000:
                            raise ValueError(f"Source exceeds the 25 MB resource bound: {name}")
                        chunks.append(chunk)
                    payload = b"".join(chunks)
                    # Congress.gov can echo an authenticated request URL in its
                    # response. Retain the body with that credential redacted.
                    redacted = key != "DEMO_KEY" and key.encode() in payload
                    if redacted:
                        payload = payload.replace(key.encode(), b"[REDACTED_API_KEY]")
                    receipt = {
                        "url": url, "resolved_url": current, "path": path.relative_to(self.root).as_posix(),
                        "sha256": digest(payload), "bytes": len(payload),
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                        "credential_redacted": redacted, "content_type": response.headers.get("content-type"),
                        "rate_limit": response.headers.get("x-ratelimit-limit"),
                        "rate_remaining": response.headers.get("x-ratelimit-remaining"),
                    }
                    atomic_write(path, gzip.compress(payload, mtime=0))
                    write_json(receipt_path, receipt)
                    self.records[name] = receipt
                    self.downloads += 1
                    return payload
            except httpx.TransportError:
                if attempt == 5:
                    break
                time.sleep(min(10, 2 ** attempt))
        raise RuntimeError(f"Source request exhausted retries for {name}; cached progress is retained")

    def json(self, url, name):
        return json.loads(self.get(url, name))
