"""HLD 2: deterministic scorecard engine (seven metrics + status). No LLM.

Owner: M1 (see CLAUDE.md). Public functions here are listed in CLAUDE.md section 5.

Formulas (problem statement 2b, section 4); ratios are plain fractions (0.6 == 60%):
- adoption            = WAU week 3 / licensed users
- wau_change          = (WAU week 3 - WAU week 1) / WAU week 1
- roi                 = (realised benefit to date - total cost to date) / total cost to date
- avg_monthly_benefit = realised benefit to date / months live                   (USD, 2 dp)
- payback_months      = total cost to date / avg monthly benefit                 (2 dp)
- run_rate_vs_plan    = avg monthly benefit x 12 / planned annual benefit
Payback and run-rate use the unrounded monthly average. Ratios are rounded to config.RATIO_DECIMALS. A metric whose denominator is zero (or whose
payback would be negative or infinite) is None and is reported as undefined, never guessed.
"""
from __future__ import annotations

import logging

from src.contracts import InitiativeRecord, ScorecardRow
from src.scorecard.status import portfolio_status, round_ratio

logger = logging.getLogger(__name__)

MONEY_DECIMALS = 2
PAYBACK_DECIMALS = 2


def compute_scorecard(records: list[InitiativeRecord]) -> list[ScorecardRow]:
    """Compute adoption, WAU change, ROI, avg monthly benefit, payback, run-rate vs plan
    and status for every record, using the formulas in problem statement 2b section 4."""
    if not records:
        logger.warning("compute_scorecard called with no records")
        return []
    ids = [r.initiative_id for r in records]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"duplicate initiative IDs in records: {duplicates}")
    rows = [score_record(record) for record in sorted(records, key=lambda r: r.initiative_id)]
    logger.info("scorecard: %d rows (%s)", len(rows),
                ", ".join(f"{s}={sum(r.status == s for r in rows)}" for s in ("Green", "Amber", "Red")))
    return rows


def score_record(record: InitiativeRecord) -> ScorecardRow:
    """Compute all seven metrics for one initiative."""
    adoption = adoption_rate(record.wau_week3, record.licensed_users)
    roi = return_on_investment(record.realised_benefit_to_date_usd, record.total_cost_to_date_usd)
    # Derived metrics use the unrounded monthly average; only the displayed value is rounded.
    raw_monthly = _monthly_benefit(record.realised_benefit_to_date_usd, record.months_live)
    return ScorecardRow(
        initiative_id=record.initiative_id,
        initiative_name=record.initiative_name,
        short_name=record.short_name,
        adoption=adoption,
        wau_change=wau_change(record.wau_week1, record.wau_week3),
        roi=roi,
        avg_monthly_benefit=average_monthly_benefit(record.realised_benefit_to_date_usd, record.months_live),
        payback_months=payback_months(record.total_cost_to_date_usd, raw_monthly),
        run_rate_vs_plan=run_rate_vs_plan(raw_monthly, record.planned_annual_benefit_usd),
        status=portfolio_status(adoption, roi),
        inputs=record,
    )


def adoption_rate(wau_latest: int, licensed_users: int) -> float | None:
    """Latest-week WAU as a fraction of licensed users; None when there are no licences."""
    return _ratio(wau_latest, licensed_users)


def wau_change(wau_first: int, wau_latest: int) -> float | None:
    """Relative change in WAU from the first to the latest reporting week; None if week 1 is 0."""
    return _ratio(wau_latest - wau_first, wau_first)


def return_on_investment(benefit_usd: float, cost_usd: float) -> float | None:
    """(benefit - cost) / cost; None when cost is 0."""
    return _ratio(benefit_usd - cost_usd, cost_usd)


def average_monthly_benefit(benefit_usd: float, months_live: int) -> float | None:
    """Realised benefit per month live (USD, 2 dp); None when months live is 0."""
    raw = _monthly_benefit(benefit_usd, months_live)
    return None if raw is None else round(raw, MONEY_DECIMALS)


def payback_months(cost_usd: float, avg_monthly_benefit_usd: float | None) -> float | None:
    """Months of average benefit needed to repay cost (2 dp); None when monthly benefit <= 0."""
    if avg_monthly_benefit_usd is None or avg_monthly_benefit_usd <= 0:
        return None
    return round(cost_usd / avg_monthly_benefit_usd, PAYBACK_DECIMALS)


def run_rate_vs_plan(avg_monthly_benefit_usd: float | None, planned_annual_usd: float) -> float | None:
    """Annualised current benefit (avg monthly x 12) as a fraction of the annual plan."""
    if avg_monthly_benefit_usd is None:
        return None
    return _ratio(avg_monthly_benefit_usd * 12, planned_annual_usd)


def _monthly_benefit(benefit_usd: float, months_live: int) -> float | None:
    """Unrounded realised benefit per month live; None when months live is 0."""
    return None if months_live <= 0 else benefit_usd / months_live


def _ratio(numerator: float, denominator: float) -> float | None:
    """numerator / denominator rounded to RATIO_DECIMALS, or None when the denominator is 0."""
    if denominator == 0:
        return None
    return round_ratio(numerator / denominator)
