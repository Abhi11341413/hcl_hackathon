"""Tests for src.scorecard.store: SQLite round trip and 5a lookup (owner: M1)."""
import sqlite3
from datetime import date

import pandas as pd
import pytest

from src.contracts import METRIC_NAMES, InitiativeRecord
from src.scorecard import store
from src.scorecard.engine import compute_scorecard


@pytest.fixture(scope="module")
def rows():
    from src import config
    df = pd.read_csv(config.TRUTH_DIR / "expected_clean_inputs.csv", dtype=str, keep_default_na=False)
    return compute_scorecard([InitiativeRecord(**r) for r in df.to_dict("records")])


@pytest.fixture
def db(tmp_path, rows):
    path = tmp_path / "runtime" / "scorecard.db"
    store.save_scorecard(rows, path)
    return path


def _undefined_row():
    rec = InitiativeRecord(initiative_id="NIM-99", initiative_name="Zero", go_live_date=date(2026, 11, 13),
                           months_live=0, licensed_users=0, wau_week1=0, wau_week2=0, wau_week3=0,
                           total_cost_to_date_usd=0.0, realised_benefit_to_date_usd=0.0,
                           planned_annual_benefit_usd=0.0)
    return compute_scorecard([rec])[0]


def test_round_trip_is_exact(db, rows) -> None:
    assert store.load_scorecard(db) == rows


def test_save_replaces_previous_rows(db, rows) -> None:
    store.save_scorecard(rows[:3], db)
    assert [r.initiative_id for r in store.load_scorecard(db)] == [r.initiative_id for r in rows[:3]]


def test_undefined_metrics_survive_as_none(tmp_path) -> None:
    path = tmp_path / "s.db"
    row = _undefined_row()
    store.save_scorecard([row], path)
    (loaded,) = store.load_scorecard(path)
    assert loaded == row and loaded.roi is None


def test_load_missing_db_or_table_returns_empty(tmp_path) -> None:
    assert store.load_scorecard(tmp_path / "absent.db") == []
    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()
    assert store.load_scorecard(empty) == []


def test_save_rejects_duplicate_ids(tmp_path, rows) -> None:
    with pytest.raises(ValueError):
        store.save_scorecard([rows[0], rows[0]], tmp_path / "d.db")


def test_lookup_specific_values(db, rows) -> None:
    evidence = store.lookup(["NIM-05"], ["roi", "status"], db)
    assert [e.evidence_id for e in evidence] == ["scorecard:NIM-05:roi", "scorecard:NIM-05:status"]
    roi, status = evidence
    expected = next(r for r in rows if r.initiative_id == "NIM-05")
    assert roi.kind == "scorecard" and roi.value == expected.roi and roi.metric == "roi"
    assert "-22.0%" in roi.text and roi.source_file == store.SOURCE_FILE
    assert status.value == "Red" and "Red" in status.text


def test_lookup_empty_filters_mean_all(db, rows) -> None:
    assert len(store.lookup([], [], db)) == len(rows) * len(METRIC_NAMES)


def test_lookup_normalises_and_ignores_unknowns(db) -> None:
    evidence = store.lookup([" nim-01 ", "NIM-77"], ["ROI", "made_up", "roi"], db)
    assert [e.evidence_id for e in evidence] == ["scorecard:NIM-01:roi"]


def test_lookup_only_unknown_metrics_returns_nothing(db) -> None:
    assert store.lookup(["NIM-01"], ["made_up"], db) == []


def test_lookup_on_missing_db_returns_nothing(tmp_path) -> None:
    assert store.lookup(["NIM-01"], [], tmp_path / "none.db") == []


def test_evidence_ids_are_unique(db) -> None:
    ids = [e.evidence_id for e in store.lookup([], [], db)]
    assert len(ids) == len(set(ids))


def test_undefined_value_text(tmp_path) -> None:
    path = tmp_path / "u.db"
    store.save_scorecard([_undefined_row()], path)
    (ev,) = store.lookup(["NIM-99"], ["payback_months"], path)
    assert ev.value is None and "undefined" in ev.text


@pytest.mark.parametrize("metric, value, expected", [
    ("adoption", 0.6888888889, "68.9%"), ("roi", 0.0, "0.0%"), ("avg_monthly_benefit", 352417.5, "$352,417.50"),
    ("payback_months", 44.44, "44.44 months"), ("status", "Green", "Green"),
])
def test_format_metric(metric, value, expected) -> None:
    assert store.format_metric(metric, value) == expected


def test_format_metric_unknown_raises() -> None:
    with pytest.raises(ValueError):
        store.format_metric("nope", 1.0)


def test_evidence_id_format() -> None:
    assert store.scorecard_evidence_id("NIM-05", "run_rate_vs_plan") == "scorecard:NIM-05:run_rate_vs_plan"
    kind, initiative_id, metric = "scorecard:NIM-05:run_rate_vs_plan".split(":")
    assert (kind, initiative_id, metric) == ("scorecard", "NIM-05", "run_rate_vs_plan")


def test_all_lookup_ids_use_scorecard_prefix(db) -> None:
    for ev in store.lookup([], [], db):
        assert ev.evidence_id == f"scorecard:{ev.initiative_id}:{ev.metric}"
