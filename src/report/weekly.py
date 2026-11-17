"""Executive report generator (weekly report).

Owner: M4 (see CLAUDE.md). Public functions here are listed in CLAUDE.md section 5.

Deterministic: no LLM. Every figure is a ScorecardRow value, only formatted for display.
Every reason carries a citation:
  - scorecard values -> ``scorecard:<initiative_id>:<metric>`` (see docs/requests/M4.md)
  - charter context  -> the evidence_id returned by M2 ``retrieve`` (file and section only;
    charter text is never copied into the report, so embedded instructions cannot leak in).
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from src import config
from src.charters import retriever as charter_retriever
from src.contracts import Citation, ReportItem, ScorecardRow, WeeklyReport

logger = logging.getLogger(__name__)

STATUS_ORDER: dict[str, int] = {"Red": 0, "Amber": 1, "Green": 2}
STATUS_ICON: dict[str, str] = {"Red": "🔴", "Amber": "🟠", "Green": "🟢"}
CHARTER_REFS_PER_ITEM = 2

METRIC_LABELS: dict[str, str] = {
    "adoption": "Adoption",
    "wau_change": "WAU change",
    "roi": "ROI",
    "avg_monthly_benefit": "Avg monthly benefit",
    "payback_months": "Payback (months)",
    "run_rate_vs_plan": "Run-rate vs plan",
    "status": "Status",
}
_PCT_METRICS = {"adoption", "wau_change", "roi", "run_rate_vs_plan"}


# ------------------------------------------------------------------ formatting (display only)
def _half_up(value: float, places: str, scale: int = 1) -> Decimal:
    """Round half-up on the decimal representation (avoids 0.2875*100 -> 28.749999 -> "28.7")."""
    return (Decimal(repr(float(value))) * scale).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def format_pct(value: float | None) -> str:
    """Format a ratio (0.2875) as a percentage with one decimal ("28.8%"); None -> "n/a"."""
    return "n/a" if value is None else f"{_half_up(value, '0.1', scale=100)}%"


def format_usd(value: float | None) -> str:
    """Format a USD amount with thousands separators and no decimals; None -> "n/a"."""
    return "n/a" if value is None else f"${_half_up(value, '1'):,}"


def format_months(value: float | None) -> str:
    """Format a month count with one decimal; None -> "n/a"."""
    return "n/a" if value is None else f"{_half_up(value, '0.1')}"


def format_metric(metric: str, value: float | str | None) -> str:
    """Format any scorecard metric value for display, by metric name."""
    if value is None:
        return "n/a"
    if isinstance(value, str):
        return value
    if metric in _PCT_METRICS:
        return format_pct(value)
    if metric == "avg_monthly_benefit":
        return format_usd(value)
    if metric == "payback_months":
        return format_months(value)
    return str(value)


def scorecard_evidence_id(initiative_id: str, metric: str) -> str:
    """Evidence ID for one scorecard value (format proposed in docs/requests/M4.md)."""
    return f"scorecard:{initiative_id}:{metric}"


def label(row: ScorecardRow) -> str:
    """Human label for an initiative: 'NIM-04 EPS' (falls back to the full name)."""
    return f"{row.initiative_id} {row.short_name or row.initiative_name}".strip()


# ------------------------------------------------------------------ reasons
def attention_reasons(row: ScorecardRow) -> list[tuple[str, str]]:
    """Return (reason, metric) pairs explaining why an initiative is Amber/Red,
    plus supporting signals (falling usage, run-rate below plan). Uses only row values
    and the thresholds in src.config."""
    green, red = config.GREEN_MIN_ADOPTION, config.RED_MAX_ADOPTION
    reasons: list[tuple[str, str]] = []

    if row.adoption is None:
        reasons.append(("Adoption not available (missing input)", "adoption"))
    elif row.adoption < red:
        reasons.append((f"Adoption {format_pct(row.adoption)} is below the {format_pct(red)} Red threshold", "adoption"))
    elif row.adoption < green:
        reasons.append((f"Adoption {format_pct(row.adoption)} is below the {format_pct(green)} Green threshold", "adoption"))

    if row.roi is None:
        reasons.append(("ROI not available (missing input)", "roi"))
    elif row.roi < config.ROI_ZERO:
        reasons.append((f"ROI {format_pct(row.roi)} is negative", "roi"))
    elif row.roi == config.ROI_ZERO and row.status != "Green":
        reasons.append((f"ROI {format_pct(row.roi)} is not above 0", "roi"))

    if row.run_rate_vs_plan is not None and row.run_rate_vs_plan < 1:
        reasons.append((f"Benefit run-rate is {format_pct(row.run_rate_vs_plan)} of plan", "run_rate_vs_plan"))
    if row.wau_change is not None and row.wau_change < 0:
        reasons.append((f"Weekly active users changed {format_pct(row.wau_change)} over the three weeks", "wau_change"))
    return reasons


def _charter_citations(row: ScorecardRow) -> list[Citation]:
    """Best-effort charter references from M2. Returns [] if retrieval is unavailable."""
    query = f"risks, issues and objectives of {row.initiative_name}"
    try:
        evidence = charter_retriever.retrieve(query, [row.initiative_id], config.TOP_K)
    except NotImplementedError:
        logger.info("charter retriever not implemented yet; report has scorecard citations only")
        return []
    except Exception:
        logger.exception("charter retrieval failed for %s", row.initiative_id)
        return []
    refs: list[Citation] = []
    for ev in evidence:
        if ev.kind != "charter" or ev.initiative_id != row.initiative_id:
            continue
        where = f"{ev.source_file} › {ev.section}" if ev.section else ev.source_file
        refs.append(Citation(evidence_id=ev.evidence_id, claim=f"Charter context: {where}"))
        if len(refs) >= CHARTER_REFS_PER_ITEM:
            break
    return refs


def build_item(row: ScorecardRow, with_charter: bool = True) -> ReportItem:
    """Build the report item for one initiative: reasons, plus a citation for each reason."""
    reasons = attention_reasons(row)
    citations = [Citation(evidence_id=scorecard_evidence_id(row.initiative_id, "status"),
                          claim=f"Status {row.status}")]
    citations += [Citation(evidence_id=scorecard_evidence_id(row.initiative_id, m), claim=text) for text, m in reasons]
    if with_charter:
        citations += _charter_citations(row)
    return ReportItem(initiative_id=row.initiative_id, status=row.status,
                      reasons=[text for text, _ in reasons] or [f"Status {row.status}"], citations=citations)


# ------------------------------------------------------------------ report
def _dedupe(rows: list[ScorecardRow]) -> list[ScorecardRow]:
    seen: set[str] = set()
    unique: list[ScorecardRow] = []
    for row in rows:
        if row.initiative_id in seen:
            logger.warning("duplicate scorecard row for %s ignored", row.initiative_id)
            continue
        seen.add(row.initiative_id)
        unique.append(row)
    return unique


def _sort_key(row: ScorecardRow) -> tuple[int, float, str]:
    adoption = row.adoption if row.adoption is not None else -1.0
    return STATUS_ORDER[row.status], adoption, row.initiative_id


def _summary(rows: list[ScorecardRow], counts: dict[str, int], items: list[ReportItem]) -> str:
    if not rows:
        return "No scorecard data is available yet. Build the data on the home page first."
    text = (f"The portfolio has {len(rows)} initiatives: {counts['Green']} Green, {counts['Amber']} Amber "
            f"and {counts['Red']} Red. {len(items)} need attention this week.")
    with_roi = [r for r in rows if r.roi is not None]
    if with_roi:
        best = max(with_roi, key=lambda r: r.roi)  # selection only, no arithmetic
        text += f" Highest ROI: {label(best)} ({format_pct(best.roi)})."
    with_adoption = [r for r in rows if r.adoption is not None]
    if with_adoption:
        low = min(with_adoption, key=lambda r: r.adoption)
        text += f" Lowest adoption: {label(low)} ({format_pct(low.adoption)})."
    return text


def _scorecard_table(rows: list[ScorecardRow]) -> list[str]:
    head = "| Initiative | Status | Adoption | WAU change | ROI | Avg monthly benefit | Payback (months) | Run-rate vs plan |"
    lines = [head, "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(
            f"| {label(r)} | {STATUS_ICON[r.status]} {r.status} | {format_pct(r.adoption)} | {format_pct(r.wau_change)} "
            f"| {format_pct(r.roi)} | {format_usd(r.avg_monthly_benefit)} | {format_months(r.payback_months)} "
            f"| {format_pct(r.run_rate_vs_plan)} |")
    return lines


def render_markdown(report_date: date, rows: list[ScorecardRow], counts: dict[str, int],
                    summary: str, items: list[ReportItem]) -> str:
    """Render the weekly report as markdown. Every reason line ends with its evidence ID."""
    by_id = {r.initiative_id: r for r in rows}
    md = [f"# Weekly AI Portfolio Report: week ending {report_date.isoformat()}", "", "## Summary", summary, ""]
    if not rows:
        return "\n".join(md)
    md += ["## Status overview",
           f"{STATUS_ICON['Green']} Green: {counts['Green']} · {STATUS_ICON['Amber']} Amber: {counts['Amber']} · "
           f"{STATUS_ICON['Red']} Red: {counts['Red']}", "", "## Initiatives requiring attention"]
    if not items:
        md.append("None: every initiative is Green.")
    for item in items:
        row = by_id[item.initiative_id]
        md.append(f"### {STATUS_ICON[item.status]} {label(row)}: {item.status}")
        md.append(f"_{row.initiative_name}_")
        cites = {c.claim: c.evidence_id for c in item.citations}
        for reason in item.reasons:
            ref = cites.get(reason, scorecard_evidence_id(row.initiative_id, "status"))
            md.append(f"- {reason} `[{ref}]`")
        charter = [c for c in item.citations if not c.evidence_id.startswith("scorecard:")]
        if charter:
            md.append("- Related charter evidence: " + "; ".join(f"{c.claim.removeprefix('Charter context: ')} `[{c.evidence_id}]`" for c in charter))
        md.append("")
    md += ["## Full scorecard", *_scorecard_table(rows), "", "## Evidence index"]
    for item in items:
        for c in item.citations:
            md.append(f"- `{c.evidence_id}`: {c.claim}")
    md += ["", "_Method: every figure is taken from the governed scorecard (deterministic code, "
           "problem statement 2b section 4 formulas); this report only formats values. "
           "Charter references point to the indexed charter file and section._"]
    return "\n".join(md)


def build_weekly_report(rows: list[ScorecardRow]) -> WeeklyReport:
    """Summarise portfolio performance, list Amber/Red initiatives with reasons, and cite
    scorecard values (and charter evidence via M2 retrieve) for every statement."""
    rows = sorted(_dedupe(list(rows or [])), key=_sort_key)
    report_date = date.fromisoformat(config.REPORT_DATE)
    counts = {s: sum(1 for r in rows if r.status == s) for s in ("Green", "Amber", "Red")}
    items = [build_item(r) for r in rows if r.status != "Green"]
    summary = _summary(rows, counts, items)
    markdown = render_markdown(report_date, rows, counts, summary, items)
    logger.info("weekly report built: %d initiatives, %d attention items", len(rows), len(items))
    return WeeklyReport(report_date=report_date, status_counts=counts, summary=summary, items=items, markdown=markdown)
