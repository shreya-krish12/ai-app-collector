"""Configuration tab: default rules, changing them, and the next run using them."""

import copy

import pytest
from fastapi.testclient import TestClient

from api_server import create_app
from app_collector.config import Mode
from app_collector.rules import DEFAULT_RULES, InvalidRules, RuleStore, validate


def changed(**kw) -> dict:
    rules = copy.deepcopy(DEFAULT_RULES)
    rules.update(kw)
    return rules


def by_app(records):
    return {r["app_id"]: r for r in records}


# ---------------------------------------------------------------- defaults

def test_defaults_match_the_assignment():
    store = RuleStore()
    assert store.get() == {
        "sanctioned_apps": {"acme": ["ChatGPT", "GitHub Copilot"],
                            "vontier": ["Claude", "Gemini", "GitHub Copilot"]},
        "missing_risk": "null",
        "max_notes_length": 500,
    }
    assert store.is_default()


async def test_default_run_is_unchanged(make_collector, db):
    await make_collector().run(Mode.MOCK)
    otter = by_app(db.list_records("acme"))["otter"]
    assert otter["risk_score"] is None and len(otter["raw_notes"]) == 500


# ---------------------------------------------------------------- changes apply on the next run

async def test_new_sanctioned_list_reclassifies_on_next_run(make_collector, db):
    collector = make_collector()
    await collector.run(Mode.MOCK)
    assert by_app(db.list_records("acme"))["claude"]["classification"] == "unsanctioned"

    collector.rules.update(changed(sanctioned_apps={"acme": ["ChatGPT", "GitHub Copilot", "Claude"],
                                                    "vontier": ["Claude", "Gemini", "GitHub Copilot"]}))
    await collector.run(Mode.MOCK)

    acme = by_app(db.list_records("acme"))
    assert acme["claude"]["classification"] == "sanctioned"       # same row, updated
    assert acme["claude"]["times_collected"] == 2
    assert by_app(db.list_records("vontier"))["chatgpt"]["classification"] == "unsanctioned"  # other client untouched


async def test_worst_case_policy_stores_100_for_missing_risk(make_collector, db):
    collector = make_collector()
    collector.rules.update(changed(missing_risk="worst_case"))
    run = await collector.run(Mode.MOCK)

    assert by_app(db.list_records("acme"))["otter"]["risk_score"] == 100
    assert run.summary["totals"]["missing_risk"] == 2   # still counted as missing


async def test_shorter_notes_length_is_used(make_collector, db):
    collector = make_collector()
    collector.rules.update(changed(max_notes_length=200))
    await collector.run(Mode.MOCK)

    rows = db.list_records()
    assert all(len(r["raw_notes"] or "") <= 200 for r in rows)
    assert by_app(db.list_records("acme"))["otter"]["notes_truncated"]


# ---------------------------------------------------------------- validation

@pytest.mark.parametrize("bad, message", [
    (changed(max_notes_length=501), "1 to 500"),      # requirement says <= 500
    (changed(max_notes_length=0), "1 to 500"),
    (changed(max_notes_length="300"), "1 to 500"),
    (changed(missing_risk="zero"), "missing_risk"),   # 0 is not offered: unknown is not safe
    (changed(sanctioned_apps={"globex": ["X"]}), "unknown client_id"),
    (changed(sanctioned_apps={"acme": ["  "], "vontier": []}), "empty name"),
    (changed(sanctioned_apps={"acme": "ChatGPT", "vontier": []}), "list of names"),
])
def test_bad_rules_are_rejected(bad, message):
    with pytest.raises(InvalidRules, match=message):
        validate(bad)


def test_names_are_trimmed_and_duplicates_merged():
    clean = validate(changed(sanctioned_apps={"acme": [" ChatGPT ", "chatgpt", "Git  Hub"], "vontier": []}))
    assert clean["sanctioned_apps"]["acme"] == ["ChatGPT", "Git Hub"]


def test_an_empty_list_is_allowed():
    assert validate(changed(sanctioned_apps={"acme": [], "vontier": []}))["sanctioned_apps"]["acme"] == []


# ---------------------------------------------------------------- saving

def test_rules_are_saved_and_loaded_again(tmp_path):
    path = tmp_path / "rules.json"
    RuleStore(path).update(changed(max_notes_length=300))
    assert RuleStore(path).get()["max_notes_length"] == 300


def test_broken_file_falls_back_to_defaults(tmp_path):
    path = tmp_path / "rules.json"
    path.write_text("{not json", encoding="utf-8")
    assert RuleStore(path).is_default()


def test_reset_restores_defaults_and_removes_file(tmp_path):
    path = tmp_path / "rules.json"
    store = RuleStore(path)
    store.update(changed(missing_risk="worst_case"))
    store.reset()
    assert store.is_default() and not path.exists()


# ---------------------------------------------------------------- HTTP API

def test_rules_api(db, make_collector):
    with TestClient(create_app(db=db, collector=make_collector())) as api:
        assert api.get("/api/rules").json()["is_default"] is True

        res = api.put("/api/rules", json=changed(max_notes_length=250))
        assert res.status_code == 200 and res.json()["rules"]["max_notes_length"] == 250
        assert res.json()["is_default"] is False

        assert api.put("/api/rules", json=changed(max_notes_length=900)).status_code == 400

        new_list = changed(sanctioned_apps={"acme": ["Midjourney"], "vontier": []})
        api.put("/api/rules", json=new_list)
        acme = next(c for c in api.get("/api/mock-data").json()["clients"] if c["client_id"] == "acme")
        assert acme["sanctioned_apps"] == ["Midjourney"]   # Mock API page shows the current list

        assert api.post("/api/rules/reset").json()["is_default"] is True
