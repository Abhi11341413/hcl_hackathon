"""Evidence aggregator + HLD 6 answer generator (orchestrates the question-time flow).

Owner: M3 (see CLAUDE.md). Public functions here are listed in CLAUDE.md section 5.

Flow: check_input -> route -> 5a scorecard lookup and/or 5b charter retrieval ->
aggregate (code filters/sorts; the LLM never compares or computes) -> LLM draft ->
guardrail validate. Every failure path ends in config.FALLBACK_TEXT, never an exception.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from pydantic import BaseModel, Field

from src import config
from src.ai.guardrails import check_input, redact_injections, validate
from src.ai.router import initiative_catalogue, route
from src.contracts import AnswerStatus, Answer, Citation, Evidence, RouteDecision

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent / "prompts" / "answer_system.txt"
EVIDENCE_LINE_SEP = " :: "  # must match src.llm.client's extractive-fallback contract
PERCENT_METRICS = frozenset({"adoption", "wau_change", "roi", "run_rate_vs_plan"})
STATUS_DRIVERS = ("adoption", "roi")  # G/A/R depends on these, so "why" needs them
_HIGH_RE = re.compile(r"\b(highest|best|top|most|largest|biggest|greatest|maximum)\b")
_LOW_RE = re.compile(r"\b(lowest|worst|bottom|least|smallest|minimum)\b")
_STATUS_RE = re.compile(r"\b(green|amber|red)\b")


class DraftAnswer(BaseModel):
    """What the LLM is asked to return (evidence and route are attached by code)."""
    status: AnswerStatus = Field(description="answered | insufficient_evidence | refused")
    text: str = Field(description="Answer for the user, citing evidence ids in [brackets]")
    citations: list[Citation] = Field(default_factory=list)


def answer_question(question: str) -> Answer:
    """check_input -> route -> scorecard lookup / charter retrieve -> aggregate evidence ->
    LLM draft -> guardrail validate. Returns the approved Answer (or the fallback)."""
    try:
        refusal = check_input(question)
        if refusal is not None:
            return refusal
        decision = route(question, list(initiative_catalogue()))
        if decision.route == "out_of_scope":
            return Answer(status="insufficient_evidence", text=config.FALLBACK_TEXT, route="out_of_scope")
        evidence = gather_evidence(question, decision)
        if not evidence:
            logger.info("no evidence for route=%s", decision.route)
            return Answer(status="insufficient_evidence", text=config.FALLBACK_TEXT, route=decision.route)
        draft = draft_answer(question, evidence, decision)
        result = validate(draft, evidence)
        return result.answer
    except Exception:  # the chat must never crash; log and fall back
        logger.exception("answer_question failed")
        return Answer(status="insufficient_evidence", text=config.FALLBACK_TEXT)


# ------------------------------------------------------------------ evidence aggregation
def gather_evidence(question: str, decision: RouteDecision) -> list[Evidence]:
    """Fetch scorecard and/or charter evidence for the route, then filter it in code."""
    evidence: list[Evidence] = []
    if decision.route in ("numeric", "mixed"):
        metrics = list(decision.metrics)
        if "status" in metrics:
            metrics += [m for m in STATUS_DRIVERS if m not in metrics]
        scorecard = _safe_lookup(decision.initiative_ids, metrics)
        evidence.extend(select_scorecard_evidence(question, decision, scorecard))
    if decision.route in ("narrative", "mixed"):
        charter = _safe_retrieve(question, decision.initiative_ids or None)
        evidence.extend(e.model_copy(update={"text": redact_injections(e.text)}) for e in charter)
    return _dedupe(evidence)


def select_scorecard_evidence(question: str, decision: RouteDecision, items: list[Evidence]) -> list[Evidence]:
    """Code-side selection for portfolio questions (no initiative named):
    "which are Red" keeps only those initiatives; "highest/lowest X" keeps the top one."""
    items = [_with_display(e) for e in items if e.kind == "scorecard"]
    if decision.initiative_ids or not items:
        return items
    lowered = question.lower()
    wanted_status = {s.capitalize() for s in _STATUS_RE.findall(lowered)}
    if wanted_status and "status" in decision.metrics:
        keep = {e.initiative_id for e in items if e.metric == "status" and str(e.value) in wanted_status}
        return [e for e in items if e.initiative_id in keep and e.metric in ("status", *STATUS_DRIVERS)]
    ranked_metric = next((m for m in decision.metrics if m != "status"), None)
    high, low = _HIGH_RE.search(lowered), _LOW_RE.search(lowered)
    if ranked_metric and (high or low):
        numeric = [e for e in items if e.metric == ranked_metric and isinstance(e.value, (int, float))]
        if numeric:
            pick = max(numeric, key=lambda e: e.value) if high else min(numeric, key=lambda e: e.value)
            return [pick]
    return items


def display_value(metric: str | None, value: float | str | None) -> str | None:
    """Format a scorecard value for people (code formats; the LLM only copies)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        return value
    if metric in PERCENT_METRICS:
        return f"{value * 100:.1f}%"
    if metric == "payback_months":
        return f"{value:.1f} months"
    if metric == "avg_monthly_benefit":
        return f"${value:,.2f}"
    return f"{value:g}"


