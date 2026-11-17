"""Portfolio Dashboard page. Owner: M4 (see CLAUDE.md).

Shows the governed scorecard (from M1 load_scorecard) with Green/Amber/Red status.
"""
import logging

import streamlit as st

from src import config
from src.scorecard.store import load_scorecard

logger = logging.getLogger(__name__)

st.title("Portfolio Dashboard")
try:
    rows = load_scorecard(config.DB_PATH)
    if not rows:
        st.info("No scorecard yet. Use 'Build / refresh data' on the home page.")
    else:
        st.dataframe([r.model_dump(exclude={"inputs"}) for r in rows], use_container_width=True)
except NotImplementedError:
    st.warning("Scorecard store not implemented yet (M1).")
