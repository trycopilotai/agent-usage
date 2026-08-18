"""A local SQLite record of what each provider reported.

Only the allowlisted observation fields are written, and they
pass through the redaction boundary on the way in rather than
on the way out. Filtering at read time leaves the sensitive
value on disk, where the next reader finds it.

History exists for one reason: a rate needs two points.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from . import config, contract, redaction

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    collected_at REAL NOT NULL,
    answered INTEGER NOT NULL,
    source TEXT NOT NULL,
    error TEXT,
    binding_label TEXT,
    binding_percent REAL,
    document TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS observations_provider_time
    ON observations (provider, collected_at);
"""


def connect(path: Path | None = None, **kwargs: Any) -> sqlite3.Connection:
    target = config.database_path(**kwargs) if path is None else Path(path)
    if str(target) != ":memory:":
        config.ensure_private(target.parent)
    connection = sqlite3.connect(str(target))
    connection.row_factory = sqlite3.Row
    connection.executescript(_SCHEMA)
    connection.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
        ("schema_version", str(SCHEMA_VERSION)),
    )
    connection.commit()
    return connection


def record(connection: sqlite3.Connection, observation: contract.Observation) -> int:
    document = redaction.filter_observation(observation.to_dict())
    binding = document.get("binding_window") or {}
    cursor = connection.execute(
        "INSERT INTO observations "
        "(provider, collected_at, answered, source, error, binding_label, "
        "binding_percent, document) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            document["provider"],
            float(document["collected_at"]),
            1 if document.get("answered") else 0,
            document.get("source", ""),
            document.get("error"),
            binding.get("label"),
            binding.get("used_percent"),
            json.dumps(document, sort_keys=True),
        ),
    )
    connection.commit()
    return int(cursor.lastrowid)


def samples(
    connection: sqlite3.Connection,
    provider: str,
    *,
    since: float | None = None,
    limit: int = 5000,
) -> list[tuple[float, float]]:
    """Answered binding percentages, oldest first.

    Unanswered rows are excluded rather than counted as zero,
    which is the same rule the contract states.
    """
    query = (
        "SELECT collected_at, binding_percent FROM observations "
        "WHERE provider = ? AND answered = 1 AND binding_percent IS NOT NULL"
    )
    values: list[Any] = [provider]
    if since is not None:
        query += " AND collected_at >= ?"
        values.append(float(since))
    query += " ORDER BY collected_at ASC LIMIT ?"
    values.append(int(limit))
    rows = connection.execute(query, values).fetchall()
    return [(float(row["collected_at"]), float(row["binding_percent"])) for row in rows]


def latest(connection: sqlite3.Connection, provider: str) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT document FROM observations WHERE provider = ? "
        "ORDER BY collected_at DESC LIMIT 1",
        (provider,),
    ).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row["document"])
    except ValueError:
        return None


def freshness_of(
    document: dict[str, Any],
    now: float | None = None,
    live_seconds: float = 300.0,
    cached_seconds: float = 3600.0,
) -> str:
    """Classify a stored read by age.

    A read stays live only while it is younger than the live
    window. Past that it is cached, and past the cached
    window it is stale, so an old reading cannot present
    itself as current.
    """
    moment = time.time() if now is None else now
    age = moment - float(document.get("collected_at", 0.0))
    if age <= live_seconds:
        return contract.FRESHNESS_LIVE
    if age <= cached_seconds:
        return contract.FRESHNESS_CACHED
    return contract.FRESHNESS_STALE
