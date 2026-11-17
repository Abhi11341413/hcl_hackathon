"""HLD 4: question router (numeric / narrative / mixed / out_of_scope).

Owner: M3 (see CLAUDE.md). Public functions here are listed in CLAUDE.md section 5.

Routing is rule-based first (deterministic and testable). Only questions with no
initiative, metric, narrative or out-of-scope signal are sent to the LLM; when the LLM
is unavailable the client's fallback returns ``out_of_scope``, which is the safe answer.
"""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path

from src import config
from src.contracts import METRIC_NAMES, RouteDecision

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent / "prompts" / "router.txt"
_ID_RE = re.compile(r"\bNIM-?(\d{1,2})\b", re.IGNORECASE)
_CHARTER_NAME_RE = re.compile(r"^(NIM-\d+)_(.+?)_charter\.(?:pdf|docx)$", re.IGNORECASE)

# metric -> phrases that ask for it (lower-case regexes)
METRIC_PATTERNS: dict[str, tuple[str, ...]] = {
    "adoption": (r"\badoption\b", r"\badopted\b", r"\buptake\b"),
    "wau_change": (r"\bwau\b", r"weekly active", r"active users"),
    "roi": (r"\broi\b", r"return on investment"),
    "avg_monthly_benefit": (r"monthly benefit", r"benefit per month", r"average benefit"),
    "payback_months": (r"\bpayback\b", r"pay back", r"break[- ]even"),
    "run_rate_vs_plan": (r"run[- ]?rate", r"\bon track\b", r"against (?:its |the )?plan", r"vs\.? plan",
                         r"versus plan", r"planned benefit"),
    "status": (r"\bstatus\b", r"\bgreen\b", r"\bamber\b", r"\bred\b", r"\brag\b", r"attention",
               r"at risk", r"\bperforming\b", r"\bunderperform"),
}

# phrases that need charter text
NARRATIVE_PATTERNS: tuple[str, ...] = (
    r"\brisks?\b", r"\bcio\b", r"\bcomment", r"\bsaid\b", r"\bsay\b", r"operational analysis",
    r"\bconclu", r"\bobjective", r"\bscope\b", r"\bpurpose\b", r"\bproduce", r"\bclassif",
    r"\bdeliver", r"\bmeant to\b", r"\bbenefits? (?:case|levers?)\b", r"\blevers?\b",
    r"planned benefit", r"stakeholder", r"feedback", r"governance", r"\bcharter\b", r"\bsummar",
    r"\bdescribe\b", r"what is (?!the )", r"what does", r"\bvendor\b", r"\bteam\b", r"\bbudget\b",
    r"\bsponsor\b", r"\bowner\b", r"\bmilestone", r"\bkpis?\b", r"\breview\b", r"satisfaction",
    r"\bassumption", r"\bdependenc", r"\bwho\b",
)

# questions the governed data cannot answer: forecasts, what-ifs, ad-hoc aggregates
OUT_OF_SCOPE_PATTERNS: tuple[str, ...] = (
    r"\bnext (?:year|quarter|month|week)\b", r"\bforecast", r"\bpredict", r"\bproject(?:ed|ion)\b",
    r"\bwill (?:\w+ )?be\b", r"\bif we\b", r"\bwhat would\b", r"\bwhat if\b", r"\bsuppose\b",
    r"\bhypothetical", r"\bdoubl", r"\baverage \w+ across\b", r"\bacross the (?:whole )?portfolio\b",
    r"\bportfolio[- ](?:wide )?(?:average|total|mean)\b", r"\btotal \w+ across\b",
    r"\bweather\b", r"\bstock price\b",
)


def route(question: str, initiative_ids: list[str]) -> RouteDecision:
    """Classify the question and extract the initiatives and metrics it refers to.

    initiative_ids is the list of valid initiative IDs (empty means "use the catalogue").
    """
    if not question or not question.strip():
        return RouteDecision(route="out_of_scope", reason="empty question")
    text = question.lower()
    catalogue = initiative_catalogue()
    valid = set(initiative_ids) or set(catalogue) or None
    ids = find_initiatives(question, catalogue, valid)
    metrics = find_metrics(text)
    narrative = any(re.search(p, text) for p in NARRATIVE_PATTERNS)

    if any(re.search(p, text) for p in OUT_OF_SCOPE_PATTERNS):
        return RouteDecision(route="out_of_scope", initiative_ids=ids, metrics=metrics,
                             reason="forecast, what-if or aggregate outside the governed metrics")
    if metrics and narrative:
        decision = RouteDecision(route="mixed", initiative_ids=ids, metrics=metrics,
                                 reason="needs scorecard values and charter text")
    elif metrics:
        decision = RouteDecision(route="numeric", initiative_ids=ids, metrics=metrics,
                                 reason="asks for governed scorecard metrics")
    elif narrative or ids:
        decision = RouteDecision(route="narrative", initiative_ids=ids, metrics=[],
                                 reason="asks about charter content")
    else:
        decision = _route_with_llm(question, catalogue, valid)
    logger.info("route=%s ids=%s metrics=%s", decision.route, decision.initiative_ids, decision.metrics)
    return decision


