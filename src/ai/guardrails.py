"""HLD 7: guardrail validator (numbers, citations, injections, personal data).

Owner: M3 (see CLAUDE.md). Public functions here are listed in CLAUDE.md section 5.

Rules enforced on every drafted answer:
- an ``answered`` draft must cite at least one evidence_id that exists in the evidence;
- every number in the text must appear in the evidence; percentages must appear in
  *scorecard* evidence (so a figure planted in a charter can never become a metric);
- no email addresses or phone numbers in the output.
Anything that fails is replaced by ``config.FALLBACK_TEXT``.
"""
from __future__ import annotations

import logging
import re

from src import config
from src.contracts import Answer, Evidence, GuardrailResult

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?<![\w.])\+?\d[\d\s().-]{7,}\d(?![\w.])")
_NUMBER_RE = re.compile(r"(?<![\w.])(-?)(\$?)(\d[\d,]*(?:\.\d+)?)(%?)")
_INITIATIVE_ID_RE = re.compile(r"\bNIM-?\d+\b", re.IGNORECASE)
_TOLERANCE = 1e-9

PII_REQUEST_PATTERNS: tuple[str, ...] = (
    r"\be-?mail\b", r"\bphone\b", r"\bmobile (?:number|no)\b", r"\btelephone\b", r"\bcontact details\b",
    r"\bcontact (?:number|info)", r"\bhome address\b", r"\bpostal address\b", r"\baddress of\b",
    r"\bwhere does .{1,60}\blive\b", r"\bwhere .{1,40} lives?\b", r"\bdate of birth\b", r"\bbirthday\b",
    r"\bsalary of\b", r"\bpersonal (?:details|information|data)\b", r"\bsocial security\b", r"\bssn\b",
    r"\bpassport\b", r"\bwhatsapp\b", r"\blinkedin\b",
)

INJECTION_PATTERNS: tuple[str, ...] = (
    r"ignore (?:all |any |the |your |previous |prior |above |earlier )+(?:instructions|rules|prompts?|guidelines)",
    r"disregard (?:all |any |the |your |previous |prior |above )*(?:instructions|rules|guidelines)",
    r"forget (?:all |everything |your |previous )+(?:instructions|rules|you)",
    r"\b(?:you are|act as|pretend to be|you're) now\b", r"\bnew instructions?\b", r"\bsystem prompt\b",
    r"\b(?:assistant|ai|model|llm|chatbot)s?\s*(?:must|should|shall)\b",
    r"\bwhen (?:asked|summari[sz]ing|reporting)\b.{0,80}\b(?:say|report|state|answer|claim)\b",
    r"\b(?:always|must) (?:report|say|state|answer|claim)\b", r"\boverride\b", r"\bjailbreak\b",
    r"^\s*(?:system|assistant)\s*:", r"\bdo not (?:mention|reveal|cite)\b",
)
REDACTION = "[instruction-like text removed]"


# ------------------------------------------------------------------ input checks
def check_input(question: str) -> Answer | None:
    """Return a refusal Answer for disallowed requests (e.g. personal details), else None."""
    if question is None or not question.strip():
        return Answer(status="insufficient_evidence", text=config.FALLBACK_TEXT)
    lowered = question.lower()
    if EMAIL_RE.search(question) or any(re.search(p, lowered) for p in PII_REQUEST_PATTERNS):
        logger.info("refused: personal-details request")
        return Answer(status="refused", text=config.REFUSAL_PII_TEXT)
    return None


def detect_injection(text: str) -> bool:
    """True when text contains instruction-like content aimed at the model."""
    if not text:
        return False
    return any(re.search(p, text, flags=re.IGNORECASE | re.MULTILINE) for p in INJECTION_PATTERNS)


def redact_injections(text: str) -> str:
    """Replace sentences/lines of untrusted text that look like instructions to the model."""
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?\n])\s+", text)
    cleaned = [REDACTION if detect_injection(part) else part for part in parts]
    return " ".join(cleaned)


