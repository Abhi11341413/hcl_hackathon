"""Weekly Report page. Owner: M4 (see CLAUDE.md).

Builds the weekly executive report from the scorecard and shows it as markdown.
"""
import logging

import streamlit as st

from src import config
from src.report.weekly import build_weekly_report
from src.scorecard.store import load_scorecard

logger = logging.getLogger(__name__)

st.title("Weekly Report")
if st.button("Generate weekly report", type="primary"):
    try:
        report = build_weekly_report(load_scorecard(config.DB_PATH))
        st.markdown(report.markdown)
        st.download_button("Download (.md)", report.markdown, file_name=f"weekly_report_{report.report_date}.md")
    except NotImplementedError as exc:
        st.warning(f"Not implemented yet: {exc}")