def find_metrics(text: str) -> list[str]:
    """Return the scorecard metrics a (lower-case) question mentions, in METRIC_NAMES order."""
    lowered = text.lower()
    return [m for m in METRIC_NAMES if any(re.search(p, lowered) for p in METRIC_PATTERNS.get(m, ()))]


def find_initiatives(question: str, catalogue: dict[str, list[str]], valid: set[str] | None) -> list[str]:
    """Return initiative IDs referenced by ID or by name/short name, in catalogue order."""
    found: set[str] = set()
    for match in _ID_RE.finditer(question):
        found.add(f"NIM-{int(match.group(1)):02d}")
    lowered = question.lower()
    for initiative_id, aliases in catalogue.items():
        for alias in aliases:
            if _alias_matches(alias.lower(), lowered):
                found.add(initiative_id)
                break
    ordered = [i for i in catalogue if i in found] + sorted(found - set(catalogue))
    return [i for i in ordered if valid is None or i in valid]


def initiative_catalogue() -> dict[str, list[str]]:
    """Map initiative ID -> name aliases. Uses the scorecard (M1 public API) when built,
    otherwise the charter file names in config.CHARTER_DIR (e.g. NIM-09_DHS_GenAI_Chat)."""
    return {k: list(v) for k, v in _catalogue_cached(str(config.DB_PATH), str(config.CHARTER_DIR)).items()}


def clear_catalogue_cache() -> None:
    """Forget the cached catalogue (call after the scorecard is rebuilt)."""
    _catalogue_cached.cache_clear()


@lru_cache(maxsize=4)
def _catalogue_cached(db_path: str, charter_dir: str) -> dict[str, tuple[str, ...]]:
    """Build the alias catalogue once per (db, charter dir)."""
    aliases: dict[str, set[str]] = {}
    try:
        from src.scorecard.store import load_scorecard

        for row in load_scorecard(Path(db_path)):
            names = aliases.setdefault(row.initiative_id, set())
            names.update(n for n in (row.short_name, row.initiative_name) if n)
    except Exception as exc:  # scorecard not built / M1 not implemented yet
        logger.info("scorecard catalogue unavailable (%s); using charter file names", exc)
    directory = Path(charter_dir)
    if directory.is_dir():
        for path in sorted(directory.iterdir()):
            match = _CHARTER_NAME_RE.match(path.name)
            if match:
                aliases.setdefault(match.group(1).upper(), set()).add(match.group(2).replace("_", " "))
    return {k: tuple(sorted(v, key=len, reverse=True)) for k, v in sorted(aliases.items())}


def _alias_matches(alias: str, lowered_question: str) -> bool:
    """Whole-word match for an alias; long aliases may be followed by a suffix (chat -> chatbot)."""
    if len(alias) < 3:
        return False
    tail = r"" if len(alias) >= 8 else r"\b"
    return re.search(r"\b" + re.escape(alias) + tail, lowered_question) is not None


def _route_with_llm(question: str, catalogue: dict[str, list[str]], valid: set[str] | None) -> RouteDecision:
    """Ask the LLM (via src.llm.client) for a route when the rules find no signal."""
    from src.llm.client import generate_json

    try:
        template = PROMPT_PATH.read_text(encoding="utf-8")
    except OSError:
        logger.exception("router prompt missing")
        return RouteDecision(route="out_of_scope", reason="router prompt missing")
    initiatives = "\n".join(f"- {i}: {', '.join(names)}" for i, names in catalogue.items()) or "- (none)"
    prompt = template.format(
        initiatives=initiatives,
        schema=json.dumps(RouteDecision.model_json_schema()),
        question=question.strip(),
    )
    result = generate_json(prompt, RouteDecision)
    decision = result if isinstance(result, RouteDecision) else RouteDecision(route="out_of_scope")
    # never trust the LLM with IDs or metric names it was not given
    decision.initiative_ids = [i for i in decision.initiative_ids if valid is None or i in valid]
    decision.metrics = [m for m in decision.metrics if m in METRIC_NAMES]
    if not decision.reason:
        decision.reason = "classified by LLM"
    return decision
