# -*- coding: utf-8 -*-
"""Database-backed project leases and bounded task event journal helpers.

These helpers are intentionally small and dependency-light. MongoDB provides the
atomic compare-and-set behavior; a process-local lock alone cannot protect tasks
when a deployment accidentally starts multiple workers.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

DEFAULT_LEASE_SECONDS = 180
MAX_EVENT_TEXT = 1400


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def claim_project_lease(collection: Any, pid: str, owner: str, *, now: datetime | None = None,
                        lease_seconds: int = DEFAULT_LEASE_SECONDS) -> bool:
    """Atomically claim an expired/unowned project lease. False means another owner holds it."""
    current = now or utcnow()
    expires = current + timedelta(seconds=max(30, min(int(lease_seconds), 3600)))
    query = {"pid": str(pid), "$or": [{"expires_at": {"$lte": current}}, {"owner": str(owner)}]}
    try:
        result = collection.update_one(query, {"$set": {
            "pid": str(pid), "owner": str(owner), "claimed_at": current,
            "updated_at": current, "expires_at": expires,
        }}, upsert=True)
        return bool(getattr(result, "matched_count", 0) or getattr(result, "upserted_id", None))
    except Exception as exc:
        # A unique pid index turns a simultaneous upsert by another worker into a
        # duplicate-key conflict. Treat that as an ordinary lock contention only.
        if exc.__class__.__name__ in {"DuplicateKeyError", "BulkWriteError"}:
            return False
        raise


def renew_project_lease(collection: Any, pid: str, owner: str, *, now: datetime | None = None,
                        lease_seconds: int = DEFAULT_LEASE_SECONDS) -> bool:
    current = now or utcnow()
    result = collection.update_one(
        {"pid": str(pid), "owner": str(owner), "expires_at": {"$gt": current}},
        {"$set": {"updated_at": current,
                   "expires_at": current + timedelta(seconds=max(30, min(int(lease_seconds), 3600)))}}
    )
    return bool(getattr(result, "matched_count", 0))


def release_project_lease(collection: Any, pid: str, owner: str) -> bool:
    result = collection.delete_one({"pid": str(pid), "owner": str(owner)})
    return bool(getattr(result, "deleted_count", 0))


def sanitize_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """Persist only bounded milestone metadata, never raw provider request/headers."""
    kind = str(event.get("t") or "event")[:32]
    out: dict[str, Any] = {"type": kind}
    for key in ("x", "text", "path", "tool", "n", "status"):
        value = event.get(key)
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            out[key] = str(value)[:MAX_EVENT_TEXT] if isinstance(value, str) else value
    # Keep event payloads compact and JSON-friendly.
    return out
