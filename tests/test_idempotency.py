"""Idempotency: re-running updates the same (client_id, app_id) row, never duplicates it."""

from sqlalchemy import select

from app_collector.config import Mode
from app_collector.models import AppUsageRecord


def row(app_id="app-1", client_id="acme", **kw):
    return {"client_id": client_id, "app_id": app_id, "app_name": "App", "classification": "unsanctioned",
            "risk_score": 10, "users": 1, "raw_notes": None, "notes_truncated": False, **kw}


async def test_second_run_updates_instead_of_inserting(make_collector, db):
    collector = make_collector()
    first = await collector.run(Mode.MOCK)
    count_after_first = db.count_records()
    second = await collector.run(Mode.MOCK)

    assert count_after_first == db.count_records() == 12  # 6 apps x 2 clients
    assert (first.summary["totals"]["inserted"], first.summary["totals"]["updated"]) == (12, 0)
    assert (second.summary["totals"]["inserted"], second.summary["totals"]["updated"]) == (0, 12)


async def test_rerun_keeps_created_at_and_counts_runs(make_collector, db):
    collector = make_collector()
    await collector.run(Mode.MOCK)
    with db.Session() as s:
        before = {(r.client_id, r.app_id): r.created_at for r in s.scalars(select(AppUsageRecord))}
    await collector.run(Mode.REAL)

    with db.Session() as s:
        rows = s.scalars(select(AppUsageRecord)).all()
    assert len(rows) == len(before)
    assert all(r.created_at == before[(r.client_id, r.app_id)] for r in rows)
    assert all(r.times_collected == 2 for r in rows)


def test_upsert_overwrites_changed_values(db):
    db.upsert_records([row(risk_score=10)])
    assert db.upsert_records([row(risk_score=90, app_name="Renamed")]) == (0, 1)
    [record] = db.list_records()
    assert (record["risk_score"], record["app_name"]) == (90, "Renamed")


def test_same_app_twice_in_one_batch_is_one_row(db):
    assert db.upsert_records([row(risk_score=1), row(risk_score=2)]) == (1, 0)
    assert db.list_records()[0]["risk_score"] == 2


def test_same_app_id_for_two_clients_is_two_rows(db):
    db.upsert_records([row(client_id="acme")])
    db.upsert_records([row(client_id="vontier")])
    assert db.count_records() == 2


def test_empty_batch_does_nothing(db):
    assert db.upsert_records([]) == (0, 0)
