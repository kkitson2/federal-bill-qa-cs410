"""Small JSON HTTP API so an app in any language can call search. Standard library only.

    uv run --no-editable python -m search serve            # http://127.0.0.1:8410

    GET  /health                                   -> {"status": "ok", "sections": 408, "methods": [...]}
    GET  /search?q=<question>&k=5&method=hybrid    -> {"question", "method", "k", "results": [...]}
    POST /search  {"question": "...", "k": 5, "method": "hybrid"}   (same response)

Errors return {"error": "..."} with status 400 (bad input), 404 (unknown path) or 500.
Binds to 127.0.0.1 by default: it is a local development service with no authentication.
"""

from __future__ import annotations

import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .engine import DEFAULT_METHOD, METHODS, Searcher

DEFAULT_PORT = 8410
MAX_BODY = 64 * 1024
log = logging.getLogger("search.server")


class BadRequest(ValueError):
    pass


def make_handler(searcher: Searcher):
    class Handler(BaseHTTPRequestHandler):
        server_version = "BillSearch/1.0"

        def _send(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _search(self, params: dict) -> None:
            question = params.get("question", params.get("q"))
            k = params.get("k", 5)
            method = params.get("method", DEFAULT_METHOD)
            try:
                k = int(k)
            except (TypeError, ValueError):
                raise BadRequest("k must be an integer") from None
            if not isinstance(question, str):
                raise BadRequest("question is required (JSON field 'question' or query parameter 'q')")
            results = searcher.search(question, k=k, method=method)
            self._send(HTTPStatus.OK, {"question": question, "method": method, "k": k,
                                       "results": [r.to_dict() for r in results]})

        def _handle(self, params_from_request) -> None:
            path = urlparse(self.path).path.rstrip("/") or "/"
            try:
                if path == "/health" and self.command == "GET":
                    self._send(HTTPStatus.OK, {"status": "ok", "sections": len(searcher.sections),
                                               "methods": list(METHODS), "default_method": DEFAULT_METHOD})
                elif path == "/search":
                    self._search(params_from_request())
                else:
                    self._send(HTTPStatus.NOT_FOUND, {"error": f"No route {self.command} {path}"})
            except (BadRequest, ValueError) as error:
                self._send(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            except Exception:  # keep the server up; details go to the server log only
                log.exception("search failed")
                self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal error, see server log"})

        def do_GET(self) -> None:  # noqa: N802
            self._handle(lambda: {key: values[-1] for key, values in parse_qs(urlparse(self.path).query).items()})

        def do_POST(self) -> None:  # noqa: N802
            def body() -> dict:
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    raise BadRequest("request body too large")
                try:
                    data = json.loads(self.rfile.read(length) or b"{}")
                except json.JSONDecodeError:
                    raise BadRequest("body must be JSON") from None
                if not isinstance(data, dict):
                    raise BadRequest("body must be a JSON object")
                return data
            self._handle(body)

        def log_message(self, fmt: str, *args) -> None:
            log.info("%s - %s", self.address_string(), fmt % args)

    return Handler


def make_server(searcher: Searcher, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(searcher))
