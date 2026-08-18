"""A read only HTTP surface, bound to loopback.

The service answers the same questions the CLI answers, from
the same library, so the two cannot drift. It never accepts a
prompt, never proxies a provider, and never writes through a
request. Every observation it serves has passed the redaction
boundary.

The screenshot route is the exception and is not observation
data. It returns the image bytes as captured, which is why
capture is off by default and why this surface is loopback
only.

Startup refuses any non loopback address. This surface has no
authentication, and a tool with no authentication that binds
a routable address is a tool that publishes your account
usage to the network it is on.
"""

from __future__ import annotations

import ipaddress
import json
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import config, contract, derive, redaction, report, store
from .providers import registry

SCHEMA = "trycopilotai/agent-usage/api/v1"
DEFAULT_PORT = 8787
SCREENSHOT_PREFIX = "/api/v1/screenshots/"


class NonLoopbackBind(ValueError):
    """A refused attempt to bind a routable address."""


def assert_loopback(host: str) -> str:
    """Refuse anything a machine other than this one can reach."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if host in ("localhost",):
            return host
        raise NonLoopbackBind("refusing to bind a non loopback host: " + str(host))
    if not address.is_loopback:
        raise NonLoopbackBind("refusing to bind a non loopback host: " + str(host))
    return host


def snapshot_document(connection: sqlite3.Connection, now: float | None = None) -> dict[str, Any]:
    """The latest stored read for every known provider."""
    moment = time.time() if now is None else now
    providers: list[dict[str, Any]] = []
    for name in registry.PROVIDERS:
        document = store.latest(connection, name)
        if document is None:
            providers.append(
                {
                    "provider": name,
                    "answered": False,
                    "error": contract.ERROR_NO_READING,
                }
            )
            continue
        document = redaction.filter_observation(document)
        document["freshness"] = store.freshness_of(document, now=moment)
        providers.append(document)
    answered = sum(1 for item in providers if item.get("answered"))
    return {
        "schema": SCHEMA,
        "generated_at": round(moment, 3),
        "providers": providers,
        "answered": answered,
        "requested": len(providers),
    }


def forecast_document(connection: sqlite3.Connection, provider: str) -> dict[str, Any]:
    document = store.latest(connection, provider)
    if document is None:
        return {"provider": provider, "status": contract.ERROR_NO_READING}
    if not document.get("answered"):
        # Say why there is nothing to forecast. "No binding
        # window" would describe a provider that answered
        # without one, which is not what happened.
        stored = document.get("error")
        return {
            "provider": provider,
            "status": stored if stored in contract.ERROR_CODES else contract.ERROR_NO_READING,
        }
    windows = tuple(
        contract.Window(
            label=entry.get("label", ""),
            used_percent=float(entry.get("used_percent", 0.0)),
            resets_in_seconds=entry.get("resets_in_seconds"),
        )
        for entry in document.get("windows", [])
        if isinstance(entry, dict) and entry.get("label")
    )
    observation = contract.Observation(
        provider=provider,
        collected_at=float(document.get("collected_at", 0.0)),
        windows=windows,
    )
    return {
        "provider": provider,
        **derive.forecast(observation, store.samples(connection, provider)),
    }


def _stored_failure(name: str, document: dict[str, Any] | None) -> contract.Observation:
    """Rebuild an unanswered reading, keeping its own code."""
    code = None
    if isinstance(document, dict):
        candidate = document.get("error")
        if candidate in contract.ERROR_CODES:
            code = candidate
    collected = float(document.get("collected_at", 0.0)) if isinstance(document, dict) else 0.0
    return contract.failed(name, code or contract.ERROR_NO_READING, now=collected or time.time())


class Handler(BaseHTTPRequestHandler):
    server_version = "agent-usage"
    sys_version = ""

    @property
    def connection_factory(self) -> Any:
        return self.server.connection_factory  # type: ignore[attr-defined]

    @property
    def state_kwargs(self) -> dict[str, Any]:
        return self.server.state_kwargs  # type: ignore[attr-defined]

    def log_message(self, *args: Any) -> None:
        """Stay silent. A request log is a usage log."""
        return

    def _send(self, status: int, payload: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, status: int, document: dict[str, Any]) -> None:
        body = (json.dumps(document, sort_keys=True, indent=2) + "\n").encode("utf-8")
        self._send(status, body, "application/json")

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            self._json(200, {"status": "ok", "schema": SCHEMA})
            return
        if path.startswith(SCREENSHOT_PREFIX):
            self._screenshot(path[len(SCREENSHOT_PREFIX) :])
            return
        connection = self.connection_factory()
        try:
            if path == "/api/v1/snapshot":
                self._json(200, snapshot_document(connection))
                return
            if path == "/api/v1/report.md":
                self._report(connection)
                return
            if path.startswith("/api/v1/forecast/"):
                provider = path[len("/api/v1/forecast/") :]
                if provider not in registry.PROVIDERS:
                    self._json(404, {"error": "unknown_provider"})
                    return
                self._json(200, forecast_document(connection, provider))
                return
        finally:
            connection.close()
        self._json(404, {"error": "not_found"})

    def _report(self, connection: sqlite3.Connection) -> None:
        observations: list[contract.Observation] = []
        for name in registry.PROVIDERS:
            document = store.latest(connection, name)
            if document is None or not document.get("answered"):
                observations.append(_stored_failure(name, document))
                continue
            windows = tuple(
                contract.Window(
                    label=entry.get("label", ""),
                    used_percent=float(entry.get("used_percent", 0.0)),
                    resets_in_seconds=entry.get("resets_in_seconds"),
                )
                for entry in document.get("windows", [])
                if isinstance(entry, dict) and entry.get("label")
            )
            credits = document.get("credits")
            if isinstance(credits, dict) and credits.get("state") in contract.CREDIT_STATES:
                restored = contract.Credits(credits["state"], credits.get("detail", ""))
            else:
                restored = contract.Credits()
            observations.append(
                contract.Observation(
                    provider=name,
                    collected_at=float(document.get("collected_at", 0.0)),
                    windows=windows,
                    credits=restored,
                )
            )
        body = report.render(observations).encode("utf-8")
        self._send(200, body, "text/markdown; charset=utf-8")

    def _screenshot(self, name: str) -> None:
        """Serve the latest portal capture, when one exists.

        Capture is off by default, so the ordinary answer here
        is 404. Nothing is generated on demand.
        """
        provider = name[:-4] if name.endswith(".png") else name
        if provider not in registry.PROVIDERS:
            self._json(404, {"error": "unknown_provider"})
            return
        path = Path(config.screenshot_path(provider, **self.state_kwargs))
        try:
            payload = path.read_bytes()
        except OSError:
            self._json(404, {"error": "no_screenshot"})
            return
        self._send(200, payload, "image/png")


def build_server(
    host: str = "127.0.0.1",
    port: int = DEFAULT_PORT,
    *,
    database_path: Path | None = None,
    connection_factory: Any = None,
    state_kwargs: dict[str, Any] | None = None,
) -> ThreadingHTTPServer:
    """Build the loopback server.

    Each request is served on its own thread and opens its
    own connection, because a SQLite connection belongs to
    the thread that created it. A ``connection_factory`` must
    therefore return a NEW connection on every call; handing
    back one shared connection raises inside the handler.
    """
    assert_loopback(host)
    server = ThreadingHTTPServer((host, port), Handler)
    if connection_factory is None:

        def connection_factory() -> sqlite3.Connection:
            return store.connect(database_path, **(state_kwargs or {}))

    server.connection_factory = connection_factory  # type: ignore[attr-defined]
    server.state_kwargs = state_kwargs or {}  # type: ignore[attr-defined]
    return server
