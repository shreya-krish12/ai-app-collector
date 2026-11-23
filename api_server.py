"""
Backend for the dashboard.

    python api_server.py      ->  http://127.0.0.1:8000   (API docs: /docs)

It also serves the mock API over HTTP at /upstream/apps, which is what
real-time mode calls.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from app_collector.api.upstream import PAGE_2_CURSOR, RETRY_AFTER_SECONDS, UpstreamSimulator, page_items
from app_collector.api.upstream_server import create_upstream_app
from app_collector.collector.ingester import Collector, Run
from app_collector.config import DB_FILE, Mode, settings
from app_collector.pytest_runner import run_pytest
from app_collector.rules import DEFAULT_RULES, MAX_NOTES_LIMIT, RULES_FILE, InvalidRules, RuleStore
from app_collector.storage.db import Database
from app_collector.utils.logger import logger


class RunRequest(BaseModel):
    mode: Literal["mock", "real"] = "mock"
    client_ids: list[str] | None = None


def create_app(db: Database | None = None, collector: Collector | None = None,
               rules: RuleStore | None = None) -> FastAPI:
    database = db or Database(settings.database_url)
    rules = rules or (collector.rules if collector else RuleStore(RULES_FILE))
    collector = collector or Collector(database, rules=rules)
    active_runs: dict[str, Run] = {}
    tasks: set[asyncio.Task] = set()
    playground = {"sim": UpstreamSimulator()}  # separate from the real-time server's state
    test_lock = asyncio.Lock()
    last_tests: dict = {"result": None}

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        database.create_all()
        if n := database.fail_interrupted_runs():
            logger.warning(f"Marked {n} interrupted run(s) as failed")
        logger.info("API ready on http://127.0.0.1:8000")
        yield

    app = FastAPI(title="AI App Collector", lifespan=lifespan)
    app.mount("/upstream", create_upstream_app())

    def is_running() -> bool:
        return any(r.status == "running" for r in active_runs.values())

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/config")
    def config():
        sqlite = database.engine.dialect.name == "sqlite"
        return {
            "default_mode": settings.default_mode.value,
            "upstream_base_url": settings.upstream_base_url,
            "clients": [{"client_id": c.client_id, "sanctioned_apps": list(c.sanctioned_apps)} for c in rules.clients().values()],
            "max_retries": settings.max_retries,
            "database": {
                "type": database.engine.dialect.name,
                "file": str(DB_FILE) if sqlite else None,
                "url": database.engine.url.render_as_string(hide_password=True),
            },
        }

    # ------------------------------------------------------ configuration tab
    def rules_view() -> dict:
        return {"rules": rules.get(), "defaults": DEFAULT_RULES, "is_default": rules.is_default(),
                "max_notes_limit": MAX_NOTES_LIMIT, "saved_to": str(rules.path) if rules.path else None}

    @app.get("/api/rules")
    def get_rules():
        return rules_view()

    @app.put("/api/rules")
    def put_rules(body: dict[str, Any]):
        if is_running():
            raise HTTPException(409, "Wait for the current run to finish before changing the rules.")
        try:
            rules.update(body)
        except InvalidRules as exc:
            raise HTTPException(400, str(exc)) from exc
        logger.info(f"Rules updated: {rules.get()}")
        return rules_view()

    @app.post("/api/rules/reset")
    def reset_rules():
        if is_running():
            raise HTTPException(409, "Wait for the current run to finish before changing the rules.")
        rules.reset()
        return rules_view()

    # ---------------------------------------------------------- mock API page
    @app.get("/api/mock-data")
    def mock_data():
        """What the mock API returns, for the 'Mock API' page."""
        return {
            "endpoint": "GET /apps?client_id=<client>&cursor=<cursor>",
            "retry_after_seconds": RETRY_AFTER_SECONDS,
            "clients": [
                {
                    "client_id": cid,
                    "sanctioned_apps": list(c.sanctioned_apps),
                    "page_1": {"items": page_items(cid, 1), "next_cursor": PAGE_2_CURSOR},
                    "page_2": {"items": page_items(cid, 2), "next_cursor": None},
                }
                for cid, c in rules.clients().items()
            ],
        }

    @app.get("/api/playground/apps")
    def playground_request(client_id: str | None = None, cursor: str | None = None):
        """Send one request to the mock API and show exactly what came back."""
        res = playground["sim"].handle(client_id, cursor)
        return {"status_code": res.status_code, "headers": res.headers, "body": res.body}

    @app.post("/api/playground/reset")
    def playground_reset():
        playground["sim"] = UpstreamSimulator()
        return {"reset": True}

    # ----------------------------------------------------------------- runs
    @app.post("/api/runs", status_code=202)
    async def start_run(body: RunRequest):
        if is_running():
            raise HTTPException(409, "A run is already in progress. Wait for it to finish.")
        try:
            run = collector.new_run(Mode(body.mode), body.client_ids)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        active_runs[run.id] = run
        for old in list(active_runs)[:-10]:  # keep the last 10 event logs in memory
            if active_runs[old].status != "running":
                active_runs.pop(old)
        task = asyncio.create_task(collector.run(Mode(body.mode), run=run))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return run.to_dict()

    @app.get("/api/runs")
    def list_runs(limit: int = Query(20, ge=1, le=100)):
        return database.list_runs(limit)

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str, after: int = Query(0, ge=0)):
        if run := active_runs.get(run_id):
            data = run.to_dict(include_events=False)
            data["events"] = [e for e in run.events if e["seq"] > after]
            return data
        stored = next((r for r in database.list_runs(100) if r["id"] == run_id), None)
        if not stored:
            raise HTTPException(404, "Run not found")
        return {**stored, "events": []}

    # --------------------------------------------------------------- data
    @app.get("/api/records")
    def records(client_id: str | None = None,
                classification: Literal["sanctioned", "unsanctioned"] | None = None):
        return database.list_records(client_id, classification)

    @app.delete("/api/records")
    def clear_records(client_id: str | None = None):
        if is_running():
            raise HTTPException(409, "Cannot clear records while a run is in progress.")
        return {"deleted": database.delete_records(client_id)}

    @app.get("/api/summary")
    def summary():
        return {"clients": database.summary_by_client(), "runs": database.list_runs(10)}

    # --------------------------------------------------------------- tests
    @app.post("/api/tests")
    async def run_tests():
        if test_lock.locked():
            raise HTTPException(409, "Tests are already running.")
        async with test_lock:
            last_tests["result"] = await asyncio.to_thread(run_pytest)
        return last_tests["result"]

    @app.get("/api/tests")
    def get_last_tests():
        return last_tests["result"]

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api_server:app", host="127.0.0.1", port=8000)
