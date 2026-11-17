"""Unit tests for src.data.cleaning parsers and rules (owner: M1)."""
from datetime import date, datetime
from decimal import Decimal

import pandas as pd
import pytest

from src.data import cleaning as cl
from src.data.change_log import ChangeLog

WEEKS = (date(2026, 10, 30), date(2026, 11, 6), date(2026, 11, 13))


@pytest.mark.parametrize("raw, expected", [
    (1800, 1800), (1800.0, 1800), ("12,000 seats", 12000), (" 400 ", 400),
    (None, None), (float("nan"), None), ("", None), ("n/a", None), (-5, None), (1.5, None), (True, None),
])
def test_parse_count(raw, expected) -> None:
    assert cl.parse_count(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("$40,583,740", Decimal("40583740")), (14986.72, Decimal("14986.72")), ("4541847645", Decimal("4541847645")),
    ("abc", None), (None, None), ("", None),
])
def test_parse_decimal(raw, expected) -> None:
    assert cl.parse_decimal(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    (datetime(2022, 9, 30), date(2022, 9, 30)),
    (pd.Timestamp("2021-06-15"), date(2021, 6, 15)),
    ("31-Oct-2021", date(2021, 10, 31)),
    ("2062-10-24", date(2062, 10, 24)),
    ("15/01/2015", date(2015, 1, 15)),        # day first
    ("Nov 06, 2026", date(2026, 11, 6)),
    ("2022-09-30 00:00:00", date(2022, 9, 30)),
    ("not a date", None), (None, None),
])
def test_parse_date(raw, expected) -> None:
    assert cl.parse_date(raw) == expected


def test_parse_week_resolves_ambiguous_slash_by_week_sequence() -> None:
    assert cl.parse_week("06/11/2026", WEEKS) == date(2026, 11, 6)
    assert cl.parse_week("30/10/2026", WEEKS) == date(2026, 10, 30)
    assert cl.parse_week("2026-10-23", WEEKS) == date(2026, 10, 23)  # parsed, filtered later


@pytest.mark.parametrize("start, months", [
    (date(2021, 10, 31), 60), (date(2020, 5, 30), 77), (date(2019, 1, 1), 94),
    (date(2015, 1, 15), 141), (date(2026, 11, 13), 0),
])
def test_months_between(start, months) -> None:
    assert cl.months_between(start, date(2026, 11, 13)) == months


def test_months_between_rejects_future_start() -> None:
    with pytest.raises(ValueError):
        cl.months_between(date(2062, 10, 24), date(2026, 11, 13))


@pytest.mark.parametrize("raw, expected", [
    ("5-000002148", "005-000002148"), ("005-000002148", "005-000002148"),
    (" AIUCI-2024::StateChat ", "AIUCI-2024::StateChat"), (None, ""),
])
def test_normalise_source_ref(raw, expected) -> None:
    assert cl.normalise_source_ref(raw) == expected


def test_short_name_from_charter() -> None:
    assert cl.short_name_from_charter("NIM-09_DHS_GenAI_Chat_charter.pdf") == "DHS GenAI Chat"
    assert cl.short_name_from_charter("random.pdf") == ""


@pytest.mark.parametrize("unit, value, expected", [
    ("USD", "10", Decimal("10")), ("USD thousands", "14986.72", Decimal("14986720")),
    ("USD millions", "1.5", Decimal("1500000")), ("INR", "84", Decimal("1")), ("EUR", "1", None),
])
def test_benefit_to_usd(unit, value, expected) -> None:
    assert cl.benefit_to_usd(Decimal(value), unit, {"INR": Decimal(84)}) == expected


def test_read_fx_rates_and_rejects_bad_note() -> None:
    fx = pd.DataFrame({"item": ["FX rate", "Cost units"], "value": [84, "$M"],
                       "note": ["1 USD = 84.0 INR (fixed)", "costs in $M"]})
    assert cl.read_fx_rates(fx) == {"INR": Decimal(84)}
    with pytest.raises(ValueError):
        cl.read_fx_rates(pd.DataFrame({"item": ["FX rate"], "value": [84], "note": ["eighty-four"]}))


def test_clean_go_live_replaces_future_date_with_fallback() -> None:
    log = ChangeLog()
    got = cl.clean_go_live("2062-10-24", "NIM-09", date(2026, 11, 13), date(2023, 10, 24), log)
    assert got == date(2023, 10, 24)
    assert [e.rule for e in log.entries] == ["FUTURE_GO_LIVE_REPLACED"]


def test_clean_go_live_without_fallback_excludes() -> None:
    log = ChangeLog()
    assert cl.clean_go_live("2062-10-24", "X", date(2026, 11, 13), None, log) is None
    assert log.entries[-1].rule == "FUTURE_GO_LIVE_NO_FALLBACK"


