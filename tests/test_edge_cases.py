"""
Extra edge cases:
  1. pagination with N pages (not only 2)
  2. 429 repeated several times before 200
  3. a new / unknown AI app that is on nobody's list
  4. strange risk_score values and emojis
  5. a second run checked row by row, not only by count
"""

import httpx
import pytest
from sqlalchemy import func, select

from app_collector.api.client import APIClient, UpstreamError
from app_collector.collector.ingester import Collector
from app_collector.collector.normalizer import normalize_record, parse_risk_score, sanitize_notes
from app_collector.config import CLIENTS, Mode, Settings
from app_collector.models import AppUsageRecord

ACME, VONTIER = CLIENTS["acme"], CLIENTS["vontier"]


def paged_api(n_pages: int, per_page: int = 2, fail_first: int = 0, risk=10, apps=None,
              always_429_for: str | None = None) -> httpx.AsyncClient:
    """A fake API with `n_pages` pages (cursors p2, p3, ...).

    fail_first:     each page answers 429 (Retry-After: 1) this many times before 200.
    apps:           fixed list of items for page 1 (overrides the generated ones).
    always_429_for: this client_id never gets anything but 429.
    """
    log: list[tuple[str, int, int]] = []  # (client_id, page, status)
    tries: dict[tuple[str, int], int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        client_id = request.url.params.get("client_id")
        cursor = request.url.params.get("cursor")
        page = int(cursor[1:]) if cursor else 1
        tries[(client_id, page)] = tries.get((client_id, page), 0) + 1
        if client_id == always_429_for or tries[(client_id, page)] <= fail_first:
            log.append((client_id, page, 429))
            return httpx.Response(429, headers={"Retry-After": "1"}, json={"error": "slow down"})
        log.append((client_id, page, 200))
        items = apps if apps is not None and page == 1 else [
            {"app_id": f"app-{page}-{i}", "app_name": f"App {page}-{i}", "risk_score": risk,
             "users": 1, "raw_notes": "ok"}
            for i in range(per_page)
        ]
        return httpx.Response(200, json={"items": items, "next_cursor": f"p{page + 1}" if page < n_pages else None})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    http.log = log  # type: ignore[attr-defined]
    return http


def collector_for(db, fake_sleep, make_http, clients=None, **settings) -> Collector:
    return Collector(db, Settings(**settings), http_factory=lambda mode: make_http(), sleep=fake_sleep,
                     clients=clients or {"acme": ACME})


# ---------------------------------------------------------------- 1. N pages

@pytest.mark.parametrize("n", [1, 2, 3, 5, 10])
async def test_reads_all_n_pages_in_order(n, fake_sleep):
    http = paged_api(n)
    pages = [p async for p in APIClient(http, sleep=fake_sleep).iter_pages("acme")]

    assert [p.number for p in pages] == list(range(1, n + 1))
    ids = [i["app_id"] for p in pages for i in p.items]
    assert len(ids) == len(set(ids)) == n * 2          # every item once, none lost, none repeated
    assert [page for _, page, _ in http.log] == list(range(1, n + 1))  # one request per page, then stop


async def test_ten_pages_end_to_end_saves_every_row(db, fake_sleep):
    run = await collector_for(db, fake_sleep, lambda: paged_api(10, per_page=3)).run(Mode.MOCK)

    assert run.status == "completed"
    assert run.clients["acme"].pages == 10
    assert db.count_records() == 30


async def test_empty_page_in_the_middle_still_follows_cursor(fake_sleep):
    pages = {None: {"items": [{"app_id": "a"}], "next_cursor": "p2"},
             "p2": {"items": [], "next_cursor": "p3"},
             "p3": {"items": [{"app_id": "b"}], "next_cursor": None}}
    http = httpx.AsyncClient(base_url="http://x", transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json=pages[r.url.params.get("cursor")])))

    got = [p async for p in APIClient(http, sleep=fake_sleep).iter_pages("acme")]
    assert [len(p.items) for p in got] == [1, 0, 1]


# ---------------------------------------------------------------- 2. repeated 429

@pytest.mark.parametrize("fails", [1, 2, 3, 4, 5])
async def test_429_several_times_then_200(fails, fake_sleep):
    http = paged_api(1, fail_first=fails)
    pages = [p async for p in APIClient(http, max_retries=5, sleep=fake_sleep).iter_pages("acme")]

    assert pages[0].attempts == fails + 1
    assert fake_sleep.calls == [1.0] * fails           # waited exactly Retry-After (1 s) each time
    assert [s for _, _, s in http.log] == [429] * fails + [200]


async def test_too_many_429s_gives_up_after_retry_budget(fake_sleep):
    http = paged_api(1, fail_first=5)
    with pytest.raises(UpstreamError, match="429 persisted after 4 attempts"):
        [p async for p in APIClient(http, max_retries=3, sleep=fake_sleep).iter_pages("acme")]
    assert fake_sleep.calls == [1.0, 1.0, 1.0]          # 1 try + 3 retries, no endless loop


