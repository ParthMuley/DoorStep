"""SQLite persistence. Each record is stored as a JSON blob plus the columns we
index or constrain on. Provider inventories live in their own tables.

Write operations run inside ``BEGIN IMMEDIATE`` transactions so acceptance is
atomic; unique indexes enforce idempotency and one active accepted assignment
per case + service type.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS counters (prefix TEXT PRIMARY KEY, n INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS organizations (organization_id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS residents (
  resident_id TEXT PRIMARY KEY, zone_id TEXT NOT NULL, contact_channel TEXT NOT NULL, data TEXT NOT NULL);

-- Provider-owned inventories (separate tables, never joined into case rows).
CREATE TABLE IF NOT EXISTS transport_inventory (provider_id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS destination_inventory (provider_id TEXT PRIMARY KEY, data TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS alerts (
  alert_id TEXT PRIMARY KEY, zone_id TEXT NOT NULL, official_verified INTEGER NOT NULL, data TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS cases (
  case_id TEXT PRIMARY KEY, resident_id TEXT NOT NULL, zone_id TEXT NOT NULL,
  resident_status TEXT NOT NULL, communication_status TEXT NOT NULL, data TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS service_requests (
  request_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, service_type TEXT NOT NULL,
  status TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE, data TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS offers (
  offer_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, case_id TEXT NOT NULL,
  provider_id TEXT NOT NULL, eligible INTEGER NOT NULL, data TEXT NOT NULL,
  UNIQUE (request_id, provider_id));

CREATE TABLE IF NOT EXISTS assignments (
  assignment_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, service_type TEXT NOT NULL,
  provider_id TEXT NOT NULL, status TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
  data TEXT NOT NULL);
-- Only one active accepted assignment per resident case and service type.
CREATE UNIQUE INDEX IF NOT EXISTS one_accepted_assignment
  ON assignments (case_id, service_type) WHERE status IN ('ACCEPTED', 'COMPLETED');

CREATE TABLE IF NOT EXISTS verifications (
  verification_id TEXT PRIMARY KEY, assignment_id TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS messages (
  message_id TEXT PRIMARY KEY, case_id TEXT, direction TEXT NOT NULL,
  external_id TEXT UNIQUE, status TEXT NOT NULL, data TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS escalations (
  escalation_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
  data TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS referrals (
  referral_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, status TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE, data TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS consent_grants (
  id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, data TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE, case_id TEXT,
  correlation_id TEXT, event_type TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_by_case ON events (case_id, seq);
"""

TABLES = [
    "counters", "settings", "organizations", "residents", "transport_inventory",
    "destination_inventory", "alerts", "cases", "service_requests", "offers",
    "assignments", "verifications", "messages", "escalations", "referrals",
    "consent_grants", "events",
]


def default_db_path() -> str:
    return os.environ.get("DOORSTEP_DB_PATH", str(Path("var") / "doorstep_demo.db"))


class Database:
    def __init__(self, path: str | None = None):
        self.path = path or default_db_path()
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # A single shared connection guarded by a lock keeps writes serialized
        # (FastAPI runs sync handlers in a threadpool) and works for :memory:.
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.RLock()
        self._depth = 0
        self._conn.executescript(SCHEMA)

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Atomic write transaction (re-entrant: nested calls join the outer one)."""
        with self._lock:
            outer = self._depth == 0
            if outer:
                self._conn.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield self._conn
            except BaseException:
                self._depth -= 1
                if outer:
                    self._conn.execute("ROLLBACK")
                raise
            else:
                self._depth -= 1
                if outer:
                    self._conn.execute("COMMIT")

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            yield self._conn

    def wipe(self) -> None:
        with self.tx() as conn:
            for table in TABLES:
                conn.execute(f"DELETE FROM {table}")
            conn.execute("DELETE FROM sqlite_sequence")

    def next_id(self, prefix: str) -> str:
        """Deterministic sequential id (``assign_001``) -- reproducible after reset."""
        with self.tx() as conn:
            row = conn.execute("SELECT n FROM counters WHERE prefix = ?", (prefix,)).fetchone()
            n = (row["n"] if row else 0) + 1
            conn.execute(
                "INSERT INTO counters (prefix, n) VALUES (?, ?) "
                "ON CONFLICT(prefix) DO UPDATE SET n = excluded.n", (prefix, n))
        return f"{prefix}_{n:03d}"

    def get_setting(self, key: str, default: str) -> str:
        with self.read() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    def close(self) -> None:
        self._conn.close()
