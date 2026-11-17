"""Weekly Report page. Owner: M4 (see CLAUDE.md).

Builds the weekly executive report from the scorecard and shows it as markdown,
with each attention item's citations and a markdown download.
"""
import logging

import streamlit as st

from src import config
from src.report.weekly import STATUS_ICON, build_weekly_report
from src.scorecard import store as scorecard_store

logger = logging.getLogger(__name__)

st.set_page_config(page_title="Weekly Report", layout="wide")
st.title("Weekly Report")
st.caption(f"Week ending {config.REPORT_DATE} · initiatives needing attention, every figure traceable")

if st.button("Generate weekly report", type="primary"):
    try:
        st.session_state.report = build_weekly_report(scorecard_store.load_scorecard(config.DB_PATH))
    except NotImplementedError as exc:
        st.warning(f"Not implemented yet: {exc}")
    except Exception as exc:
        logger.exception("weekly report failed")
        st.error(f"Could not build the report: {exc}")

report = st.session_state.get("report")
if report:
    c1, c2, c3 = st.columns(3)
    for col, status in zip((c1, c2, c3), ("Green", "Amber", "Red")):
        col.metric(f"{STATUS_ICON[status]} {status}", report.status_counts.get(status, 0))
    st.download_button("Download report (.md)", report.markdown,
                       file_name=f"weekly_report_{report.report_date.isoformat()}.md", mime="text/markdown")
    st.markdown(report.markdown)
    if report.items:
        with st.expander("Citations by initiative"):
            for item in report.items:
                st.markdown(f"**{item.initiative_id}** ({item.status})")
                for c in item.citations:
                    st.markdown(f"- `{c.evidence_id}`: {c.claim}")
