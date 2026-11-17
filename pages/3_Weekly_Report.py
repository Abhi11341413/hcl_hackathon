"""Weekly Report page. Owner: M4 (see CLAUDE.md).

Pick a reporting week; the scorecard is re-scored as of that week by M1's compute_scorecard
(via src.report.insights) and the executive report is built for it, with a week-over-week
view, each attention item's citations and a markdown download.
"""
import logging
from datetime import date

import streamlit as st

from src import config
from src.contracts import ScorecardRow
from src.report.insights import LATEST_WEEK, WEEKS, scorecard_as_of_week, wau_for_week
from src.report.weekly import STATUS_ICON, build_report_for_date, format_pct, label
from src.scorecard import store as scorecard_store

logger = logging.getLogger(__name__)

st.set_page_config(page_title="Weekly Report", layout="wide")
st.title("Weekly Report")

week = st.selectbox("Reporting week ending", list(WEEKS), index=len(WEEKS) - 1,
                    format_func=lambda w: f"{w} (latest)" if w == LATEST_WEEK else w)
st.caption(f"Week ending {week} · initiatives needing attention, every figure traceable")
if week != LATEST_WEEK:
    st.info("Adoption, WAU change and status are re-scored for this week. Cost and benefit figures are only "
            f"supplied as at {config.REPORT_DATE}, so ROI, payback, monthly benefit and run-rate do not change by week.")


def load_rows() -> list[ScorecardRow] | None:
    """Governed scorecard rows, or None (after showing a message) when unavailable."""
    try:
        rows = scorecard_store.load_scorecard(config.DB_PATH)
    except NotImplementedError as exc:
        st.warning(f"Not implemented yet: {exc}")
        return None
    except Exception as exc:
        logger.exception("load_scorecard failed")
        st.error(f"Could not load the scorecard: {exc}")
        return None
    if not rows:
        st.info("No scorecard yet. Use **Build / refresh data** on the home page.")
        return None
    return rows


def week_table(latest: list[ScorecardRow], week_rows: list[ScorecardRow], week: str) -> list[dict]:
    """WAU per week (up to the selected week), adoption and status for the week vs latest."""
    by_id = {r.initiative_id: r for r in latest}
    table = []
    for r in sorted(week_rows, key=lambda x: x.initiative_id):
        base = by_id[r.initiative_id]
        line = {"Initiative": label(r)}
        for w in WEEKS:
            line[f"WAU {w}"] = f"{wau_for_week(base.inputs, w):,}" if w <= week else "-"
        line[f"Adoption ({week})"] = format_pct(r.adoption)
        line[f"Status ({week})"] = f"{STATUS_ICON[r.status]} {r.status}"
        line[f"Status ({LATEST_WEEK})"] = f"{STATUS_ICON[base.status]} {base.status}"
        table.append(line)
    return table


if st.button("Generate weekly report", type="primary"):
    rows = load_rows()
    if rows is not None:
        try:
            week_rows = scorecard_as_of_week(rows, week)
            st.session_state.report = build_report_for_date(week_rows, date.fromisoformat(week))
            st.session_state.report_table = week_table(rows, week_rows, week)
        except Exception as exc:
            logger.exception("weekly report failed")
            st.error(f"Could not build the report: {exc}")

report = st.session_state.get("report")
if report and report.report_date.isoformat() != week:
    st.warning(f"Showing the report for week ending {report.report_date.isoformat()}. "
               "Press **Generate weekly report** to build it for the selected week.")
if report:
    c1, c2, c3 = st.columns(3)
    for col, status in zip((c1, c2, c3), ("Green", "Amber", "Red")):
        col.metric(f"{STATUS_ICON[status]} {status}", report.status_counts.get(status, 0))
    st.download_button("Download report (.md)", report.markdown,
                       file_name=f"weekly_report_{report.report_date.isoformat()}.md", mime="text/markdown")
    if st.session_state.get("report_table"):
        with st.expander("Week-over-week view", expanded=True):
            st.dataframe(st.session_state.report_table, width="stretch", hide_index=True)
    st.markdown(report.markdown)
    if report.items:
        with st.expander("Citations by initiative"):
            for item in report.items:
                st.markdown(f"**{item.initiative_id}** ({item.status})")
                for c in item.citations:
                    st.markdown(f"- `{c.evidence_id}`: {c.claim}")
