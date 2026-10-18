"""Shared helpers for Fetch.ai messaging: timestamps and correlation IDs.
Message models live in `fetch_messages.py` (contract v2.0); agent addressing in
`agents/base.py`."""

from datetime import datetime, timezone
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_correlation_id() -> str:
    return f"corr_{uuid4().hex[:12]}"