def _costs(rows: list[tuple]) -> pd.DataFrame:
    cols = ["currentUII", "projectId", "projectStatus", "plannedStartDate", "actualStartDate",
            "plannedEndDate", "actualEndDate", "actualCost ($M)"]
    return pd.DataFrame(rows, columns=cols)


def test_clean_costs_drops_x1000_twin_and_converts_to_usd() -> None:
    d = "2022-02-28"
    costs = _costs([
        ("9-1", "A", "Completed", d, d, "2023-02-27", "2023-02-27", 22.162494),
        ("009-1", "B", "Completed", d, d, "2023-02-27", "2023-02-27", 22162.494),
        ("009-1", "C", "In Progress", d, d, "2024-01-01", None, None),
        ("999-9", "D", "Completed", d, d, d, d, 1.0),
    ])
    log = ChangeLog()
    totals = cl.clean_costs(costs, {"009-1": "NIM-04"}, log)
    assert totals == {"NIM-04": Decimal("22162494.000000")}
    rules = [e.rule for e in log.entries]
    assert "DROP_X1000_UNIT_ERROR_DUPLICATE" in rules and "UNMAPPED_COST_ROW" in rules


def test_clean_costs_requires_columns() -> None:
    with pytest.raises(ValueError, match="missing columns"):
        cl.clean_costs(pd.DataFrame({"x": [1]}), {}, ChangeLog())


def _benefits(rows: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["initiative_id", "metric", "value", "unit", "basis", "as_of"])


def test_clean_benefits_handles_basis_units_and_stale_rows() -> None:
    df = _benefits([
        ("A", "realised_benefit_to_date", 100, "USD", "cumulative to date", "2026-08-31"),
        ("A", "realised_benefit_to_date", 200, "USD", "cumulative to date", "2026-11-13"),
        ("A", "planned_benefit_per_month", 10, "USD", "plan, per month", "charter baseline"),
        ("B", "avg_monthly_benefit", "$1,000", "USD", "average per month since go-live", "2026-11-13"),
        ("B", "planned_annual_benefit", 168, "INR", "plan, per year", "charter baseline"),
        ("C", "odd", 1, "USD", "something else", "2026-11-13"),
    ])
    log = ChangeLog()
    out = cl.clean_benefits(df, {"INR": Decimal(84)}, {"B": 12}, log)
    assert out["A"].realised_to_date == Decimal(200) and out["A"].planned_annual == Decimal(120)
    assert out["B"].realised_to_date == Decimal(12000) and out["B"].planned_annual == Decimal(2)
    assert out["C"].realised_to_date is None
    rules = {e.rule for e in log.entries}
    assert {"DROP_STALE_DUPLICATE", "MONTHLY_PLAN_TO_ANNUAL", "MONTHLY_AVERAGE_TO_CUMULATIVE",
            "PARSE_MONEY_TEXT", "CONVERT_INR_TO_USD", "UNKNOWN_BASIS"} <= rules


def _usage(rows: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["initiative_ref", "week_ending", "metric_name", "value", "unit"])


def test_clean_usage_normalises_refs_metrics_units_dates_and_signs() -> None:
    df = _usage([
        ("5-1", "2026-10-30", "weekly_active_users", "10", "users"),
        ("5-1", "Nov 06, 2026", "WAU", "-20", "users"),
        ("5-1", "13/11/2026", "Active Users (7-day)", "30", "users"),
        ("5-1", "13/11/2026", "Active Users (7-day)", "30", "users"),     # exact duplicate
        ("5-1", "2026-10-23", "WAU", "99", "users"),                      # outside window
        ("NIM-02", "2026-10-30", "adoption_pct_of_licensed", "52.0", "% of licensed"),
        ("NIM-02", "2026-11-06", "adoption_pct_of_licensed", "50.0", "% of licensed"),
        ("NIM-02", "2026-11-13", "adoption_pct_of_licensed", "47.2", "% of licensed"),
        ("NIM-03", "2026-10-30", "WAU", "5", "users"),                    # incomplete weeks
        ("777-1", "2026-10-30", "WAU", "5", "users"),                     # unmapped
    ])
    log = ChangeLog()
    out = cl.clean_usage(df, {"005-1": "NIM-01"}, {"NIM-02": 2500}, WEEKS, log)
    assert out == {"NIM-01": [10, 20, 30], "NIM-02": [1300, 1250, 1180]}
    rules = {e.rule for e in log.entries}
    assert {"DROP_EXACT_DUPLICATE_ROW", "MAP_SOURCE_REF_TO_INITIATIVE_ID", "RENAME_METRIC",
            "NEGATIVE_WAU_SIGN_ERROR", "DROP_WEEK_OUTSIDE_REPORTING_PERIOD", "PERCENT_OF_LICENSED_TO_USERS",
            "RESOLVE_SLASH_DATE_BY_WEEK_SEQUENCE", "PARSE_TEXT_DATE", "UNMAPPED_USAGE_REF"} <= rules
