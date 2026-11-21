"""A small HTTP layer for the API: routes, JSON, and CORS for the phone's page.

The page is served from another origin (Cloudflare Pages, over HTTPS) and calls this
plain-HTTP server on the LAN, which Chrome allows once the user grants the local network
permission. Every POST sends JSON or ``application/octet-stream``, so a browser always
sends a CORS preflight first, and only origins in ``server.origins`` get through:

* no ``Origin`` header (curl, scripts): allowed
* the server's own origin (a page it serves itself): allowed
* an origin in the list, or ``*`` in the list: allowed, with CORS headers
* anything else: 403, and preflights get no CORS headers, so the browser refuses

Standard library only: one phone, a request every few hundred milliseconds, and the
engine and scans run on threads of their own anyway.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

log = logging.getLogger(__name__)

MAX_BODY = 16 * 2**20  # bytes; a batch of 720p frames is well under 1 MB
METHODS = "GET, POST, PUT, DELETE, OPTIONS"


class HttpError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, list[str]]
    headers: Any  # http.client.HTTPMessage
    body: bytes = b""

    @property
    def content_type(self) -> str:
        return (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()

    def json(self) -> dict[str, Any]:
        """The body as a JSON object ({} if empty). Raises :class:`HttpError`."""
        if not self.body:
            return {}
        if self.content_type != "application/json":
            raise HttpError(415, "send JSON with Content-Type: application/json")
        try:
            data = json.loads(self.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise HttpError(400, f"invalid JSON: {e}") from None
        if not isinstance(data, dict):
            raise HttpError(400, "the body must be a JSON object")
        return data


# A handler returns a JSON-able dict (200), or (status, dict).
Handler = Callable[[Request], "dict[str, Any] | tuple[int, dict[str, Any]]"]


@dataclass
class Router:
    routes: dict[tuple[str, str], Handler] = field(default_factory=dict)

    def add(self, method: str, path: str, handler: Handler) -> None:
        self.routes[(method, path)] = handler

    def find(self, method: str, path: str) -> Handler:
        handler = self.routes.get((method, path))
        if handler is None:
            if any(p == path for _, p in self.routes):
                raise HttpError(405, f"{method} isn't supported on {path}")
            raise HttpError(404, f"no such endpoint: {path}")
        return handler


def origin_allowed(origin: str | None, host: str | None, origins: list[str]) -> bool:
    if not origin:
        return True
    if "*" in origins or origin in origins:
        return True
    # the server's own pages (it may serve the page itself): same scheme-less host:port
    return host is not None and origin.split("://", 1)[-1] == host


def make_handler(router: Router, origins: list[str]) -> type[BaseHTTPRequestHandler]:
    class ApiHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"  # keep-alive: the page sends a batch every 250 ms
        server_version = "treemap"

        def log_message(self, fmt: str, *args: Any) -> None:
            log.debug("%s %s", self.address_string(), fmt % args)

        def _origin_ok(self) -> bool:
            return origin_allowed(self.headers.get("Origin"), self.headers.get("Host"), origins)

        def _cors(self) -> None:
            origin = self.headers.get("Origin")
            if origin and self._origin_ok():
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:  # CORS preflight
            if not self._origin_ok():
                self.send_response(403)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(204)
            self._cors()
            self.send_header("Access-Control-Allow-Methods", METHODS)
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "600")
            # Chrome's older Private Network Access preflight asks for this; harmless now.
            if self.headers.get("Access-Control-Request-Private-Network"):
                self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _handle(self) -> None:
            url = urlsplit(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            try:
                if length > MAX_BODY:
                    self.close_connection = True  # the body isn't read
                    raise HttpError(413, f"the body is over {MAX_BODY} bytes")
                body = self.rfile.read(length) if length else b""
                if not self._origin_ok():
                    raise HttpError(403, f"origin {self.headers.get('Origin')} isn't allowed; "
                                         "add it to server.origins in the config")
                handler = router.find(self.command, url.path)
                req = Request(self.command, url.path, parse_qs(url.query), self.headers, body)
                result = handler(req)
                status, payload = result if isinstance(result, tuple) else (200, result)
            except HttpError as e:
                status, payload = e.status, {"error": e.message}
            except Exception as e:  # noqa: BLE001 - the page gets a message, the log the trace
                log.exception("%s %s failed", self.command, url.path)
                status, payload = 500, {"error": f"{type(e).__name__}: {e}"}
            self._send(status, payload)

        do_GET = do_POST = do_PUT = do_DELETE = _handle

    return ApiHandler


class HttpServer:
    """Serves ``router`` on ``host:port`` from a background thread."""

    def __init__(self, router: Router, host: str, port: int, origins: list[str]) -> None:
        self._httpd = ThreadingHTTPServer((host, port), make_handler(router, origins))
        self._httpd.daemon_threads = True
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    def start(self) -> HttpServer:
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="http",
                                        daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
