"""Evaluation summary: scorecard correctness, retrieval, groundedness, citations, no-answer.

Owner: M4 (see CLAUDE.md). Public functions here are listed in CLAUDE.md section 5.
"""
from __future__ import annotations

import logging

from pathlib import Path

logger = logging.getLogger(__name__)


def run_evaluation(truth_dir: Path) -> dict[str, float]:
    """Compare system outputs with data/truth (expected_scorecard.csv, planted_issues.json,
    eval_questions.csv) and return metric name -> score."""
    raise NotImplementedError("M4: run_evaluation")
