"""
Settings and the two clients.

Each client has its own sanctioned_apps list. Every other app is
"unsanctioned" for that client.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_FILE = PROJECT_ROOT / "app_collector.db"


class Mode(str, Enum):
    """How the collector reaches the API. Everything else is identical.

    mock: httpx.MockTransport answers inside Python (no network).
    real: real HTTP calls to the FastAPI mock server (UPSTREAM_BASE_URL).
    """

    MOCK = "mock"
    REAL = "real"


def app_key(app_name: str) -> str:
    """'  github   COPILOT ' -> 'github copilot' (used for list matching)."""
    return " ".join(app_name.lower().split())


@dataclass(frozen=True)
class ClientConfig:
    client_id: str
    sanctioned_apps: tuple[str, ...]

    def classify(self, app_name: str) -> str:
        allowed = {app_key(a) for a in self.sanctioned_apps}
        return "sanctioned" if app_key(app_name) in allowed else "unsanctioned"


CLIENTS: dict[str, ClientConfig] = {
    "acme": ClientConfig("acme", ("ChatGPT", "GitHub Copilot")),
    "vontier": ClientConfig("vontier", ("Claude", "Gemini", "GitHub Copilot")),
}


@dataclass
class Settings:
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", f"sqlite:///{DB_FILE.as_posix()}")
    )
    default_mode: Mode = field(default_factory=lambda: Mode(os.getenv("APP_MODE", "mock").lower()))
    upstream_base_url: str = field(
        default_factory=lambda: os.getenv("UPSTREAM_BASE_URL", "http://127.0.0.1:8000/upstream")
    )
    upstream_token: str | None = field(default_factory=lambda: os.getenv("UPSTREAM_TOKEN"))
    http_timeout: float = field(default_factory=lambda: float(os.getenv("HTTP_TIMEOUT", "10")))
    max_retries: int = field(default_factory=lambda: int(os.getenv("MAX_RETRIES", "3")))
    backoff_base: float = field(default_factory=lambda: float(os.getenv("BACKOFF_BASE", "0.5")))
    backoff_max: float = field(default_factory=lambda: float(os.getenv("BACKOFF_MAX", "30")))
    max_notes_length: int = 500
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))


settings = Settings()
