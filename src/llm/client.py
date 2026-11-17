"""The ONLY gateway to LLMs: Gemini -> Sarvam -> extractive fallback.

Owner: M3 (see CLAUDE.md). Public functions here are listed in CLAUDE.md section 5.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel

logger = logging.getLogger(__name__)


def generate_json(prompt: str, schema: type[BaseModel]) -> BaseModel:
    """Return the model response parsed into schema. Tries Gemini, then Sarvam, then an
    extractive (no-LLM) fallback. Never raises to callers. Keys via config.get_secret()."""
    raise NotImplementedError("M3: generate_json")
