"""Tests for src.scorecard.engine against data/truth/expected_scorecard.csv (owner: M1)."""
from datetime import date

import pandas as pd
import pytest

from src.contracts import InitiativeRecord
from src.scorecard import engine

TOLERANCE = 1e-9
METRIC_COLUMNS = {  # ScorecardRow field -> expected_scorecard.csv column
    "adoption": "adoption", "wau_change": "wau_change", "roi": "roi",
    "avg_monthly_benefit": "avg_monthly_benefit_usd", "payback_months": "payback_months",
    "run_rate_vs_plan": "run_rate_vs_plan",
}


def _record(**overrides) -> InitiativeRecord:
    base = dict(initiative_id="NIM-99", initiative_name="Test", go_live_date=date(2025, 11, 13), months_live=12,
                licensed_users=100, wau_week1=50, wau_week2=55, wau_week3=60, total_cost_to_date_usd=1_000_000.0,
                realised_benefit_to_date_usd=1_200_000.0, planned_annual_benefit_usd=1_000_000.0)
    base.update(overrides)
    return InitiativeRecord(**base)


@pytest.fixture(scope="module")
def expected(truth_dir_module) -> pd.DataFrame:
    return pd.read_csv(truth_dir_module / "expected_scorecard.csv").set_index("initiative_id")


@pytest.fixture(scope="module")
def truth_dir_module():
    from src import config
    return config.TRUTH_DIR


@pytest.fixture(scope="module")
def truth_records(truth_dir_module) -> list[InitiativeRecord]:
    """Records built straight from the answer key, so engine tests don't depend on the cleaner."""
    df = pd.read_csv(truth_dir_module / "expected_clean_inputs.csv", dtype=str, keep_default_na=False)
    return [InitiativeRecord(**row) for row in df.to_dict("records")]


def test_scorecard_matches_expected(truth_records, expected) -> None:
    rows = engine.compute_scorecard(truth_records)
    assert [r.initiative_id for r in rows] == list(expected.index)
    for row in rows:
        exp = expected.loc[row.initiative_id]
        assert row.status == exp["status"], row.initiative_id
        assert row.short_name == exp["short_name"]
        for field, column in METRIC_COLUMNS.items():
            assert getattr(row, field) == pytest.approx(exp[column], abs=TOLERANCE), (row.initiative_id, field)


def test_end_to_end_from_seed_matches_expected(seed_dir, expected) -> None:
    from src.data.loaders import load_and_clean
    rows = engine.compute_scorecard(load_and_clean(seed_dir).records)
    got = {r.initiative_id: r for r in rows}
    for iid, exp in expected.iterrows():
        assert got[iid].status == exp["status"]
        for field, column in METRIC_COLUMNS.items():
            assert getattr(got[iid], field) == pytest.approx(exp[column], abs=TOLERANCE), (iid, field)


def test_rows_carry_their_inputs() -> None:
    record = _record()
    (row,) = engine.compute_scorecard([record])
    assert row.inputs == record


def test_single_record_formulas() -> None:
    (row,) = engine.compute_scorecard([_record()])
    assert row.adoption == 0.6
    assert row.wau_change == 0.2
    assert row.roi == 0.2
    assert row.avg_monthly_benefit == 100_000.0
    assert row.payback_months == 10.0
    assert row.run_rate_vs_plan == 1.2
    assert row.status == "Green"


def test_undefined_metrics_are_none_not_errors() -> None:
    record = _record(licensed_users=0, wau_week1=0, total_cost_to_date_usd=0.0, months_live=0,
                     planned_annual_benefit_usd=0.0)
    (row,) = engine.compute_scorecard([record])
    assert row.adoption is None and row.wau_change is None and row.roi is None
    assert row.avg_monthly_benefit is None and row.payback_months is None and row.run_rate_vs_plan is None
    assert row.status == "Amber"


def test_negative_benefit_gives_no_payback() -> None:
    (row,) = engine.compute_scorecard([_record(realised_benefit_to_date_usd=-10.0)])
    assert row.payback_months is None and row.roi < 0 and row.status == "Red"


def test_zero_plan_gives_no_run_rate() -> None:
    (row,) = engine.compute_scorecard([_record(planned_annual_benefit_usd=0.0)])
    assert row.run_rate_vs_plan is None


def test_empty_input_returns_empty_list() -> None:
    assert engine.compute_scorecard([]) == []


def test_duplicate_ids_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        engine.compute_scorecard([_record(), _record()])


def test_rows_sorted_by_initiative_id() -> None:
    rows = engine.compute_scorecard([_record(initiative_id="NIM-02"), _record(initiative_id="NIM-01")])
    assert [r.initiative_id for r in rows] == ["NIM-01", "NIM-02"]
