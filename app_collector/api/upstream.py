"""
The mock AI-app-usage API: its data and its rules. Used by BOTH modes.

    GET /apps?client_id=acme                      -> page 1 + next_cursor
    GET /apps?client_id=acme&cursor=page-2        -> 429 first time, then page 2

Every record: app_id, app_name, users, risk_score, raw_notes.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

PAGE_2_CURSOR = "page-2"
RETRY_AFTER_SECONDS = 1

# Exactly 650 characters, with extra spaces and a control character (\x07)
# so the sanitiser has something to clean.
LONG_NOTES = (
    "Meeting audio is uploaded to a third-party transcription service.\x07  Transcripts "
    "are kept by the vendor and may be used for model training unless the opt-out is "
    "enabled. "
)
LONG_NOTES = (LONG_NOTES * 5)[:650]
assert len(LONG_NOTES) == 650

# (app_id, app_name, risk_score, raw_notes) -- same apps for both clients
PAGE_1 = [
    ("chatgpt", "ChatGPT", 30, "Company workspace with SSO."),
    ("claude", "Claude", 25, "Team plan, 30-day data retention."),
    ("copilot", "GitHub Copilot", 20, "Used inside code editors."),
]
PAGE_2 = [
    ("gemini", "Gemini", 45, "Some personal accounts seen."),
    ("otter", "Otter.ai", None, LONG_NOTES),  # the 650-char + null risk_score record
    ("midjourney", "Midjourney", 70, "Image generator, no admin controls."),
]

# Active users per app differ per client, so the two clients are independent.
USERS = {
    "acme": {"chatgpt": 120, "claude": 35, "copilot": 60, "gemini": 18, "otter": 12, "midjourney": 9},
    "vontier": {"chatgpt": 40, "claude": 95, "copilot": 70, "gemini": 50, "otter": 22, "midjourney": 4},
}


def page_items(client_id: str, page: int) -> list[dict]:
    rows = PAGE_1 if page == 1 else PAGE_2
    return [
        {"app_id": a, "app_name": n, "users": USERS[client_id][a], "risk_score": r, "raw_notes": notes}
        for a, n, r, notes in rows
    ]


@dataclass
class UpstreamResponse:
    status_code: int
    body: dict
    headers: dict[str, str] = field(default_factory=dict)


class UpstreamSimulator:
    """Remembers how often page 2 was asked for, to return 429 on every first try."""

    def __init__(self) -> None:
        self.page_2_attempts: dict[str, int] = defaultdict(int)
        self.request_log: list[tuple[str, str | None, int]] = []  # (client, cursor, status)

    def handle(self, client_id: str | None, cursor: str | None) -> UpstreamResponse:
        response = self._handle(client_id, cursor)
        self.request_log.append((client_id or "", cursor, response.status_code))
        return response

    def _handle(self, client_id: str | None, cursor: str | None) -> UpstreamResponse:
        if not client_id:
            return UpstreamResponse(400, {"error": "client_id is required"})
        if client_id not in USERS:
            return UpstreamResponse(404, {"error": f"unknown client_id '{client_id}'"})
        if cursor is None:
            return UpstreamResponse(200, {"items": page_items(client_id, 1), "next_cursor": PAGE_2_CURSOR})
        if cursor != PAGE_2_CURSOR:
            return UpstreamResponse(400, {"error": "invalid cursor"})

        self.page_2_attempts[client_id] += 1
        if self.page_2_attempts[client_id] % 2 == 1:  # 1st, 3rd, ... attempt
            return UpstreamResponse(
                429, {"error": "Too Many Requests"}, {"Retry-After": str(RETRY_AFTER_SECONDS)}
            )
        return UpstreamResponse(200, {"items": page_items(client_id, 2), "next_cursor": None})
