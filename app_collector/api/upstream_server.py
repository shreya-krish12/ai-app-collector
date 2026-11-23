"""
Real-time mode upstream: the shared UpstreamSimulator served over HTTP.

The API server mounts this app at /upstream. It can also run on its own:
    python -m app_collector.api.upstream_server --port 8001
and then UPSTREAM_BASE_URL=http://127.0.0.1:8001
"""

from __future__ import annotations

import argparse

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from app_collector.api.upstream import UpstreamSimulator


def create_upstream_app(simulator: UpstreamSimulator | None = None) -> FastAPI:
    sim = simulator or UpstreamSimulator()
    app = FastAPI(title="Simulated AI App Usage API")
    app.state.simulator = sim

    @app.get("/apps")
    def list_apps(client_id: str | None = Query(None), cursor: str | None = Query(None)):
        result = sim.handle(client_id, cursor)
        return JSONResponse(result.body, status_code=result.status_code, headers=result.headers)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    uvicorn.run(create_upstream_app(), host="127.0.0.1", port=args.port)
