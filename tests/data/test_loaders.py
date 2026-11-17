"""End-to-end tests for load_and_clean against the answer key in data/truth (owner: M1)."""
import json
import shutil

import pandas as pd
import pytest

from src.data.loaders import load_and_clean


@pytest.fixture(scope="module")
def result():
    from src import config
    return load_and_clean(config.SEED_DIR)


def test_records_match_expected_clean_inputs(result, truth_dir) -> None:
    expected = pd.read_csv(truth_dir / "expected_clean_inputs.csv", dtype=str)
    got = pd.DataFrame([r.model_dump(mode="json") for r in result.records])[expected.columns]
    assert list(got["initiative_id"]) == list(expected["initiative_id"])
    for col in expected.columns:
        if col.endswith("_usd"):
            assert (got[col].astype(float) - expected[col].astype(float)).abs().max() < 0.005, col
        else:
            assert list(got[col].astype(str)) == list(expected[col]), col


# Planted spreadsheet issues -> rule our cleaner must log for that initiative.
# (KPI and charter issues belong to other steps and are not checked here.)
EXPECTED_RULES = {
    "REAL-COST-NIM-04": "DROP_X1000_UNIT_ERROR_DUPLICATE",
    "PL-REG-01": "STRIP_NON_DIGITS",
    "PL-REG-02": "FUTURE_GO_LIVE_REPLACED",
    "PL-REG-03": "PARSE_DAY_FIRST_DATE",
    "PL-REG-04": "TRIM_WHITESPACE",
    "PL-REG-05": "PARSE_TEXT_DATE",
    "PL-REG-06": "DROP_EXACT_DUPLICATE_ROW",
    "PL-USE-01": "RENAME_METRIC",
    "PL-USE-02": "MAP_SOURCE_REF_TO_INITIATIVE_ID",
    "PL-USE-03": "PERCENT_OF_LICENSED_TO_USERS",
    "PL-USE-04": "DROP_EXACT_DUPLICATE_ROW",
    "PL-USE-05": "RESOLVE_SLASH_DATE_BY_WEEK_SEQUENCE",
    "PL-USE-06": "NEGATIVE_WAU_SIGN_ERROR",
    "PL-USE-07": "DROP_WEEK_OUTSIDE_REPORTING_PERIOD",
    "PL-FIN-01": "JOIN_COSTS_VIA_SOURCE_REF",
    "PL-FIN-02": "CONVERT_USD_MILLIONS_TO_USD",
    "PL-FIN-03": "CONVERT_USD_THOUSANDS_TO_USD",
    "PL-FIN-04": "PARSE_MONEY_TEXT",
    "PL-FIN-05": "MONTHLY_AVERAGE_TO_CUMULATIVE",
    "PL-FIN-06": "CONVERT_INR_TO_USD",
    "PL-FIN-07": "MONTHLY_PLAN_TO_ANNUAL",
    "PL-FIN-08": "CONVERT_USD_MILLIONS_TO_USD",
    "PL-FIN-09": "DROP_STALE_DUPLICATE",
}


def test_every_planted_spreadsheet_issue_is_logged(result, truth_dir) -> None:
    issues = {i["id"]: i for i in json.loads((truth_dir / "planted_issues.json").read_text(encoding="utf-8"))}
    logged = {(e.rule, e.initiative_id, e.file) for e in result.change_log}
    missing = []
    for issue_id, rule in EXPECTED_RULES.items():
        issue = issues[issue_id]
        ids = [i for i in issue["initiative_id"].split(",") if i.startswith("NIM-")]
        hit = any(r == rule and f == issue["file"].strip() and (i in ids or not ids)
                  for r, i, f in logged) if ids else any(r == rule for r, _, _ in logged)
        if not hit:
            missing.append(issue_id)
    assert missing == []


def test_change_log_ids_are_unique(result) -> None:
    ids = [e.issue_id for e in result.change_log]
    assert len(ids) == len(set(ids))


def test_missing_seed_dir_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        load_and_clean(tmp_path / "nope")


def test_missing_seed_file_raises(tmp_path, seed_dir) -> None:
    shutil.copy(seed_dir / "portfolio_register.xlsx", tmp_path)
    with pytest.raises(FileNotFoundError, match="usage_weekly.csv"):
        load_and_clean(tmp_path)


def test_initiative_without_usage_is_excluded_and_logged(tmp_path, seed_dir) -> None:
    for name in ("portfolio_register.xlsx", "financials.xlsx"):
        shutil.copy(seed_dir / name, tmp_path)
    usage = pd.read_csv(seed_dir / "usage_weekly.csv", dtype=str)
    usage[usage["initiative_ref"] != "NIM-10"].to_csv(tmp_path / "usage_weekly.csv", index=False)
    res = load_and_clean(tmp_path)
    assert "NIM-10" not in {r.initiative_id for r in res.records}
    assert any(e.rule == "EXCLUDED_INCOMPLETE_INITIATIVE" and e.initiative_id == "NIM-10" for e in res.change_log)
