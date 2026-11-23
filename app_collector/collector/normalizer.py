"""
Turns one raw API record into one database row for a given client.

Pure functions (no I/O), so they are easy to test.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app_collector.config import ClientConfig

MAX_NOTES_LENGTH = 500
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class InvalidRecord(ValueError):
    """Record is missing app_id or app_name and cannot be stored."""


@dataclass
class NormalizedRecord:
    values: dict
    notes_truncated: bool
    risk_missing: bool


def sanitize_notes(raw: object, max_length: int = MAX_NOTES_LENGTH) -> tuple[str | None, bool]:
    """Remove control characters, collapse whitespace, cut to max_length.

    Returns (clean_text, was_truncated).
    """
    if raw is None:
        return None, False
    text = " ".join(_CONTROL_CHARS.sub(" ", str(raw)).split())
    if len(text) > max_length:
        return text[:max_length], True
    return text, False


def parse_risk_score(raw: object) -> int | None:
    """Missing or invalid -> None (unknown). Never guess 0, which would mean 'no risk'.

    Text like "high", emojis, "", "NaN", "inf", lists and booleans are all invalid.
    """
    if raw is None or isinstance(raw, bool):
        return None
    try:
        score = int(float(raw))  # int(nan) -> ValueError, int(inf) -> OverflowError
    except (TypeError, ValueError, OverflowError):
        return None
    return max(0, min(100, score))


def parse_users(raw: object) -> int | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return None


def normalize_record(raw: dict, client: ClientConfig, *, max_notes_length: int = MAX_NOTES_LENGTH,
                     missing_risk: str = "null") -> NormalizedRecord:
    """missing_risk: "null" stores NULL (default); "worst_case" stores 100 when the score is missing."""
    app_id = str(raw.get("app_id") or "").strip()
    app_name = " ".join(str(raw.get("app_name") or "").split())
    if not app_id:
        raise InvalidRecord("missing app_id")
    if not app_name:
        raise InvalidRecord(f"missing app_name for {app_id}")

    notes, truncated = sanitize_notes(raw.get("raw_notes"), min(max_notes_length, MAX_NOTES_LENGTH))
    risk = parse_risk_score(raw.get("risk_score"))
    risk_missing = risk is None
    if risk_missing and missing_risk == "worst_case":
        risk = 100  # never 0: an unknown app is not a safe app

    values = {
        "client_id": client.client_id,
        "app_id": app_id[:100],
        "app_name": app_name[:255],
        "classification": client.classify(app_name),
        "risk_score": risk,
        "users": parse_users(raw.get("users")),
        "raw_notes": notes,
        "notes_truncated": truncated,
    }
    return NormalizedRecord(values=values, notes_truncated=truncated, risk_missing=risk_missing)
