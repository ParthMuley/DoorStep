"""MongoDB persistence: two databases.

* ``doorstep_users``: residents and operational data (cases, messages,
  assignments, alerts, events, ...).
* ``doorstep_orgs``: organizations / provider registry and provider events.

Tests and the offline smoke test use ``mongomock`` (same API, in memory).
Atomicity comes from single-document operations: unique indexes,
conditional ``update_one`` / ``find_one_and_update`` and ``$inc`` counters.
There are no multi-collection transactions, so the engine checks every guard
*before* writing (see docs/decisions.md B-20). ``tx()`` serializes writes
inside this process.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from pymongo import ASCENDING, ReturnDocument
from pymongo.collection import Collection

# Collections that live in the organizations database; everything else is users/operational.
ORG_COLLECTIONS = {"organizations", "provider_registry", "provider_events"}

USERS_COLLECTIONS = [
    "residents", "cases", "alerts", "service_requests", "offers", "assignments", "verifications",
    "messages", "escalations", "referrals", "consent_grants", "events", "settings", "counters",
    "zone_alerts", "feeds", "ingests", "checkins", "synthetic_feed",
]


def _truthy(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes")


def _make_client(uri: Optional[str], use_mock: bool):
    if use_mock:
        import mongomock

        return mongomock.MongoClient(tz_aware=True)
    from pymongo import MongoClient

    return MongoClient(uri or os.environ.get("MONGODB_URI", "mongodb://localhost:27017"),
                       serverSelectionTimeoutMS=5000, tz_aware=True)


class Database:
    """``Database(":memory:")`` = fresh in-memory mongomock (tests, A's integration tests).
    ``Database()`` = ``MONGODB_URI`` (or mongomock when ``USE_MONGOMOCK=true``).
    ``Database(client=c)`` = reuse a client (e.g. to simulate a backend restart)."""

    def __init__(self, path: Optional[str] = None, *, uri: Optional[str] = None, client: Any = None,
                 users_db: Optional[str] = None, orgs_db: Optional[str] = None):
        if client is None:
            if path and path.startswith("mongodb"):
                uri = path
            use_mock = path == ":memory:" or (path is None and uri is None and _truthy(os.environ.get("USE_MONGOMOCK")))
            client = _make_client(uri, use_mock)
        self.client = client
        self.users = client[users_db or os.environ.get("MONGODB_USERS_DB", "doorstep_users")]
        self.orgs = client[orgs_db or os.environ.get("MONGODB_ORGS_DB", "doorstep_orgs")]
        self._lock = threading.RLock()
        self._ensure_indexes()

    # ------------------------------------------------------------- basics
    def coll(self, name: str) -> Collection:
        return (self.orgs if name in ORG_COLLECTIONS else self.users)[name]

    def _ensure_indexes(self) -> None:
        def index(coll: str, keys, **kwargs) -> None:
            collection = self.coll(coll)
            name = kwargs.setdefault("name", f"{coll}__" + "__".join(
                k if isinstance(k, str) else k[0] for k in ([keys] if isinstance(keys, str) else keys)))
            if name not in collection.index_information():  # existing index: no-op (restart-safe)
                collection.create_index(keys, **kwargs)

        index("assignments", "idempotency_key", unique=True)
        # One active accepted assignment per case + service type (field set only while ACCEPTED/COMPLETED).
        index("assignments", "_accepted_slot", unique=True,
              partialFilterExpression={"_accepted_slot": {"$exists": True}})
        index("assignments", [("case_id", ASCENDING), ("_ord", ASCENDING)])
        index("messages", "external_id", unique=True,
              partialFilterExpression={"external_id": {"$type": "string"}})
        index("escalations", "idempotency_key", unique=True)
        index("referrals", "idempotency_key", unique=True)
        index("events", "event_id", unique=True)
        index("events", [("case_id", ASCENDING), ("seq", ASCENDING)])
        index("offers", [("case_id", ASCENDING), ("request_id", ASCENDING), ("_ord", ASCENDING)])
        index("cases", "resident_id")

    @contextmanager
    def tx(self) -> Iterator[None]:
        """Serialize a group of writes in this process. Not a rollback: callers validate first."""
        with self._lock:
            yield

    def wipe(self) -> None:
        with self._lock:
            for name in USERS_COLLECTIONS:
                self.users[name].delete_many({})
            for name in ORG_COLLECTIONS:
                self.orgs[name].delete_many({})

    # ------------------------------------------------------------ counters
    def _inc(self, name: str) -> int:
        doc = self.coll("counters").find_one_and_update(
            {"_id": name}, {"$inc": {"n": 1}}, upsert=True, return_document=ReturnDocument.AFTER)
        return int(doc["n"])

    def next_id(self, prefix: str) -> str:
        """Deterministic sequential id (``assign_001``), reproducible after reset."""
        return f"{prefix}_{self._inc(prefix):03d}"

    def next_seq(self, name: str) -> int:
        return self._inc(f"seq:{name}")

    def next_ord(self) -> int:
        """Monotonic insertion order (stands in for SQLite rowid ordering)."""
        return self._inc("_ord")

    # ------------------------------------------------------------ settings
    def get_setting(self, key: str, default: str) -> str:
        doc = self.coll("settings").find_one({"_id": key})
        return doc["value"] if doc else default

    def set_setting(self, key: str, value: str) -> None:
        self.coll("settings").update_one({"_id": key}, {"$set": {"value": value}}, upsert=True)

    def ping(self) -> dict[str, str]:
        out = {}
        for label, db in (("users", self.users), ("orgs", self.orgs)):
            try:
                db.command("ping")
                out[label] = "ok"
            except Exception as exc:  # pragma: no cover - only with a real server down
                out[label] = f"error: {type(exc).__name__}"
        return out

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if close:
            close()
