"""Mock mode and real-time mode share all code and produce the same rows."""

from app_collector.config import Mode


def comparable(records):
    return [{k: v for k, v in r.items() if k not in {"id", "created_at", "updated_at", "times_collected"}}
            for r in records]


async def test_real_time_mode_uses_http_and_handles_429(make_collector, db, simulator, fake_sleep):
    run = await make_collector().run(Mode.REAL)

    assert run.status == "completed"
    assert db.count_records() == 12
    assert [s for _, c, s in simulator.request_log if c].count(429) == 2  # once per client
    assert fake_sleep.calls == [1.0, 1.0]


async def test_mock_and_real_time_give_identical_rows(make_collector, db):
    collector = make_collector()
    await collector.run(Mode.MOCK)
    mock_rows = comparable(db.list_records())
    db.delete_records()
    await collector.run(Mode.REAL)
    assert comparable(db.list_records()) == mock_rows


async def test_run_summary(make_collector):
    t = (await make_collector().run(Mode.MOCK)).summary["totals"]
    assert (t["pages"], t["received"], t["retries"]) == (4, 12, 2)
    assert (t["truncated"], t["missing_risk"]) == (2, 2)  # Otter.ai, once per client
    assert t["sanctioned"] + t["unsanctioned"] == 12


async def test_run_is_saved(make_collector, db):
    run = await make_collector().run(Mode.MOCK)
    [stored] = db.list_runs()
    assert (stored["id"], stored["status"], stored["summary"]["totals"]["received"]) == (run.id, "completed", 12)