# ------------------------------------------------------------------ output validation
def validate(draft: Answer, evidence: list[Evidence]) -> GuardrailResult:
    """Block any number not present in scorecard evidence and any citation that does not
    resolve to an evidence_id; replace with config.FALLBACK_TEXT when unsupported."""
    if draft.status == "refused":
        return GuardrailResult(approved=True, answer=draft)
    if draft.status == "insufficient_evidence":
        return GuardrailResult(approved=True, answer=_fallback(draft))

    violations: list[str] = []
    fatal = False
    known = {e.evidence_id: e for e in evidence}
    valid_citations = [c for c in draft.citations if c.evidence_id in known]
    for citation in draft.citations:
        if citation.evidence_id not in known:
            violations.append(f"unknown_citation:{citation.evidence_id}")
    if not valid_citations:
        violations.append("no_valid_citations")
        fatal = True
    if not draft.text or not draft.text.strip():
        violations.append("empty_text")
        fatal = True

    unsupported = unsupported_numbers(draft.text or "", evidence)
    if unsupported:
        violations.extend(f"unsupported_number:{n}" for n in unsupported)
        fatal = True
    if EMAIL_RE.search(draft.text or "") or PHONE_RE.search(_strip_ids(draft.text or "", evidence)):
        violations.append("personal_data_in_output")
        fatal = True

    if fatal:
        logger.warning("guardrail blocked answer: %s", violations)
        return GuardrailResult(approved=False, violations=violations, answer=_fallback(draft))
    cited_ids = {c.evidence_id for c in valid_citations}
    shown = [e for e in evidence if e.evidence_id in cited_ids]
    final = draft.model_copy(update={"citations": valid_citations, "evidence": shown})
    if violations:
        logger.info("guardrail approved with warnings: %s", violations)
    return GuardrailResult(approved=True, violations=violations, answer=final)


def unsupported_numbers(text: str, evidence: list[Evidence]) -> list[str]:
    """Return number tokens in text that the evidence does not support.

    Percentages must be found in scorecard evidence; other numbers in any evidence.
    Initiative IDs and evidence IDs are ignored. Signs are ignored ("-22.0%" == "22.0%").
    """
    scorecard_values = _allowed_values([e for e in evidence if e.kind == "scorecard"])
    all_values = scorecard_values | _allowed_values([e for e in evidence if e.kind != "scorecard"])
    bad: list[str] = []
    for token, value, is_percent in _numbers(_strip_ids(text, evidence)):
        allowed = scorecard_values if is_percent else all_values
        if not any(abs(value - a) <= _TOLERANCE for a in allowed):
            bad.append(token)
    return bad


def _allowed_values(evidence: list[Evidence]) -> set[float]:
    """Every number written in the evidence text, value, section or source name."""
    values: set[float] = set()
    for item in evidence:
        pieces = [item.text or "", item.section or "", item.source_file or ""]
        if isinstance(item.value, (int, float)) and not isinstance(item.value, bool):
            values.add(abs(float(item.value)))
        elif isinstance(item.value, str):
            pieces.append(item.value)
        for _, value, _ in _numbers(" ".join(pieces)):
            values.add(value)
    return values


def _numbers(text: str) -> list[tuple[str, float, bool]]:
    """(token, absolute value, is_percent) for every number token in text."""
    found: list[tuple[str, float, bool]] = []
    for match in _NUMBER_RE.finditer(text):
        sign, dollar, digits, percent = match.groups()
        try:
            value = abs(float(digits.replace(",", "")))
        except ValueError:
            continue
        found.append((match.group(0).strip(), value, bool(percent)))
    return found


def _strip_ids(text: str, evidence: list[Evidence]) -> str:
    """Remove evidence IDs and initiative IDs so their digits are not checked as numbers."""
    for evidence_id in sorted({e.evidence_id for e in evidence}, key=len, reverse=True):
        text = text.replace(evidence_id, " ")
    text = re.sub(r"\[[^\]]{1,80}\]", " ", text)  # any bracketed citation marker
    return _INITIATIVE_ID_RE.sub(" ", text)


def _fallback(draft: Answer) -> Answer:
    """The exact no-evidence answer, keeping the route for display."""
    return Answer(status="insufficient_evidence", text=config.FALLBACK_TEXT, route=draft.route)

