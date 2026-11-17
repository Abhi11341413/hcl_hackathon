"""Per-initiative insights and as-of-week scorecards for the dashboard and weekly report.

Owner: M4 (see CLAUDE.md). Deterministic, no LLM.

- ``initiative_insights``: plain-language observations for one ScorecardRow. Every figure
  is a ScorecardRow value (or its inputs) or a config threshold, only formatted.
- ``scorecard_as_of_week``: re-scores the portfolio as of an earlier reporting week by
  passing week-truncated InitiativeRecords to M1's public ``compute_scorecard``, so M1
  remains the only code that computes metrics. Financial inputs (cost, benefit, months
  live) are only supplied as at config.REPORT_DATE, so ROI, payback, average monthly
  benefit and run-rate are the same for every week; adoption, WAU change and status vary.
"""
from __future__ import annotations

import logging

from src import config
from src.contracts import InitiativeRecord, ScorecardRow
from src.report.weekly import attention_reasons, format_months, format_pct, format_usd
from src.scorecard.engine import compute_scorecard

logger = logging.getLogger(__name__)

WEEKS: tuple[str, ...] = tuple(config.REPORTING_WEEKS)
LATEST_WEEK: str = WEEKS[-1]


# ------------------------------------------------------------------ week selection
def week_index(week: str) -> int:
    """1-based position of a reporting week; ValueError for an unknown week."""
    if week not in WEEKS:
        raise ValueError(f"unknown reporting week {week!r}; expected one of {WEEKS}")
    return WEEKS.index(week) + 1


def wau_for_week(record: InitiativeRecord, week: str) -> int:
    """Weekly active users recorded for that reporting week."""
    return (record.wau_week1, record.wau_week2, record.wau_week3)[week_index(week) - 1]


def record_as_of_week(record: InitiativeRecord, week: str) -> InitiativeRecord:
    """The record as it stood at the end of ``week``: the selected week becomes the latest
    week (week 3 slot), and weeks after it are dropped. Financial fields are unchanged."""
    n = week_index(week)
    waus = (record.wau_week1, record.wau_week2, record.wau_week3)[:n]
    padded = (waus[0],) * (3 - n) + waus  # keep week 1 as the first observation
    return record.model_copy(update={"wau_week1": padded[0], "wau_week2": padded[1], "wau_week3": padded[2]})


def scorecard_as_of_week(rows: list[ScorecardRow], week: str) -> list[ScorecardRow]:
    """Scorecard rows as of ``week`` (computed by M1 compute_scorecard). The latest week
    returns the governed rows unchanged."""
    if not rows:
        return []
    if week == LATEST_WEEK:
        week_index(week)
        return list(rows)
    records = [record_as_of_week(r.inputs, week) for r in rows]
    logger.info("re-scoring %d initiatives as of week ending %s", len(records), week)
    return compute_scorecard(records)


# ------------------------------------------------------------------ insights
def status_rule_text(row: ScorecardRow) -> str:
    """Which Green/Amber/Red rule produced the status (thresholds from config)."""
    green, red = format_pct(config.GREEN_MIN_ADOPTION), format_pct(config.RED_MAX_ADOPTION)
    if row.status == "Green":
        return f"Green: adoption is at least {green} and ROI is above 0."
    if row.status == "Red":
        return f"Red: adoption is below {red} or ROI is negative."
    return f"Amber: not Red, but adoption is below {green} or ROI is not above 0."


def initiative_insights(row: ScorecardRow) -> list[str]:
    """Plain-language observations for one initiative, strongest signal first."""
    i = row.inputs
    notes: list[str] = [status_rule_text(row)]
    notes += [text for text, _ in attention_reasons(row)]

    if row.adoption is not None and row.adoption >= config.GREEN_MIN_ADOPTION:
        notes.append(f"Adoption {format_pct(row.adoption)} meets the {format_pct(config.GREEN_MIN_ADOPTION)} "
                     f"Green threshold ({i.wau_week3:,} of {i.licensed_users:,} licensed users active in the latest week).")
    if row.wau_change is not None and row.wau_change > 0:
        notes.append(f"Weekly active users grew {format_pct(row.wau_change)} "
                     f"({i.wau_week1:,} to {i.wau_week3:,}).")
    if row.roi is not None and row.roi > config.ROI_ZERO:
        notes.append(f"ROI is {format_pct(row.roi)}: realised benefit {format_usd(i.realised_benefit_to_date_usd)} "
                     f"against cost {format_usd(i.total_cost_to_date_usd)}.")
    if row.run_rate_vs_plan is not None and row.run_rate_vs_plan >= 1:
        notes.append(f"Benefit run-rate is {format_pct(row.run_rate_vs_plan)} of plan, at or ahead of target.")
    if row.payback_months is not None:
        notes.append(f"Payback period is {format_months(row.payback_months)} months at the current average "
                     f"monthly benefit of {format_usd(row.avg_monthly_benefit)}; live for {i.months_live} months.")
    else:
        notes.append("Payback is undefined: the initiative has no positive monthly benefit yet.")
    return _unique(notes)


def _unique(items: list[str]) -> list[str]:
    """Drop repeated sentences, keeping order."""
    seen: set[str] = set()
    return [x for x in items if not (x in seen or seen.add(x))]
