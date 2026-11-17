"""SQLite scorecard table + HLD 5a scorecard lookup.

Owner: M1 (see CLAUDE.md). Public functions here are listed in CLAUDE.md section 5.
"""
from __future__ import annotations

import logging

from pathlib import Path

from src.contracts import Evidence, ScorecardRow

logger = logging.getLogger(__name__)


def save_scorecard(rows: list[ScorecardRow], db_path: Path) -> None:
    """Write one row per initiative to the SQLite scorecard table (replace on rebuild)."""
    raise NotImplementedError("M1: save_scorecard")


def load_scorecard(db_path: Path) -> list[ScorecardRow]:
    """Read the full scorecard table; empty list if the database does not exist yet."""
    raise NotImplementedError("M1: load_scorecard")


def lookup(initiative_ids: list[str], metrics: list[str], db_path: Path) -> list[Evidence]:
    """Return exact scorecard values for the named initiatives/metrics as Evidence (kind="scorecard").
    Empty initiative_ids means all initiatives; empty metrics means all metrics."""
    raise NotImplementedError("M1: lookup")
