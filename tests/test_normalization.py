"""Normalisation: truncation/sanitising of raw_notes, missing risk_score, validation."""

import pytest

from app_collector.api.upstream import LONG_NOTES
from app_collector.collector.normalizer import InvalidRecord, normalize_record, parse_risk_score, sanitize_notes
from app_collector.config import CLIENTS

ACME = CLIENTS["acme"]


def raw(**overrides):
    return {"app_id": "x", "app_name": "Some App", "users": 5, "risk_score": 40, "raw_notes": "ok", **overrides}


def test_650_char_notes_truncated_to_500():
    assert len(LONG_NOTES) == 650
    record = normalize_record(raw(raw_notes=LONG_NOTES), ACME)
    assert len(record.values["raw_notes"]) == 500
    assert record.values["notes_truncated"] is True


def test_short_notes_untouched():
    assert sanitize_notes("Fine as is.") == ("Fine as is.", False)


def test_control_chars_and_extra_spaces_removed():
    assert sanitize_notes("  one\ttwo\x07three\n\n four  ")[0] == "one two three four"


def test_none_notes_stay_none():
    assert sanitize_notes(None) == (None, False)


def test_null_risk_score_stored_as_null_not_zero():
    record = normalize_record(raw(risk_score=None), ACME)
    assert record.values["risk_score"] is None
    assert record.risk_missing is True


@pytest.mark.parametrize("value, expected", [
    (42, 42), ("57", 57), (61.9, 61), (-5, 0), (250, 100), (None, None), ("high", None), (True, None),
])
def test_risk_score_parsing(value, expected):
    assert parse_risk_score(value) == expected


@pytest.mark.parametrize("bad", [{"app_id": None}, {"app_id": "  "}, {"app_name": ""}, {"app_name": None}])
def test_record_without_id_or_name_is_rejected(bad):
    with pytest.raises(InvalidRecord):
        normalize_record(raw(**bad), ACME)


def test_classification_uses_the_clients_list():
    assert normalize_record(raw(app_name="ChatGPT"), ACME).values["classification"] == "sanctioned"
    assert normalize_record(raw(app_name="Claude"), ACME).values["classification"] == "unsanctioned"
