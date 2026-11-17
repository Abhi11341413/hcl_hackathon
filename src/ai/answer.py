"""Evidence aggregator + HLD 6 answer generator (orchestrates the question-time flow).

Owner: M3 (see CLAUDE.md). Public functions here are listed in CLAUDE.md section 5.
"""
from __future__ import annotations

import logging

from src.contracts import Answer

logger = logging.getLogger(__name__)


def answer_question(question: str) -> Answer:
    """check_input -> route -> scorecard lookup / charter retrieve -> aggregate evidence ->
    LLM draft -> guardrail validate. Returns the approved Answer (or the fallback)."""
    raise NotImplementedError("M3: answer_question")