def _with_display(item: Evidence) -> Evidence:
    """Append the formatted value to scorecard evidence text when it is not already there."""
    shown = display_value(item.metric, item.value)
    if not shown or shown in item.text:
        return item
    label = item.metric or "value"
    return item.model_copy(update={"text": f"{item.text} ({label} = {shown})".strip()})


def _safe_lookup(initiative_ids: list[str], metrics: list[str]) -> list[Evidence]:
    """M1 5a lookup; empty list when the scorecard is not available."""
    try:
        from src.scorecard.store import lookup

        return lookup(initiative_ids, metrics, config.DB_PATH)
    except Exception as exc:
        logger.warning("scorecard lookup unavailable: %s", exc)
        return []


def _safe_retrieve(question: str, initiative_ids: list[str] | None) -> list[Evidence]:
    """M2 5b retrieval; empty list when the charter index is not available."""
    try:
        from src.charters.retriever import retrieve

        return retrieve(question, initiative_ids, config.TOP_K)
    except Exception as exc:
        logger.warning("charter retrieval unavailable: %s", exc)
        return []


def _dedupe(evidence: list[Evidence]) -> list[Evidence]:
    """Keep the first item per evidence_id."""
    seen: set[str] = set()
    unique: list[Evidence] = []
    for item in evidence:
        if item.evidence_id not in seen:
            seen.add(item.evidence_id)
            unique.append(item)
    return unique


# ------------------------------------------------------------------ drafting
def format_evidence(evidence: list[Evidence]) -> str:
    """One line per item: ``[id] kind=.. | initiative=.. | ... :: text`` (newlines flattened)."""
    lines = []
    for item in evidence:
        meta = [f"kind={item.kind}", f"initiative={item.initiative_id}"]
        if item.metric:
            meta.append(f"metric={item.metric}")
        source = item.source_file + (f"#{item.section}" if item.section else "")
        meta.append(f"source={source}")
        text = " ".join(item.text.split())
        lines.append(f"[{item.evidence_id}] {' | '.join(meta)}{EVIDENCE_LINE_SEP}{text}")
    return "\n".join(lines)


def build_prompt(question: str, evidence: list[Evidence]) -> str:
    """Fill the answer template (src/ai/prompts/answer_system.txt)."""
    template = PROMPT_PATH.read_text(encoding="utf-8")
    return template.format(
        schema=json.dumps(DraftAnswer.model_json_schema()),
        question=question.strip(),
        evidence=format_evidence(evidence),
    )


def draft_answer(question: str, evidence: list[Evidence], decision: RouteDecision) -> Answer:
    """Ask the LLM (via src.llm.client) for a grounded draft and attach evidence + route."""
    from src.llm.client import generate_json

    result = generate_json(build_prompt(question, evidence), DraftAnswer)
    if not isinstance(result, DraftAnswer):
        result = DraftAnswer.model_validate(result.model_dump())
    status = "insufficient_evidence" if result.status == "refused" else result.status
    return Answer(
        status=status,
        text=result.text or "",
        citations=list(result.citations),
        evidence=evidence,
        route=decision.route,
    )
