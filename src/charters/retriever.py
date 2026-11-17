"""HLD 5b: charter retriever over the ChromaDB index.

Owner: M2 (see CLAUDE.md). Public functions here are listed in CLAUDE.md section 5.
"""
from __future__ import annotations

import logging

from src.contracts import Evidence

logger = logging.getLogger(__name__)


def retrieve(query: str, initiative_ids: list[str] | None, k: int) -> list[Evidence]:
    """Return the k best charter chunks as Evidence (kind="charter"), filtered to
    initiative_ids when given, dropping results below config.MIN_RETRIEVAL_SCORE."""
    raise NotImplementedError("M2: retrieve")
