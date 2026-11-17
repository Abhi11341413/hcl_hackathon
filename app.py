"""Streamlit entry point. SHARED FILE: agents must not edit (see CLAUDE.md, rule 2).

Home page + build-time pipeline trigger. Feature pages live in pages/ (owned by M4).
Run: streamlit run app.py
"""
from __future__ import annotations

import logging

import streamlit as st

from src import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("app")

st.set_page_config(page_title="AI Value Intelligence", layout="wide")


def run_build() -> list[str]:
    """Build time (HLD): clean -> scorecard -> SQLite, and charters -> ChromaDB. Returns status lines."""
    from src.charters.indexer import build_index
    from src.data.loaders import load_and_clean
    from src.scorecard.engine import compute_scorecard
    from src.scorecard.store import save_scorecard

    config.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    try:
        clean = load_and_clean(config.SEED_DIR)
        rows = compute_scorecard(clean.records)
        save_scorecard(rows, config.DB_PATH)
        lines.append(f"Scorecard: {len(rows)} initiatives, {len(clean.change_log)} change-log entries")
    except NotImplementedError as exc:
        lines.append(f"Scorecard path not implemented yet: {exc}")
    except Exception as exc:  # surface, never crash the home page
        logger.exception("scorecard build failed")
        lines.append(f"Scorecard build failed: {exc}")
    try:
        stats = build_index(config.CHARTER_DIR, config.CHROMA_DIR)
        lines.append(f"Charter index: {stats.files_indexed} files, {stats.chunks_written} chunks")
    except NotImplementedError as exc:
        lines.append(f"Charter path not implemented yet: {exc}")
    except Exception as exc:
        logger.exception("charter index build failed")
        lines.append(f"Charter index failed: {exc}")
    return lines


st.title("Enterprise RAG Value Intelligence Assistant")
st.caption("Code computes the numbers, retrieval finds the text, the LLM only explains.")
st.markdown(
    "- **Portfolio Dashboard**: governed scorecard with Green/Amber/Red status\n"
    "- **AI Chat**: numeric, narrative and mixed questions with sources\n"
    "- **Weekly Report**: initiatives needing attention, every figure traceable"
)
st.info(f"Data folder: `{config.SEED_DIR.relative_to(config.ROOT)}` | Reporting week ending {config.REPORT_DATE}")

if st.button("Build / refresh data", type="primary"):
    with st.spinner("Cleaning data, computing scorecard, indexing charters..."):
        for line in run_build():
            st.write(line)
