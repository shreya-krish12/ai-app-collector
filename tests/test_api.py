"""The HTTP API the dashboard uses."""

import time

import pytest
from fastapi.testclient import TestClient

from api_server import create_app


@pytest.fixture
def api(db, make_collector):
    with TestClient(create_app(db=db, collector=make_collector())) as client:
        yield client


def finish(api, run_id, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = api.get(f"/api/runs/{run_id}").json()
        if run["status"] != "running":
            return run
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def test_run_then_read_records_and_summary(api):
    started = api.post("/api/runs", json={"mode": "mock"})
    assert started.status_code == 202
    run = finish(api, started.json()["id"])

    assert run["status"] == "completed"
    assert any("429" in e["message"] for e in run["events"])
    assert len(api.get("/api/records", params={"client_id": "acme"}).json()) == 6

    summary = {c["client_id"]: c for c in api.get("/api/summary").json()["clients"]}
    assert summary["acme"]["apps"] == summary["vontier"]["apps"] == 6
    assert summary["acme"]["missing_risk"] == summary["acme"]["truncated"] == 1


def test_mock_data_page_and_playground(api):
    data = api.get("/api/mock-data").json()
    assert [c["client_id"] for c in data["clients"]] == ["acme", "vontier"]

    params = {"client_id": "acme", "cursor": "page-2"}
    first = api.get("/api/playground/apps", params=params).json()
    second = api.get("/api/playground/apps", params=params).json()
    assert (first["status_code"], first["headers"]["Retry-After"]) == (429, "1")
    assert second["status_code"] == 200 and second["body"]["next_cursor"] is None


def test_bad_input_is_rejected(api):
    assert api.post("/api/runs", json={"mode": "live"}).status_code == 422
    assert api.post("/api/runs", json={"mode": "mock", "client_ids": ["globex"]}).status_code == 400
    assert api.get("/api/records", params={"classification": "maybe"}).status_code == 422
    assert api.get("/api/runs/nope").status_code == 404


def test_clear_records_for_one_client(api):
    finish(api, api.post("/api/runs", json={"mode": "mock"}).json()["id"])
    assert api.delete("/api/records", params={"client_id": "acme"}).json() == {"deleted": 6}
    assert len(api.get("/api/records").json()) == 6
