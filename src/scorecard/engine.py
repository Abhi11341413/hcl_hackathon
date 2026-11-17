"""HLD 2: deterministic scorecard engine (seven metrics + status). No LLM.

Owner: M1 (see CLAUDE.md). Public functions here are listed in CLAUDE.md section 5.
"""
from __future__ import annotations

import logging

from src.contracts import InitiativeRecord, ScorecardRow

logger = logging.getLogger(__name__)


def compute_scorecard(records: list[InitiativeRecord]) -> list[ScorecardRow]:
    """Compute adoption, WAU change, ROI, avg monthly benefit, payback, run-rate vs plan
    and status for every record, using the formulas in problem statement 2b section 4."""
    raise NotImplementedError("M1: compute_scorecard")
