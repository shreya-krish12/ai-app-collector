"""
The collector: for each client (in parallel) fetch every page, normalise each
record with that client's rules, and upsert page by page.

Mock and real-time mode only differ in the httpx.AsyncClient that is passed in.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict, dataclass, field
from typing import Callable

import httpx

from app_collector.api.client import APIClient, Sleep, UpstreamError
from app_collector.api.mock_api import MOCK_BASE_URL, build_mock_transport
from app_collector.api.upstream import UpstreamSimulator
from app_collector.collector.normalizer import InvalidRecord, normalize_record
from app_collector.config import ClientConfig, Mode, Settings, settings as default_settings
from app_collector.models import utcnow
from app_collector.rules import RuleStore
from app_collector.storage.db import Database
from app_collector.utils.logger import logger

HttpFactory = Callable[[Mode], httpx.AsyncClient]


@dataclass
class ClientStats:
    client_id: str
    status: str = "waiting"  # waiting | running | completed | failed
    pages: int = 0
    received: int = 0
    inserted: int = 0
    updated: int = 0
    rejected: int = 0
    retries: int = 0
    truncated: int = 0
    missing_risk: int = 0
    sanctioned: int = 0
    unsanctioned: int = 0
    error: str | None = None


COUNTERS = ("pages", "received", "inserted", "updated", "rejected", "retries",
            "truncated", "missing_risk", "sanctioned", "unsanctioned")


@dataclass
class Run:
    mode: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "running"
    started_at: str = field(default_factory=lambda: utcnow().isoformat())
    finished_at: str | None = None
    error: str | None = None
    clients: dict[str, ClientStats] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)

    def emit(self, level: str, message: str, client_id: str | None = None) -> None:
        self.events.append({"seq": len(self.events) + 1, "ts": utcnow().isoformat(),
                            "level": level, "client_id": client_id, "message": message})
        log = {"warning": logger.warning, "error": logger.error}.get(level, logger.info)
        log(f"[{self.mode}]" + (f"[{client_id}] " if client_id else " ") + message)

    @property
    def summary(self) -> dict:
        totals = {k: sum(getattr(s, k) for s in self.clients.values()) for k in COUNTERS}
        return {"totals": totals, "clients": {cid: asdict(s) for cid, s in self.clients.items()}}

    def to_dict(self, include_events: bool = True) -> dict:
        data = {"id": self.id, "mode": self.mode, "status": self.status,
                "started_at": self.started_at, "finished_at": self.finished_at,
                "error": self.error, "summary": self.summary}
        if include_events:
            data["events"] = list(self.events)
        return data


def default_http_factory(cfg: Settings) -> HttpFactory:
    def factory(mode: Mode) -> httpx.AsyncClient:
        if mode is Mode.MOCK:
            # New simulator per run, so page 2 answers 429 once per run.
            return httpx.AsyncClient(transport=build_mock_transport(UpstreamSimulator()), base_url=MOCK_BASE_URL)
        headers = {"Authorization": f"Bearer {cfg.upstream_token}"} if cfg.upstream_token else {}
        return httpx.AsyncClient(base_url=cfg.upstream_base_url, timeout=cfg.http_timeout, headers=headers)

    return factory


class Collector:
    def __init__(self, db: Database, cfg: Settings = default_settings, http_factory: HttpFactory | None = None,
                 sleep: Sleep = asyncio.sleep, clients: dict[str, ClientConfig] | None = None,
                 rules: RuleStore | None = None) -> None:
        self.db = db
        self.cfg = cfg
        self.http_factory = http_factory or default_http_factory(cfg)
        self.sleep = sleep
        # `clients` (tests) fixes the sanctioned lists; otherwise they come from the editable rules.
        self.fixed_clients = clients
        self.rules = rules or RuleStore()

    @property
    def clients(self) -> dict[str, ClientConfig]:
        if self.fixed_clients is not None:
            return self.fixed_clients
        return self.rules.clients()

    def new_run(self, mode: Mode, client_ids: list[str] | None = None) -> Run:
        run = Run(mode=mode.value)
        for cid in client_ids or list(self.clients):
            if cid not in self.clients:
                raise ValueError(f"unknown client_id '{cid}'")
            run.clients[cid] = ClientStats(client_id=cid)
        return run

    async def run(self, mode: Mode, client_ids: list[str] | None = None, run: Run | None = None) -> Run:
        run = run or self.new_run(mode, client_ids)
        # Read the rules once, so a change made during a run does not mix old and new rules.
        rules, clients = self.rules.get(), self.clients
        where = "httpx.MockTransport (inside Python)" if mode is Mode.MOCK else self.cfg.upstream_base_url
        run.emit("info", f"Started {mode.value} run for {', '.join(run.clients)} -> {where}")
        run.emit("info", f"Rules: raw_notes <= {rules['max_notes_length']} chars, missing risk_score -> "
                         f"{'NULL' if rules['missing_risk'] == 'null' else '100 (worst case)'}")
        await asyncio.to_thread(self.db.save_run, run.to_dict(include_events=False))
        try:
            async with self.http_factory(mode) as http:
                await asyncio.gather(*(self._collect(run, clients[c], http, rules) for c in run.clients))
            failed = [s for s in run.clients.values() if s.status == "failed"]
            run.status = "completed" if not failed else "failed" if len(failed) == len(run.clients) else "partial"
        except Exception as exc:
            run.status, run.error = "failed", repr(exc)
            run.emit("error", f"Run stopped: {exc!r}")
        finally:
            run.finished_at = utcnow().isoformat()
            t = run.summary["totals"]
            run.emit("info" if run.status == "completed" else "error",
                     f"Finished ({run.status}): {t['received']} received, {t['inserted']} new, "
                     f"{t['updated']} updated, {t['rejected']} rejected")
            await asyncio.to_thread(self.db.save_run, run.to_dict(include_events=False))
        return run

    async def _collect(self, run: Run, client: ClientConfig, http: httpx.AsyncClient, rules: dict) -> None:
        stats = run.clients[client.client_id]
        stats.status = "running"

        def on_event(level: str, message: str) -> None:
            if level == "warning":  # APIClient only warns when it is about to retry
                stats.retries += 1
            run.emit(level, message, client.client_id)

        api = APIClient(http, max_retries=self.cfg.max_retries, backoff_base=self.cfg.backoff_base,
                        backoff_max=self.cfg.backoff_max, on_event=on_event, sleep=self.sleep)
        try:
            async for page in api.iter_pages(client.client_id):
                stats.pages += 1
                stats.received += len(page.items)
                rows = []
                for raw in page.items:
                    try:
                        rec = normalize_record(raw, client, max_notes_length=rules["max_notes_length"],
                                               missing_risk=rules["missing_risk"])
                    except InvalidRecord as exc:
                        stats.rejected += 1
                        run.emit("warning", f"Rejected a record: {exc}", client.client_id)
                        continue
                    stats.truncated += rec.notes_truncated
                    stats.missing_risk += rec.risk_missing
                    setattr(stats, rec.values["classification"], getattr(stats, rec.values["classification"]) + 1)
                    if rec.notes_truncated:
                        run.emit("info", f"{rec.values['app_id']}: raw_notes cleaned and cut to {rules['max_notes_length']} characters", client.client_id)
                    if rec.risk_missing:
                        run.emit("info", f"{rec.values['app_id']}: risk_score is missing, stored as "
                                         + ("NULL (unknown)" if rules['missing_risk'] == 'null' else "100 (worst case)"), client.client_id)
                    rows.append(rec.values)

                inserted, updated = await asyncio.to_thread(self.db.upsert_records, rows)
                stats.inserted += inserted
                stats.updated += updated
                sanctioned = sum(r["classification"] == "sanctioned" for r in rows)
                run.emit("info", f"Page {page.number}: saved {inserted} new + {updated} updated "
                                 f"({sanctioned} sanctioned, {len(rows) - sanctioned} unsanctioned)", client.client_id)
            stats.status = "completed"
        except UpstreamError as exc:
            stats.status, stats.error = "failed", str(exc)
            run.emit("error", f"Failed: {exc}", client.client_id)
