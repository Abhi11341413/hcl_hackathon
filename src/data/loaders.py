"""HLD 1: load the seed spreadsheets and return clean records + change log.

Owner: M1 (see CLAUDE.md). Public functions here are listed in CLAUDE.md section 5.
"""
from __future__ import annotations

import logging

from pathlib import Path

from src.contracts import CleanResult

logger = logging.getLogger(__name__)


def load_and_clean(seed_dir: Path) -> CleanResult:
    """Read portfolio_register.xlsx, usage_weekly.csv and financials.xlsx from seed_dir,
    fix data-quality issues, normalise names/units/periods to USD, and log every change."""
    raise NotImplementedError("M1: load_and_clean")
