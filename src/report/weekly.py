"""Executive report generator (weekly report).

Owner: M4 (see CLAUDE.md). Public functions here are listed in CLAUDE.md section 5.
"""
from __future__ import annotations

import logging

from src.contracts import ScorecardRow, WeeklyReport

logger = logging.getLogger(__name__)


def build_weekly_report(rows: list[ScorecardRow]) -> WeeklyReport:
    """Summarise portfolio performance, list Amber/Red initiatives with reasons, and cite
    scorecard values (and charter evidence via M2 retrieve) for every statement."""
    raise NotImplementedError("M4: build_weekly_report")
