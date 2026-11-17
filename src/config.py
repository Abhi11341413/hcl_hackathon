"""Central configuration. SHARED FILE: agents must not edit (see CLAUDE.md, rule 2).

Model names and paths can be overridden with environment variables.
API keys are never stored here: use get_secret(), which reads env vars, then st.secrets.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ---- paths
DATA_DIR = ROOT / "data"
SEED_DIR = Path(os.getenv("SEED_DIR", DATA_DIR / "seed"))
CHARTER_DIR = SEED_DIR / "charters"
TRUTH_DIR = DATA_DIR / "truth"          # answer key: tests/eval only, never indexed
EVAL_DIR = DATA_DIR / "eval"
RUNTIME_DIR = Path(os.getenv("RUNTIME_DIR", DATA_DIR / "runtime"))
DB_PATH = RUNTIME_DIR / "scorecard.db"
CHROMA_DIR = RUNTIME_DIR / "chroma"
CHANGE_LOG_PATH = RUNTIME_DIR / "change_log.csv"

# ---- reporting period (problem statement: three supplied weeks)
REPORT_DATE = "2026-11-13"
REPORTING_WEEKS = ("2026-10-30", "2026-11-06", "2026-11-13")
FX_RATES_TO_USD = {"USD": 1.0}          # other rates are read from financials.xlsx › FX_and_Units

# ---- portfolio status thresholds (problem statement, section 4)
GREEN_MIN_ADOPTION = 0.60
RED_MAX_ADOPTION = 0.30                 # Red when adoption < this
ROI_ZERO = 0.0                          # Green needs ROI > 0; Red when ROI < 0
RATIO_DECIMALS = 10                     # round ratios before threshold tests

# ---- retrieval
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
CHROMA_COLLECTION = "charters"
TOP_K = int(os.getenv("TOP_K", "5"))
MIN_RETRIEVAL_SCORE = float(os.getenv("MIN_RETRIEVAL_SCORE", "0.30"))

# ---- LLM (Gemini -> Sarvam -> extractive fallback)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
SARVAM_MODEL = os.getenv("SARVAM_MODEL", "sarvam-m")
LLM_TEMPERATURE = 0.0
LLM_TIMEOUT_S = 30
LLM_MAX_RETRIES = 1

# ---- user-facing text
FALLBACK_TEXT = "I do not have that in the data provided."
REFUSAL_PII_TEXT = "I can't share personal details that are not part of the approved portfolio data."


def get_secret(name: str) -> str | None:
    """Return a secret from env vars first, then Streamlit secrets; None if absent."""
    value = os.getenv(name)
    if value:
        return value
    try:
        import streamlit as st
        return st.secrets.get(name)  # type: ignore[no-any-return]
    except Exception:
        return None
