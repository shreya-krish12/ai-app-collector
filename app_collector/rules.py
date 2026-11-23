"""
Normalisation rules that can be changed from the Configuration tab.

    sanctioned_apps   per client: which apps that client allows
    missing_risk      "null"       -> store NULL (unknown)          [default]
                      "worst_case" -> store 100 (treat as high risk)
    max_notes_length  raw_notes are cut to this many characters (1..500, default 500)

Defaults are the assignment's values. Changes are saved to a JSON file so they
survive a restart, and are picked up at the start of the next run.
"""

from __future__ import annotations

import copy
import json
import threading
from pathlib import Path

from app_collector.config import CLIENTS, PROJECT_ROOT, ClientConfig, app_key
from app_collector.utils.logger import logger

RULES_FILE = PROJECT_ROOT / "rules.json"
MISSING_RISK_POLICIES = ("null", "worst_case")
WORST_CASE_RISK = 100
MAX_NOTES_LIMIT = 500  # the requirement says <= 500, so the setting can go lower but never higher

DEFAULT_RULES: dict = {
    "sanctioned_apps": {cid: list(c.sanctioned_apps) for cid, c in CLIENTS.items()},
    "missing_risk": "null",
    "max_notes_length": 500,
}


class InvalidRules(ValueError):
    pass


def validate(rules: dict) -> dict:
    """Check and clean a rules dict. Raises InvalidRules with a readable message."""
    if not isinstance(rules, dict):
        raise InvalidRules("rules must be an object")

    apps = rules.get("sanctioned_apps")
    if not isinstance(apps, dict):
        raise InvalidRules("sanctioned_apps must be an object of client_id -> list of app names")
    unknown = set(apps) - set(CLIENTS)
    if unknown:
        raise InvalidRules(f"unknown client_id: {', '.join(sorted(unknown))}")
    clean_apps: dict[str, list[str]] = {}
    for cid in CLIENTS:
        names = apps.get(cid, [])
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            raise InvalidRules(f"sanctioned_apps.{cid} must be a list of names")
        seen, out = set(), []
        for name in names:
            name = " ".join(name.split())
            if not name:
                raise InvalidRules(f"sanctioned_apps.{cid} has an empty name")
            if len(name) > 100:
                raise InvalidRules(f"sanctioned_apps.{cid}: '{name[:20]}...' is longer than 100 characters")
            if app_key(name) not in seen:  # 'ChatGPT' and ' chatgpt ' are the same app
                seen.add(app_key(name))
                out.append(name)
        clean_apps[cid] = out

    policy = rules.get("missing_risk")
    if policy not in MISSING_RISK_POLICIES:
        raise InvalidRules(f"missing_risk must be one of: {', '.join(MISSING_RISK_POLICIES)}")

    length = rules.get("max_notes_length")
    if isinstance(length, bool) or not isinstance(length, int) or not 1 <= length <= MAX_NOTES_LIMIT:
        raise InvalidRules(f"max_notes_length must be a whole number from 1 to {MAX_NOTES_LIMIT}")

    return {"sanctioned_apps": clean_apps, "missing_risk": policy, "max_notes_length": length}


class RuleStore:
    """Holds the current rules. With `path=None` it lives in memory only (tests)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._rules = copy.deepcopy(DEFAULT_RULES)
        if path and path.exists():
            try:
                self._rules = validate(json.loads(path.read_text(encoding="utf-8")))
            except (ValueError, OSError) as exc:  # bad file -> keep defaults, do not crash
                logger.warning(f"Ignoring {path.name}: {exc}. Using default rules.")

    def get(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._rules)

    def update(self, rules: dict) -> dict:
        clean = validate(rules)
        with self._lock:
            self._rules = clean
            self._save()
        return copy.deepcopy(clean)

    def reset(self) -> dict:
        with self._lock:
            self._rules = copy.deepcopy(DEFAULT_RULES)
            if self.path and self.path.exists():
                self.path.unlink()
        return self.get()

    def is_default(self) -> bool:
        return self.get() == DEFAULT_RULES

    def clients(self) -> dict[str, ClientConfig]:
        rules = self.get()
        return {cid: ClientConfig(cid, tuple(names)) for cid, names in rules["sanctioned_apps"].items()}

    def _save(self) -> None:
        if self.path:
            self.path.write_text(json.dumps(self._rules, indent=2, ensure_ascii=False), encoding="utf-8")
