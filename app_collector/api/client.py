"""
Async upstream client: cursor pagination plus retry/backoff.

The client does not know which mode it is in. It receives a configured
httpx.AsyncClient (mock transport or real network) and behaves the same way.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import AsyncIterator, Awaitable, Callable

import httpx

RETRYABLE_STATUS = {429, 500, 502, 503, 504}

EventSink = Callable[[str, str], None]  # (level, message)
Sleep = Callable[[float], Awaitable[None]]


class UpstreamError(Exception):
    """Raised when a page cannot be fetched (non-retryable or retries exhausted)."""


@dataclass
class Page:
    number: int
    items: list[dict]
    attempts: int  # 1 = succeeded first time


def parse_retry_after(value: str | None) -> float | None:
    """Retry-After may be delta-seconds or an HTTP date (RFC 9110)."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


class APIClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        backoff_max: float = 30.0,
        on_event: EventSink | None = None,
        sleep: Sleep = asyncio.sleep,
        jitter: bool = True,
    ) -> None:
        self.http = http
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self.on_event = on_event or (lambda level, message: None)
        self.sleep = sleep
        self.jitter = jitter

    def _backoff(self, retry_number: int) -> float:
        delay = min(self.backoff_max, self.backoff_base * (2 ** (retry_number - 1)))
        if self.jitter:
            delay *= random.uniform(0.8, 1.2)
        return delay

    async def get_with_retry(self, path: str, params: dict, label: str = "Request") -> tuple[httpx.Response, int]:
        """GET with retries. Returns (response, attempts)."""
        attempt = 0
        while True:
            attempt += 1
            try:
                response = await self.http.get(path, params=params)
            except httpx.TransportError as exc:
                if attempt > self.max_retries:
                    raise UpstreamError(f"network error after {attempt} attempts: {exc!r}") from exc
                delay = self._backoff(attempt)
                self.on_event("warning", f"{label}: network error ({type(exc).__name__}), retrying in {delay:.1f}s")
                await self.sleep(delay)
                continue

            if response.status_code < 400:
                return response, attempt

            if response.status_code not in RETRYABLE_STATUS:
                raise UpstreamError(f"HTTP {response.status_code}: {response.text[:200]}")

            if attempt > self.max_retries:
                raise UpstreamError(
                    f"HTTP {response.status_code} persisted after {attempt} attempts"
                )

            retry_after = parse_retry_after(response.headers.get("Retry-After"))
            if retry_after is not None:
                delay = min(retry_after, self.backoff_max)
                source = f"Retry-After: {response.headers.get('Retry-After')}"
            else:
                delay = self._backoff(attempt)
                source = "exponential backoff"
            reason = "Too Many Requests" if response.status_code == 429 else "server error"
            self.on_event(
                "warning",
                f"{label}: HTTP {response.status_code} {reason}, waiting {delay:.1f}s then retrying ({source})",
            )
            await self.sleep(delay)

    async def iter_pages(self, client_id: str, path: str = "/apps", max_pages: int = 1000) -> AsyncIterator[Page]:
        cursor: str | None = None
        seen_cursors: set[str] = set()
        for number in range(1, max_pages + 1):
            params = {"client_id": client_id}
            if cursor:
                params["cursor"] = cursor
            self.on_event("info", f"GET page {number}" + (f" (cursor={cursor})" if cursor else ""))
            response, attempts = await self.get_with_retry(path, params, label=f"Page {number}")

            try:
                body = response.json()
            except ValueError as exc:
                raise UpstreamError(f"page {number} is not valid JSON") from exc
            items = body.get("items")
            if not isinstance(items, list):
                raise UpstreamError(f"page {number} has no 'items' list")

            self.on_event("info", f"Page {number}: HTTP 200 OK, {len(items)} apps received")
            yield Page(number=number, items=items, attempts=attempts)

            cursor = body.get("next_cursor")
            if not cursor:
                return
            if cursor in seen_cursors:
                raise UpstreamError(f"cursor loop detected at page {number}")
            seen_cursors.add(cursor)
        raise UpstreamError(f"stopped after {max_pages} pages")
