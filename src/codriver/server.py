"""HTTP plumbing: static files on one side, a small JSON API on the other.

Standard library only, threaded, one port. The browser polls `/api/state` and
posts to everything else. There is no websocket because there is nothing here
that a once-a-second poll of a few hundred bytes handles badly, and a poll
survives the panel being restarted under a browser tab that stays open.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from re import Pattern
from typing import Any

from .app import App

STATIC_DIR = Path(__file__).resolve().parent / "static"

_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json",
    ".ico": "image/x-icon",
}

Route = Callable[["PanelHandler", "re.Match[str]"], Any]

_GET_ROUTES: list[tuple[Pattern[str], Route]] = []
_POST_ROUTES: list[tuple[Pattern[str], Route]] = []


def _get(pattern: str) -> Callable[[Route], Route]:
    def register(fn: Route) -> Route:
        _GET_ROUTES.append((re.compile(pattern), fn))
        return fn

    return register


def _post(pattern: str) -> Callable[[Route], Route]:
    def register(fn: Route) -> Route:
        _POST_ROUTES.append((re.compile(pattern), fn))
        return fn

    return register


class PanelServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], app: App) -> None:
        super().__init__(address, PanelHandler)
        self.app = app


class PanelHandler(BaseHTTPRequestHandler):
    server_version = "codriver"
    protocol_version = "HTTP/1.1"

    @property
    def app(self) -> App:
        server = self.server
        assert isinstance(server, PanelServer)
        return server.app

    # --- routing ---

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        for pattern, handler in _GET_ROUTES:
            match = pattern.fullmatch(path)
            if match:
                self._dispatch(handler, match)
                return
        self._serve_static(path)

    def do_POST(self) -> None:
        path = self.path.split("?")[0]
        for pattern, handler in _POST_ROUTES:
            match = pattern.fullmatch(path)
            if match:
                self._dispatch(handler, match)
                return
        self._send_json({"error": "no such endpoint"}, status=404)

    def _dispatch(self, handler: Route, match: re.Match[str]) -> None:
        try:
            self._send_json(handler(self, match))
        except KeyError as exc:
            self._send_json({"error": f"unknown name {exc.args[0]!r}"}, status=404)
        except Exception as exc:
            self._send_json({"error": f"{type(exc).__name__}: {exc}"}, status=500)

    # --- endpoints ---

    @_get(r"/api/state")
    def _state(self, _match: re.Match[str]) -> Any:
        return self.app.state()

    @_get(r"/api/processes/([a-z0-9_-]+)/log")
    def _log(self, match: re.Match[str]) -> Any:
        return self.app.log(match.group(1))

    @_get(r"/api/document/([a-z0-9_-]+)")
    def _document(self, match: re.Match[str]) -> Any:
        return self.app.document(match.group(1))

    @_post(r"/api/sensors/refresh")
    def _refresh(self, _match: re.Match[str]) -> Any:
        return self.app.refresh_sensors()

    @_post(r"/api/recording/toggle/([a-z0-9_-]+)")
    def _toggle(self, match: re.Match[str]) -> Any:
        return self.app.toggle_recording_topic(match.group(1))

    @_post(r"/api/processes/([a-z0-9_-]+)/start")
    def _start(self, match: re.Match[str]) -> Any:
        return self.app.start_process(match.group(1))

    @_post(r"/api/processes/([a-z0-9_-]+)/stop")
    def _stop(self, match: re.Match[str]) -> Any:
        return self.app.stop_process(match.group(1))

    @_post(r"/api/commands/([a-z0-9_-]+)")
    def _command(self, match: re.Match[str]) -> Any:
        return self.app.run(match.group(1))

    # --- transport ---

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, path: str) -> None:
        relative = "index.html" if path == "/" else path.lstrip("/")
        target = (STATIC_DIR / relative).resolve()
        if not target.is_file() or STATIC_DIR not in target.parents:
            self.send_error(404, "not found")
            return
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", _MIME.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        # The panel is edited in place on the car; a cached shell would hide it.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        """Quiet by default. Every one-second poll would otherwise print a line
        and bury anything worth reading."""
        return
