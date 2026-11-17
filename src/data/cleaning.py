"""HLD 1: cleaning and standardisation rules (internal to M1).

Owner: M1 (see CLAUDE.md). Public functions here are listed in CLAUDE.md section 5.

Nothing in this module is a cross-member contract: DataFrames and the small dataclasses
below stay inside M1. ``src.data.loaders.load_and_clean`` turns them into contract models.
Money is handled as ``Decimal`` until the very end so unit conversions never add float noise.
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import pandas as pd

from src.data.change_log import (
    AREA_BENEFIT,
    AREA_COST,
    AREA_REGISTER,
    AREA_USAGE,
    ChangeLog,
)

logger = logging.getLogger(__name__)

REGISTER_FILE = "portfolio_register.xlsx"
USAGE_FILE = "usage_weekly.csv"
FINANCIALS_FILE = "financials.xlsx"

CENT = Decimal("0.01")
_ID_PATTERN = re.compile(r"^NIM-\d+$")
_SLASH_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_UII_PATTERN = re.compile(r"^(\d{1,3})-(\d+)$")
_TEXT_DATE_FORMATS: tuple[str, ...] = ("%Y-%m-%d", "%d-%b-%Y", "%b %d, %Y", "%d %b %Y", "%B %d, %Y")

# usage_weekly.csv: names that all mean "weekly active users"
WAU_METRIC = "weekly_active_users"
WAU_ALIASES: frozenset[str] = frozenset({"weekly_active_users", "wau", "active users (7-day)"})
PCT_OF_LICENSED_UNIT = "% of licensed"

# financials.xlsx › Benefits: unit -> multiplier to USD (currencies come from the FX sheet)
USD_UNIT_MULTIPLIERS: dict[str, Decimal] = {
    "usd": Decimal(1),
    "usd thousands": Decimal(1_000),
    "usd millions": Decimal(1_000_000),
}
BASIS_REALISED = "cumulative to date"
BASIS_MONTHLY_AVG = "average per month since go-live"
BASIS_PLAN_YEAR = "plan, per year"
BASIS_PLAN_MONTH = "plan, per month"
# metric names logged as renames when a row's name differs (monthly bases are logged as conversions)
CANONICAL_BENEFIT_METRICS: dict[str, str] = {
    BASIS_REALISED: "realised_benefit_to_date",
    BASIS_PLAN_YEAR: "planned_annual_benefit",
}


# ----------------------------------------------------------------------------- data holders
@dataclass
class RegisterRow:
    """One de-duplicated register row after cleaning (internal to M1)."""
    initiative_id: str
    source_ref: str
    initiative_name: str
    agency: str
    initiative_type: str
    go_live_date: date | None
    licensed_users: int | None
    charter_file: str
    short_name: str


@dataclass
class BenefitFigures:
    """Cleaned benefit values for one initiative, in USD (None when missing)."""
    realised_to_date: Decimal | None = None
    planned_annual: Decimal | None = None


# ----------------------------------------------------------------------------- scalar parsers
def is_missing(value: object) -> bool:
    """True for None, NaN/NaT and blank strings."""
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if value is pd.NaT:
        return True
    return isinstance(value, str) and value.strip() == ""


def parse_count(value: object) -> int | None:
    """Parse a non-negative integer count; text keeps only its digits ('12,000 seats' -> 12000)."""
    if is_missing(value) or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if float(value).is_integer() and value >= 0 else None
    digits = re.sub(r"\D", "", str(value))
    return int(digits) if digits else None


def parse_decimal(value: object) -> Decimal | None:
    """Parse a number or money text ('$40,583,740' -> 40583740) into a Decimal."""
    if is_missing(value) or isinstance(value, bool):
        return None
    text = str(value).strip().replace("$", "").replace(",", "").replace(" ", "")
    try:
        result = Decimal(text)
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def to_usd_float(amount: Decimal) -> float:
    """Round a USD Decimal to cents and return it as float (the contract type)."""
    return float(amount.quantize(CENT, rounding=ROUND_HALF_UP))


def parse_date(value: object) -> date | None:
    """Parse Excel dates, ISO / '31-Oct-2021' / 'Oct 30, 2026' text, and DD/MM/YYYY (day first)."""
    if is_missing(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip().split(" 00:00:00")[0]
    slash = _SLASH_DATE.match(text)
    if slash:
        first, second, year = (int(part) for part in slash.groups())
        return _safe_date(year, second, first) or _safe_date(year, first, second)
    for fmt in _TEXT_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_week(value: object, valid_weeks: tuple[date, ...]) -> date | None:
    """Parse a week-ending date; an ambiguous NN/NN/YYYY is resolved to the reading
    that falls on one of the expected reporting weeks (else day-first)."""
    text = "" if is_missing(value) else str(value).strip()
    slash = _SLASH_DATE.match(text)
    if slash:
        first, second, year = (int(part) for part in slash.groups())
        candidates = [d for d in (_safe_date(year, second, first), _safe_date(year, first, second)) if d]
        in_window = [d for d in candidates if d in valid_weeks]
        if in_window:
            return in_window[0]
    return parse_date(value)


def months_between(start: date, end: date) -> int:
    """Whole calendar months from start to end (a month counts once its day-of-month is reached)."""
    if start > end:
        raise ValueError(f"start {start} is after end {end}")
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return months


def normalise_source_ref(ref: object) -> str:
    """Trim a source-system ref and zero-pad an IT Dashboard UII agency code ('5-000002148' -> '005-000002148')."""
    if is_missing(ref):
        return ""
    text = str(ref).strip()
    match = _UII_PATTERN.match(text)
    if match:
        return f"{int(match.group(1)):03d}-{match.group(2)}"
    return text


def short_name_from_charter(charter_file: str) -> str:
    """'NIM-09_DHS_GenAI_Chat_charter.pdf' -> 'DHS GenAI Chat' ('' if the name has no such shape)."""
    match = re.match(r"^NIM-\d+_(.+)_charter\.\w+$", charter_file.strip())
    return match.group(1).replace("_", " ") if match else ""


def _safe_date(year: int, month: int, day: int) -> date | None:
    """date(year, month, day) or None when the parts are not a real date."""
    try:
        return date(year, month, day)
    except ValueError:
        return None


# ----------------------------------------------------------------------------- register
def strip_text_cells(df: pd.DataFrame, file: str, log: ChangeLog, id_col: str) -> pd.DataFrame:
    """Trim leading/trailing whitespace in every text cell, logging each changed cell."""
    out = df.copy()
    for col in out.columns:
        for idx, raw in out[col].items():
            if isinstance(raw, str) and raw != raw.strip():
                row_id = str(out.at[idx, id_col]).strip()
                log.add(AREA_REGISTER, file, "TRIM_WHITESPACE", initiative_id=row_id, field=str(col),
                        before=repr(raw), after=repr(raw.strip()),
                        effect="Joins on this value would silently fail if left untrimmed")
                out.at[idx, col] = raw.strip()
    return out


def drop_duplicate_register_rows(df: pd.DataFrame, file: str, log: ChangeLog, id_col: str) -> pd.DataFrame:
    """Drop exact duplicate rows, then any remaining repeated IDs (keep first), logging each drop."""
    exact = df.duplicated(keep="first")
    for idx in df.index[exact]:
        log.add(AREA_REGISTER, file, "DROP_EXACT_DUPLICATE_ROW", initiative_id=str(df.at[idx, id_col]),
                before=f"row {idx + 2}", after="dropped",
                effect="Initiative would be double-counted in portfolio totals")
    out = df[~exact]
    repeated = out.duplicated(subset=[id_col], keep="first")
    for idx in out.index[repeated]:
        log.add(AREA_REGISTER, file, "DROP_CONFLICTING_DUPLICATE_ID", initiative_id=str(out.at[idx, id_col]),
                before=f"row {idx + 2}", after="dropped (first occurrence kept)",
                effect="Two different register rows claim the same Initiative ID; needs client confirmation")
    return out[~repeated]


def clean_go_live(raw: object, initiative_id: str, report_date: date, fallback: date | None,
                  log: ChangeLog) -> date | None:
    """Parse a go-live cell, logging text conversions; a future date is replaced by ``fallback``."""
    parsed = parse_date(raw)
    if parsed is None:
        log.add(AREA_REGISTER, REGISTER_FILE, "UNPARSEABLE_DATE", initiative_id=initiative_id,
                field="Go-Live Date", before=raw, after="", effect="Initiative excluded: months live unknown")
        return None
    if isinstance(raw, str) and raw.strip() != parsed.isoformat():
        rule = "PARSE_DAY_FIRST_DATE" if _SLASH_DATE.match(raw.strip()) else "PARSE_TEXT_DATE"
        log.add(AREA_REGISTER, REGISTER_FILE, rule, initiative_id=initiative_id, field="Go-Live Date",
                before=raw, after=parsed.isoformat(), effect="Mixed date representations standardised to ISO")
    if parsed > report_date:
        if fallback is None:
            log.add(AREA_REGISTER, REGISTER_FILE, "FUTURE_GO_LIVE_NO_FALLBACK", initiative_id=initiative_id,
                    field="Go-Live Date", before=parsed.isoformat(), after="",
                    effect="Initiative excluded: go-live after the reporting date")
            return None
        log.add(AREA_REGISTER, REGISTER_FILE, "FUTURE_GO_LIVE_REPLACED", initiative_id=initiative_id,
                field="Go-Live Date", before=parsed.isoformat(), after=fallback.isoformat(),
                effect="Future go-live replaced by the earliest completed-project date in financials.xlsx; "
                       "months live would otherwise be negative")
        return fallback
    return parsed


def clean_licensed_users(raw: object, initiative_id: str, log: ChangeLog) -> int | None:
    """Parse licensed users; log when text had to be stripped to digits."""
    value = parse_count(raw)
    if value is None:
        log.add(AREA_REGISTER, REGISTER_FILE, "UNPARSEABLE_LICENSED_USERS", initiative_id=initiative_id,
                field="Licensed Users", before=raw, effect="Initiative excluded: adoption cannot be computed")
    elif isinstance(raw, str):
        log.add(AREA_REGISTER, REGISTER_FILE, "STRIP_NON_DIGITS", initiative_id=initiative_id,
                field="Licensed Users", before=raw, after=value, effect="Adoption cannot be computed until fixed")
    return value


def clean_register(df: pd.DataFrame, report_date: date, go_live_fallbacks: dict[str, date],
                   log: ChangeLog) -> list[RegisterRow]:
    """Clean the Register sheet into one RegisterRow per initiative."""
    required = ["Initiative ID", "Source Ref", "Initiative Name", "Go-Live Date", "Licensed Users"]
    _require_columns(df, required, f"{REGISTER_FILE} › Register")
    df = df.dropna(how="all")
    df = strip_text_cells(df, REGISTER_FILE, log, "Initiative ID")
    df = drop_duplicate_register_rows(df, REGISTER_FILE, log, "Initiative ID")
    rows: list[RegisterRow] = []
    for _, rec in df.iterrows():
        initiative_id = str(rec["Initiative ID"])
        source_ref = normalise_source_ref(rec["Source Ref"])
        charter = _text(rec.get("Charter File"))
        rows.append(RegisterRow(
            initiative_id=initiative_id,
            source_ref=source_ref,
            initiative_name=_text(rec["Initiative Name"]),
            agency=_text(rec.get("Agency / Business Unit")),
            initiative_type=_text(rec.get("Initiative Type")),
            go_live_date=clean_go_live(rec["Go-Live Date"], initiative_id, report_date,
                                       go_live_fallbacks.get(source_ref), log),
            licensed_users=clean_licensed_users(rec["Licensed Users"], initiative_id, log),
            charter_file=charter,
            short_name=short_name_from_charter(charter),
        ))
    return rows


# ----------------------------------------------------------------------------- costs
def earliest_completion_dates(costs: pd.DataFrame) -> dict[str, date]:
    """Earliest actualEndDate of a Completed project per normalised UII (go-live fallback source)."""
    out: dict[str, date] = {}
    for _, rec in costs.iterrows():
        if _text(rec.get("projectStatus")).lower() != "completed":
            continue
        end = parse_date(rec.get("actualEndDate"))
        ref = normalise_source_ref(rec.get("currentUII"))
        if end and ref and (ref not in out or end < out[ref]):
            out[ref] = end
    return out


def drop_unit_error_duplicates(costs: pd.DataFrame, log: ChangeLog, ref_to_id: dict[str, str]) -> pd.DataFrame:
    """Drop rows whose actualCost is ~1000x a twin row with the same UII and identical dates."""
    keys = ["_ref", "plannedStartDate", "actualStartDate", "plannedEndDate", "actualEndDate"]
    work = costs.assign(_ref=costs["currentUII"].map(normalise_source_ref))
    drop: list[int] = []
    for _, group in work.groupby(keys, dropna=False):
        for idx, rec in group.iterrows():
            twin = _find_x1000_twin(rec["_cost_m"], group.drop(index=idx))
            if twin is None:
                continue
            drop.append(idx)
            log.add(AREA_COST, FINANCIALS_FILE, "DROP_X1000_UNIT_ERROR_DUPLICATE",
                    initiative_id=ref_to_id.get(rec["_ref"], ""), field="actualCost ($M)",
                    before=f"projectId={rec['projectId']} actualCost={rec['_cost_m']} $M",
                    after=f"dropped; kept twin projectId={twin['projectId']} ({twin['_cost_m']} $M)",
                    effect=f"Total cost to date falls by ${to_usd_float(rec['_cost_m'] * 1_000_000):,.0f}")
    return costs.drop(index=drop)


def _find_x1000_twin(cost_m: Decimal, others: pd.DataFrame) -> pd.Series | None:
    """Return the first row in ``others`` whose cost is cost_m / 1000 (+/-0.1%), else None."""
    if cost_m <= 0:
        return None
    for _, other in others.iterrows():
        if other["_cost_m"] > 0 and Decimal("999") <= cost_m / other["_cost_m"] <= Decimal("1001"):
            return other
    return None


def clean_costs(costs: pd.DataFrame, ref_to_id: dict[str, str], log: ChangeLog) -> dict[str, Decimal]:
    """Total actual cost to date in USD per initiative ID (costs are USD millions keyed by UII)."""
    _require_columns(costs, ["currentUII", "projectId", "actualCost ($M)"], f"{FINANCIALS_FILE} › Costs_ITDashboard")
    costs = costs.dropna(how="all").copy()
    costs["_cost_m"] = [parse_decimal(v) or Decimal(0) for v in costs["actualCost ($M)"]]
    costs = drop_unit_error_duplicates(costs, log, ref_to_id)
    totals_m: dict[str, Decimal] = {}
    for _, rec in costs.iterrows():
        ref = normalise_source_ref(rec["currentUII"])
        initiative_id = ref_to_id.get(ref)
        if initiative_id is None:
            log.add(AREA_COST, FINANCIALS_FILE, "UNMAPPED_COST_ROW", field="currentUII", before=ref,
                    after="ignored", effect="Cost row has no matching register Source Ref")
            continue
        totals_m[initiative_id] = totals_m.get(initiative_id, Decimal(0)) + rec["_cost_m"]
    totals_usd: dict[str, Decimal] = {}
    for initiative_id, total_m in sorted(totals_m.items()):
        totals_usd[initiative_id] = total_m * 1_000_000
        ref = next(r for r, i in ref_to_id.items() if i == initiative_id)
        log.add(AREA_COST, FINANCIALS_FILE, "JOIN_COSTS_VIA_SOURCE_REF", initiative_id=initiative_id,
                field="currentUII", before=ref, after=initiative_id,
                effect="Costs are keyed by source-system ID, not Initiative ID")
        log.add(AREA_COST, FINANCIALS_FILE, "CONVERT_USD_MILLIONS_TO_USD", initiative_id=initiative_id,
                field="actualCost ($M)", before=f"{total_m} $M", after=f"{to_usd_float(total_m * 1_000_000)} USD",
                effect="ROI off by 10^6 if costs are left in $M")
    return totals_usd


# ----------------------------------------------------------------------------- FX + benefits
def read_fx_rates(fx: pd.DataFrame) -> dict[str, Decimal]:
    """Currency units per 1 USD from the FX_and_Units sheet, e.g. {'INR': 84}."""
    _require_columns(fx, ["item", "value", "note"], f"{FINANCIALS_FILE} › FX_and_Units")
    rates: dict[str, Decimal] = {}
    for _, rec in fx.iterrows():
        if "fx" not in _text(rec["item"]).lower():
            continue
        match = re.search(r"1\s*USD\s*=\s*([\d.]+)\s*([A-Z]{3})", _text(rec["note"]))
        rate = parse_decimal(rec["value"])
        if not match or rate is None or rate <= 0:
            raise ValueError(f"FX row is not in the form '1 USD = <rate> <CCY>': {rec.to_dict()}")
        rates[match.group(2)] = rate
    return rates


def benefit_to_usd(value: Decimal, unit: str, fx_rates: dict[str, Decimal]) -> Decimal | None:
    """Convert a benefit amount to USD using its unit label (USD / USD thousands / USD millions / FX)."""
    key = unit.strip().lower()
    if key in USD_UNIT_MULTIPLIERS:
        return value * USD_UNIT_MULTIPLIERS[key]
    rate = fx_rates.get(unit.strip().upper())
    return value / rate if rate else None


def keep_latest_benefits(df: pd.DataFrame, log: ChangeLog) -> pd.DataFrame:
    """For repeated (initiative, basis) rows keep the latest as_of date, logging stale rows."""
    df = df.assign(_as_of=[parse_date(v) or date.min for v in df["as_of"]])
    df = df.sort_values("_as_of", kind="stable")
    stale = df.duplicated(subset=["initiative_id", "_basis"], keep="last")
    for idx in df.index[stale]:
        rec = df.loc[idx]
        log.add(AREA_BENEFIT, FINANCIALS_FILE, "DROP_STALE_DUPLICATE", initiative_id=rec["initiative_id"],
                field=str(rec["metric"]), before=f"{rec['value']} as of {rec['as_of']}",
                after="dropped (latest as_of kept)", effect="Benefit understated or double-counted if summed")
    return df[~stale]


def clean_benefits(benefits: pd.DataFrame, fx_rates: dict[str, Decimal], months_live: dict[str, int],
                   log: ChangeLog) -> dict[str, BenefitFigures]:
    """Realised-to-date and planned-annual benefit in USD per initiative, from the Benefits sheet."""
    _require_columns(benefits, ["initiative_id", "metric", "value", "unit", "basis", "as_of"],
                     f"{FINANCIALS_FILE} › Benefits")
    df = benefits.dropna(how="all").copy()
    df["initiative_id"] = df["initiative_id"].map(_text)
    df["_basis"] = df["basis"].map(lambda v: _text(v).lower())
    df = keep_latest_benefits(df, log)
    out: dict[str, BenefitFigures] = {}
    for _, rec in df.iterrows():
        _apply_benefit_row(rec, fx_rates, months_live, out.setdefault(rec["initiative_id"], BenefitFigures()), log)
    return out


def _apply_benefit_row(rec: pd.Series, fx_rates: dict[str, Decimal], months_live: dict[str, int],
                       target: BenefitFigures, log: ChangeLog) -> None:
    """Convert one Benefits row to USD and store it on ``target`` (logging every transformation)."""
    initiative_id, metric, unit, basis = rec["initiative_id"], _text(rec["metric"]), _text(rec["unit"]), rec["_basis"]
    raw_value = rec["value"]
    value = parse_decimal(raw_value)
    if value is None:
        log.add(AREA_BENEFIT, FINANCIALS_FILE, "UNPARSEABLE_VALUE", initiative_id=initiative_id, field=metric,
                before=raw_value, after="ignored", effect="Benefit missing for this initiative")
        return
    if isinstance(raw_value, str):
        log.add(AREA_BENEFIT, FINANCIALS_FILE, "PARSE_MONEY_TEXT", initiative_id=initiative_id, field=metric,
                before=raw_value, after=str(value), effect="Value unreadable as a number until parsed")
    usd = benefit_to_usd(value, unit, fx_rates)
    if usd is None:
        log.add(AREA_BENEFIT, FINANCIALS_FILE, "UNKNOWN_UNIT", initiative_id=initiative_id, field=metric,
                before=f"{value} {unit}", after="ignored", effect="Benefit missing for this initiative")
        return
    if unit.strip().lower() != "usd":
        log.add(AREA_BENEFIT, FINANCIALS_FILE, f"CONVERT_{_rule_token(unit)}_TO_USD", initiative_id=initiative_id,
                field=metric, before=f"{value} {unit}", after=f"{to_usd_float(usd)} USD",
                effect=_unit_effect(unit, fx_rates))
    _store_by_basis(initiative_id, metric, basis, usd, months_live, target, log)


def _store_by_basis(initiative_id: str, metric: str, basis: str, usd: Decimal, months_live: dict[str, int],
                    target: BenefitFigures, log: ChangeLog) -> None:
    """Route a USD amount to realised/planned according to its basis column."""
    if basis == BASIS_REALISED:
        target.realised_to_date = usd
    elif basis == BASIS_MONTHLY_AVG:
        months = months_live.get(initiative_id)
        if months is None:
            log.add(AREA_BENEFIT, FINANCIALS_FILE, "MONTHLY_AVG_WITHOUT_MONTHS_LIVE", initiative_id=initiative_id,
                    field=metric, before=str(usd), after="ignored", effect="Realised benefit unknown")
            return
        target.realised_to_date = usd * months
        log.add(AREA_BENEFIT, FINANCIALS_FILE, "MONTHLY_AVERAGE_TO_CUMULATIVE", initiative_id=initiative_id,
                field=metric, before=f"{to_usd_float(usd)} per month", after=f"{to_usd_float(usd * months)} "
                f"(x {months} months live)", effect="ROI badly negative if a monthly average is read as cumulative")
    elif basis == BASIS_PLAN_YEAR:
        target.planned_annual = usd
    elif basis == BASIS_PLAN_MONTH:
        target.planned_annual = usd * 12
        log.add(AREA_BENEFIT, FINANCIALS_FILE, "MONTHLY_PLAN_TO_ANNUAL", initiative_id=initiative_id, field=metric,
                before=f"{to_usd_float(usd)} per month", after=f"{to_usd_float(usd * 12)} per year",
                effect="Run-rate vs plan 12x too high if left monthly")
    else:
        log.add(AREA_BENEFIT, FINANCIALS_FILE, "UNKNOWN_BASIS", initiative_id=initiative_id, field=metric,
                before=basis, after="ignored", effect="Row not used: basis not recognised")
        return
    canonical = CANONICAL_BENEFIT_METRICS.get(basis)
    if canonical and metric != canonical:
        log.add(AREA_BENEFIT, FINANCIALS_FILE, "RENAME_METRIC", initiative_id=initiative_id, field="metric",
                before=metric, after=canonical, effect="Row ignored if metric names are not normalised")


def _rule_token(unit: str) -> str:
    """'USD thousands' -> 'USD_THOUSANDS' for rule names."""
    return re.sub(r"\W+", "_", unit.strip().upper()).strip("_")


def _unit_effect(unit: str, fx_rates: dict[str, Decimal]) -> str:
    """Human-readable consequence of not converting this unit."""
    key = unit.strip().upper()
    if key in fx_rates:
        return f"Converted at 1 USD = {fx_rates[key]} {key} (FX_and_Units); benefit overstated {fx_rates[key]}x if left"
    return f"ROI wrong by the {unit} scale factor if left unconverted"


# ----------------------------------------------------------------------------- usage
def clean_usage(usage: pd.DataFrame, ref_to_id: dict[str, str], licensed: dict[str, int],
                weeks: tuple[date, ...], log: ChangeLog) -> dict[str, list[int]]:
    """Weekly active users per initiative for the reporting weeks, in week order."""
    _require_columns(usage, ["initiative_ref", "week_ending", "metric_name", "value", "unit"], USAGE_FILE)
    df = usage.dropna(how="all")
    df = _drop_exact_usage_duplicates(df, log)
    df = df.assign(initiative_id=[_map_usage_ref(r, ref_to_id, log) for r in df["initiative_ref"]])
    df = df[df["initiative_id"] != ""]
    df = df.assign(week=[_parse_usage_week(r, weeks, log) for _, r in df.iterrows()])
    df = _filter_reporting_weeks(df, weeks, log)
    values: dict[str, dict[date, int]] = {}
    for _, rec in df.iterrows():
        wau = _usage_value_to_wau(rec, licensed, log)
        if wau is not None:
            _store_week(values.setdefault(rec["initiative_id"], {}), rec, wau, log)
    return {iid: [by_week[w] for w in weeks] for iid, by_week in values.items() if all(w in by_week for w in weeks)}


def _drop_exact_usage_duplicates(df: pd.DataFrame, log: ChangeLog) -> pd.DataFrame:
    """Drop rows that repeat an earlier row exactly."""
    exact = df.duplicated(keep="first")
    for idx in df.index[exact]:
        rec = df.loc[idx]
        log.add(AREA_USAGE, USAGE_FILE, "DROP_EXACT_DUPLICATE_ROW", initiative_id=str(rec["initiative_ref"]),
                field="week_ending", before=f"{rec['week_ending']} = {rec['value']} (line {idx + 2})",
                after="dropped", effect="Double-counting if weekly rows are summed")
    return df[~exact]


def _map_usage_ref(raw: object, ref_to_id: dict[str, str], log: ChangeLog) -> str:
    """Return the Initiative ID for a usage ref (an ID already, or a source-system UII)."""
    text = _text(raw)
    if _ID_PATTERN.match(text):
        return text
    initiative_id = ref_to_id.get(normalise_source_ref(text), "")
    if initiative_id:
        log.add_once(("usage-ref", text), AREA_USAGE, USAGE_FILE, "MAP_SOURCE_REF_TO_INITIATIVE_ID",
                     initiative_id=initiative_id, field="initiative_ref", before=text,
                     after=f"{normalise_source_ref(text)} -> {initiative_id}",
                     effect="Initiative has no usage if the UII (leading zeros stripped) is not mapped")
    else:
        log.add_once(("usage-ref", text), AREA_USAGE, USAGE_FILE, "UNMAPPED_USAGE_REF", field="initiative_ref",
                     before=text, after="ignored", effect="Usage rows dropped: no matching initiative")
    return initiative_id


def _parse_usage_week(rec: pd.Series, weeks: tuple[date, ...], log: ChangeLog) -> date | None:
    """Parse week_ending; log every non-ISO representation."""
    raw = rec["week_ending"]
    parsed = parse_week(raw, weeks)
    text = _text(raw)
    if parsed is None:
        log.add(AREA_USAGE, USAGE_FILE, "UNPARSEABLE_WEEK", initiative_id=rec["initiative_id"], field="week_ending",
                before=text, after="dropped", effect="Usage row unusable")
    elif text != parsed.isoformat():
        rule = "RESOLVE_SLASH_DATE_BY_WEEK_SEQUENCE" if _SLASH_DATE.match(text) else "PARSE_TEXT_DATE"
        log.add(AREA_USAGE, USAGE_FILE, rule, initiative_id=rec["initiative_id"], field="week_ending",
                before=text, after=parsed.isoformat(), effect="Wrong week order would give a wrong WAU change")
    return parsed


def _filter_reporting_weeks(df: pd.DataFrame, weeks: tuple[date, ...], log: ChangeLog) -> pd.DataFrame:
    """Keep rows whose week is one of the reporting weeks."""
    keep = df["week"].isin(weeks)
    for idx in df.index[~keep & df["week"].notna()]:
        rec = df.loc[idx]
        log.add(AREA_USAGE, USAGE_FILE, "DROP_WEEK_OUTSIDE_REPORTING_PERIOD", initiative_id=rec["initiative_id"],
                field="week_ending", before=f"{rec['week'].isoformat()} = {rec['value']}", after="dropped",
                effect="'First week' of the WAU change would be wrong")
    return df[keep]


def _usage_value_to_wau(rec: pd.Series, licensed: dict[str, int], log: ChangeLog) -> int | None:
    """Turn one usage row into a WAU count (rename metric, % of licensed -> users, fix sign)."""
    initiative_id, metric, unit = rec["initiative_id"], _text(rec["metric_name"]), _text(rec["unit"]).lower()
    value = parse_decimal(rec["value"])
    if value is None:
        log.add(AREA_USAGE, USAGE_FILE, "UNPARSEABLE_VALUE", initiative_id=initiative_id, field="value",
                before=rec["value"], after="dropped", effect="Week missing for this initiative")
        return None
    if unit == PCT_OF_LICENSED_UNIT:
        seats = licensed.get(initiative_id)
        if seats is None:
            return None
        users = value / 100 * seats
        log.add(AREA_USAGE, USAGE_FILE, "PERCENT_OF_LICENSED_TO_USERS", initiative_id=initiative_id,
                field=f"value ({rec['week'].isoformat()})", before=f"{value} {rec['unit']}",
                after=f"{int(users.to_integral_value(ROUND_HALF_UP))} users (x {seats} licensed / 100)",
                effect="Adoption would be wrong if the percentage were read as a user count")
        value = users
    elif metric.lower() in WAU_ALIASES:
        if metric != WAU_METRIC:
            log.add_once(("usage-rename", initiative_id, metric), AREA_USAGE, USAGE_FILE, "RENAME_METRIC",
                         initiative_id=initiative_id, field="metric_name", before=metric, after=WAU_METRIC,
                         effect="Rows ignored if metric names are not normalised")
    else:
        log.add(AREA_USAGE, USAGE_FILE, "UNKNOWN_USAGE_METRIC", initiative_id=initiative_id, field="metric_name",
                before=metric, after="dropped", effect="Row is not a weekly-active-users measure")
        return None
    if value < 0:
        log.add(AREA_USAGE, USAGE_FILE, "NEGATIVE_WAU_SIGN_ERROR", initiative_id=initiative_id,
                field=f"value ({rec['week'].isoformat()})", before=str(value), after=str(-value),
                effect="Assumption: sign error; a negative count would distort the WAU change")
        value = -value
    return int(value.to_integral_value(ROUND_HALF_UP))


def _store_week(by_week: dict[date, int], rec: pd.Series, wau: int, log: ChangeLog) -> None:
    """Store one week's WAU; a conflicting repeat keeps the later row and is logged."""
    week = rec["week"]
    if week in by_week and by_week[week] != wau:
        log.add(AREA_USAGE, USAGE_FILE, "CONFLICTING_WEEK_VALUES", initiative_id=rec["initiative_id"],
                field=f"value ({week.isoformat()})", before=by_week[week], after=wau,
                effect="Two different values for the same week; later row kept, needs client confirmation")
    by_week[week] = wau


# ----------------------------------------------------------------------------- helpers
def _text(value: object) -> str:
    """Stripped string for a cell ('' when missing)."""
    return "" if is_missing(value) else str(value).strip()


def _require_columns(df: pd.DataFrame, columns: list[str], where: str) -> None:
    """Raise ValueError naming the missing columns, so bad inputs fail loudly."""
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ValueError(f"{where} is missing columns: {missing}")
