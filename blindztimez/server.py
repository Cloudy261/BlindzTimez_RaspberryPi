"""Optional LAN HTTP endpoint for Apple Shortcuts / home automation.

A tiny stdlib-only server (no extra dependencies, minimal attack surface). It
requires a shared secret token on every request and exposes only open/close and
per-remote commands -- no pairing, no shell, no arbitrary input. It runs as its
own service, so the network-facing part is isolated from the scheduler; both go
through `controller`, which takes the file lock, so transmits never overlap.

Endpoints (GET or POST; token required on all):
    /status                     -> JSON status
    /open                       -> UP to ALL remotes (ignores the daily flag)
    /close                      -> DOWN to ALL remotes (ignores the daily flag)
    /remote/<name>/<up|down|my|prog>  -> one button to one remote (selective)
"""

from __future__ import annotations

import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

from blindztimez import config, controller, store

_MAX_BODY = 4096  # cap request bodies; we don't need any, just drain politely


class _Server(ThreadingHTTPServer):
    """Threading HTTP server that carries the auth token for its handlers."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], token: str) -> None:
        super().__init__(address, _Handler)
        self.token = token


class _Handler(BaseHTTPRequestHandler):
    """Handle one request: authenticate, route to a controller action, reply JSON."""

    server_version = "blindztimez/1.0"

    def _authed(self) -> bool:
        """Constant-time check of the Bearer / X-Blindz-Token against the server token."""
        token: str = self.server.token  # type: ignore[attr-defined]
        given = self.headers.get("Authorization", "")
        given = given[7:] if given.startswith("Bearer ") else self.headers.get("X-Blindz-Token", "")
        return bool(token) and hmac.compare_digest(given, token)

    def _reply(self, code: int, payload: dict) -> None:
        """Send a small JSON response."""
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _drain(self) -> None:
        """Read and discard any request body (bounded), so keep-alive stays clean."""
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > 0:
            self.rfile.read(min(length, _MAX_BODY))

    def _handle(self) -> None:
        """Authenticate and dispatch one request (GET and POST share this)."""
        self._drain()
        if not self._authed():
            self._reply(401, {"error": "unauthorized"})
            return
        path = unquote(self.path.split("?", 1)[0]).rstrip("/")
        try:
            if path in ("", "/status"):
                st = store.load()
                self._reply(200, {
                    "enabled": st.runtime.enabled,
                    "remotes": [r.name for r in st.remotes],
                    "last_action": st.runtime.last_action,
                    "fail_count": st.runtime.fail_count,
                })
            elif path == "/open":
                # The endpoint controls ALL blinds, regardless of the daily flag.
                sent = controller.open_all(daily_only=False)
                self._reply(200, {"action": "open", "sent": sent})
            elif path == "/close":
                sent = controller.close_all(daily_only=False)
                self._reply(200, {"action": "close", "sent": sent})
            elif path.startswith("/remote/"):
                self._remote(path)
            else:
                self._reply(404, {"error": "not found"})
        except controller.ControllerError as exc:
            self._reply(400, {"error": str(exc)})
        except Exception:  # noqa: BLE001 - never leak a stack trace to the client
            config.get_logger().exception("http handler error")
            self._reply(500, {"error": "internal error"})

    def _remote(self, path: str) -> None:
        """Handle /remote/<name>/<button>."""
        parts = path.strip("/").split("/")
        if len(parts) != 3:
            self._reply(404, {"error": "not found"})
            return
        name, button = parts[1], parts[2].lower()
        if button not in config.BUTTON_CODES:
            self._reply(400, {"error": "button must be up|down|my|prog"})
            return
        ok = controller.send_button(name, config.BUTTON_CODES[button])
        self._reply(200 if ok else 502, {"remote": name, "button": button, "ok": ok})

    # GET and POST are both accepted so a Shortcut can use the simplest form.
    do_GET = _handle
    do_POST = _handle

    def log_message(self, fmt: str, *args) -> None:
        """Send access logs to the rotating file logger instead of stderr."""
        config.get_logger().info("http %s %s", self.address_string(), fmt % args)


def serve(bind: str, port: int, token: str) -> None:
    """Run the HTTP endpoint forever. Refuses to start without a token (fail closed)."""
    if not token:
        raise ValueError("no HTTP token set -- run: blindz token --generate")
    config.get_logger().info("HTTP endpoint listening on %s:%d", bind, port)
    with _Server((bind, port), token) as httpd:
        httpd.serve_forever()
