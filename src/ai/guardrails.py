"""HLD 7: guardrail validator (numbers, citations, injections, personal data).

Owner: M3 (see CLAUDE.md). Public functions here are listed in CLAUDE.md section 5.
"""
from __future__ import annotations

import logging

from src.contracts import Answer, Evidence, GuardrailResult

logger = logging.getLogger(__name__)


def check_input(question: str) -> Answer | None:
    """Return a refusal Answer for disallowed requests (e.g. personal details), else None."""
    raise NotImplementedError("M3: check_input")


def validate(draft: Answer, evidence: list[Evidence]) -> GuardrailResult:
    """Block any number not present in scorecard evidence and any citation that does not
    resolve to an evidence_id; replace with config.FALLBACK_TEXT when unsupported."""
    raise NotImplementedError("M3: validate")
