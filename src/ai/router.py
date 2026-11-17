"""HLD 4: question router (numeric / narrative / mixed / out_of_scope).

Owner: M3 (see CLAUDE.md). Public functions here are listed in CLAUDE.md section 5.
"""
from __future__ import annotations

import logging

from src.contracts import RouteDecision

logger = logging.getLogger(__name__)


def route(question: str, initiative_ids: list[str]) -> RouteDecision:
    """Classify the question and extract the initiatives and metrics it refers to."""
    raise NotImplementedError("M3: route")
