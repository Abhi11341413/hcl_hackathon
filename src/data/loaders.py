"""HLD 1: load the seed spreadsheets and return clean records + change log.

Owner: M1 (see CLAUDE.md). Public functions here are listed in CLAUDE.md section 5.

Pipeline: register (+ go-live fallback from costs) -> costs -> FX -> benefits -> usage
-> one InitiativeRecord per initiative. Every transformation is written to the change log;
an initiative that cannot be completed is excluded and the exclusion is logged too.
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

from src import config
from src.contracts import CleanResult, InitiativeRecord
from src.data import cleaning as cl
from src.data.change_log import AREA_ASSUMPTION, AREA_REGISTER, ChangeLog

logger = logging.getLogger(__name__)

REGISTER_SHEET = "Register"
COSTS_SHEET = "Costs_ITDashboard"
BENEFITS_SHEET = "Benefits"
FX_SHEET = "FX_and_Units"


def load_and_clean(seed_dir: Path) -> CleanResult:
    """Read portfolio_register.xlsx, usage_weekly.csv and financials.xlsx from seed_dir,
    fix data-quality issues, normalise names/units/periods to USD, and log every change."""
    seed_dir = Path(seed_dir)
    _check_inputs(seed_dir)
    report_date = date.fromisoformat(config.REPORT_DATE)
    weeks = tuple(date.fromisoformat(w) for w in config.REPORTING_WEEKS)
    log = ChangeLog()

    costs_raw = _read_sheet(seed_dir / cl.FINANCIALS_FILE, COSTS_SHEET)
    register = cl.clean_register(_read_sheet(seed_dir / cl.REGISTER_FILE, REGISTER_SHEET), report_date,
                                 cl.earliest_completion_dates(costs_raw), log)
    ref_to_id = {row.source_ref: row.initiative_id for row in register if row.source_ref}
    months_live = {row.initiative_id: cl.months_between(row.go_live_date, report_date)
                   for row in register if row.go_live_date is not None}
    licensed = {row.initiative_id: row.licensed_users for row in register if row.licensed_users is not None}

    costs = cl.clean_costs(costs_raw, ref_to_id, log)
    fx_rates = cl.read_fx_rates(_read_sheet(seed_dir / cl.FINANCIALS_FILE, FX_SHEET))
    benefits = cl.clean_benefits(_read_sheet(seed_dir / cl.FINANCIALS_FILE, BENEFITS_SHEET), fx_rates,
                                 months_live, log)
    usage = cl.clean_usage(pd.read_csv(seed_dir / cl.USAGE_FILE, dtype=str, keep_default_na=False),
                           ref_to_id, licensed, weeks, log)

    _log_assumptions(log, report_date, weeks, fx_rates)
    records = [rec for row in register
               if (rec := _build_record(row, months_live, costs, benefits, usage, log)) is not None]
    records.sort(key=lambda r: r.initiative_id)
    logger.info("load_and_clean: %d records, %d change-log entries", len(records), len(log.entries))
    return CleanResult(records=records, change_log=log.entries)


def _check_inputs(seed_dir: Path) -> None:
    """Fail fast with a clear message when the seed folder or a required file is missing."""
    if not seed_dir.is_dir():
        raise FileNotFoundError(f"seed directory not found: {seed_dir}")
    missing = [name for name in (cl.REGISTER_FILE, cl.USAGE_FILE, cl.FINANCIALS_FILE)
               if not (seed_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"missing seed files in {seed_dir}: {missing}")


def _read_sheet(path: Path, sheet: str) -> pd.DataFrame:
    """Read one sheet with raw cell values (no type coercion), raising ValueError if it is absent."""
    try:
        return pd.read_excel(path, sheet_name=sheet, dtype=object)
    except ValueError as exc:
        raise ValueError(f"{path.name} has no sheet '{sheet}'") from exc


def _build_record(row: cl.RegisterRow, months_live: dict[str, int], costs: dict[str, Decimal],
                  benefits: dict[str, cl.BenefitFigures], usage: dict[str, list[int]],
                  log: ChangeLog) -> InitiativeRecord | None:
    """Assemble one InitiativeRecord, or log the missing inputs and return None."""
    iid = row.initiative_id
    benefit = benefits.get(iid, cl.BenefitFigures())
    missing = [name for name, value in (
        ("go_live_date", row.go_live_date), ("licensed_users", row.licensed_users),
        ("total_cost_to_date", costs.get(iid)), ("weekly_active_users (3 weeks)", usage.get(iid)),
        ("realised_benefit_to_date", benefit.realised_to_date), ("planned_annual_benefit", benefit.planned_annual),
    ) if value is None]
    if missing:
        log.add(AREA_REGISTER, cl.REGISTER_FILE, "EXCLUDED_INCOMPLETE_INITIATIVE", initiative_id=iid,
                before=", ".join(missing), after="excluded from scorecard",
                effect="Initiative not scored until the missing inputs are supplied")
        logger.warning("excluding %s: missing %s", iid, missing)
        return None
    wau = usage[iid]
    return InitiativeRecord(
        initiative_id=iid, initiative_name=row.initiative_name, short_name=row.short_name,
        initiative_type=row.initiative_type, agency=row.agency, go_live_date=row.go_live_date,
        months_live=months_live[iid], licensed_users=row.licensed_users,
        wau_week1=wau[0], wau_week2=wau[1], wau_week3=wau[2],
        total_cost_to_date_usd=cl.to_usd_float(costs[iid]),
        realised_benefit_to_date_usd=cl.to_usd_float(benefit.realised_to_date),
        planned_annual_benefit_usd=cl.to_usd_float(benefit.planned_annual),
        charter_file=row.charter_file,
    )


def _log_assumptions(log: ChangeLog, report_date: date, weeks: tuple[date, ...],
                     fx_rates: dict[str, Decimal]) -> None:
    """Record the standing assumptions behind every cleaned value (FR-01)."""
    log.add(AREA_ASSUMPTION, "", "MONTHS_LIVE_DEFINITION", field="months_live",
            after=f"whole calendar months from go-live to {report_date.isoformat()}",
            effect="Drives average monthly benefit and payback")
    log.add(AREA_ASSUMPTION, "", "REPORTING_WINDOW", field="week_ending",
            after=", ".join(w.isoformat() for w in weeks), effect="Only these three weeks feed WAU metrics")
    for ccy, rate in sorted(fx_rates.items()):
        log.add(AREA_ASSUMPTION, cl.FINANCIALS_FILE, "FX_RATE", field=ccy, after=f"1 USD = {rate} {ccy}",
                effect="Fixed planning rate from FX_and_Units")
    log.add(AREA_ASSUMPTION, cl.FINANCIALS_FILE, "MISSING_ACTUAL_COST_IS_ZERO", field="actualCost ($M)",
            after="blank actualCost on in-progress projects counted as 0",
            effect="Cost to date only includes spend actually reported")
    log.add(AREA_ASSUMPTION, cl.FINANCIALS_FILE, "CLARIFY_SMALL_EPS_COSTS", initiative_id="",
            field="actualCost ($M)", after="left as reported",
            effect="Some projects report costs below $0.02M, which may be $K entered as $M; "
                   "suggested client clarification question")