async def test_repeated_429_on_every_page_end_to_end(db, fake_sleep):
    run = await collector_for(db, fake_sleep, lambda: paged_api(3, fail_first=4), max_retries=5).run(Mode.MOCK)

    assert run.status == "completed"
    assert run.clients["acme"].retries == 12            # 4 retries x 3 pages
    assert db.count_records() == 6


async def test_one_client_stuck_on_429_does_not_block_the_other(db, fake_sleep):
    collector = collector_for(db, fake_sleep, lambda: paged_api(2, always_429_for="acme"),
                              clients={"acme": ACME, "vontier": VONTIER})
    run = await collector.run(Mode.MOCK)

    assert run.status == "partial"
    assert run.clients["acme"].status == "failed"
    assert run.clients["vontier"].status == "completed"
    assert db.count_records("acme") == 0
    assert db.count_records("vontier") == 4


# ---------------------------------------------------------------- 3. unknown / new apps

@pytest.mark.parametrize("name", ["ZetaMind AI", "Qx-7 Copilot Pro", "ChatGPT Plus", "🤖 BotX", "Claude 4"])
def test_unknown_app_is_unsanctioned_for_every_client(name):
    for client in (ACME, VONTIER):
        rec = normalize_record({"app_id": "new-app", "app_name": name}, client)
        assert rec.values["classification"] == "unsanctioned"


@pytest.mark.parametrize("name", ["ChatGPT", "chatgpt", "  CHATGPT  ", "chatGPT\n"])
def test_name_match_ignores_case_and_spaces_only(name):
    assert ACME.classify(name) == "sanctioned"


async def test_unknown_app_is_stored_not_rejected(db, fake_sleep):
    apps = [{"app_id": "zetamind", "app_name": "ZetaMind AI", "risk_score": 55, "users": 3}]
    run = await collector_for(db, fake_sleep, lambda: paged_api(1, apps=apps),
                              clients={"acme": ACME, "vontier": VONTIER}).run(Mode.MOCK)

    assert run.summary["totals"]["rejected"] == 0
    assert {(r["client_id"], r["classification"]) for r in db.list_records()} == {
        ("acme", "unsanctioned"), ("vontier", "unsanctioned")}


# ---------------------------------------------------------------- 4. risk_score and emojis

@pytest.mark.parametrize("raw, expected", [
    (None, None),          # missing
    (50, 50),
    ("75", 75),            # number sent as text
    (75.9, 75),            # decimals dropped
    (-5, 0),               # clamped into 0..100
    (150, 100),
    ("🔥", None),          # emoji
    ("high", None),        # words
    ("", None),
    ("NaN", None),
    ("inf", None),         # used to crash with OverflowError
    (True, None),          # booleans are not scores
    ([1], None),
    ({"score": 1}, None),
])
def test_risk_score_values(raw, expected):
    assert parse_risk_score(raw) == expected


def test_emojis_in_notes_are_kept():
    assert sanitize_notes("Great tool 🚀🔥\x07  fast") == ("Great tool 🚀🔥 fast", False)


def test_650_emojis_are_cut_to_500_characters():
    text, truncated = sanitize_notes("🚀" * 650)
    assert truncated and text == "🚀" * 500
    text.encode("utf-8")  # no broken half-character


async def test_emojis_survive_the_database_round_trip(db):
    db.upsert_records([{"client_id": "acme", "app_id": "bot", "app_name": "🤖 BotX",
                        "classification": "unsanctioned", "risk_score": None, "users": 1,
                        "raw_notes": "Ünïcødé 中文 🚀", "notes_truncated": False}])
    [row] = db.list_records()
    assert (row["app_name"], row["raw_notes"], row["risk_score"]) == ("🤖 BotX", "Ünïcødé 中文 🚀", None)


# ---------------------------------------------------------------- 5. second run, checked row by row

def snapshot(db) -> dict:
    with db.Session() as s:
        return {(r.client_id, r.app_id): (r.id, r.app_name, r.classification, r.risk_score, r.users,
                                          r.raw_notes, r.notes_truncated, r.created_at)
                for r in s.scalars(select(AppUsageRecord))}


async def test_second_run_leaves_every_record_identical(make_collector, db):
    collector = make_collector()
    await collector.run(Mode.MOCK)
    first = snapshot(db)
    await collector.run(Mode.MOCK)
    second = snapshot(db)

    assert second == first                               # same ids, same values, same created_at
    with db.Session() as s:
        dupes = s.execute(select(AppUsageRecord.client_id, AppUsageRecord.app_id)
                          .group_by(AppUsageRecord.client_id, AppUsageRecord.app_id)
                          .having(func.count() > 1)).all()
        times = set(s.scalars(select(AppUsageRecord.times_collected)))
    assert dupes == []
    assert times == {2}


async def test_changed_value_updates_the_same_row(db, fake_sleep):
    await collector_for(db, fake_sleep, lambda: paged_api(1, risk=10)).run(Mode.MOCK)
    before = snapshot(db)
    await collector_for(db, fake_sleep, lambda: paged_api(1, risk=90)).run(Mode.MOCK)
    after = snapshot(db)

    assert after.keys() == before.keys()
    for key in before:
        assert after[key][0] == before[key][0]          # same primary key: updated in place
        assert (before[key][3], after[key][3]) == (10, 90)
