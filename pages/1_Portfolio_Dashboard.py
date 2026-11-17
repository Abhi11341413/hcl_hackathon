"""Portfolio Dashboard page. Owner: M4 (see CLAUDE.md).

Tabs: governed scorecard (from M1 load_scorecard), the Data Quality and Assumptions Log
(from M1 load_and_clean), and the latest evaluation summary (M4 run_evaluation).
Numbers are ScorecardRow values, formatted only.
"""
import logging

import streamlit as st

from src import config
from src.data import loaders as data_loaders
from src.eval import run_eval
from src.report.weekly import STATUS_ICON, format_months, format_pct, format_usd, label
from src.scorecard import store as scorecard_store

logger = logging.getLogger(__name__)

st.set_page_config(page_title="Portfolio Dashboard", layout="wide")
st.title("Portfolio Dashboard")
st.caption(f"Governed scorecard · week ending {config.REPORT_DATE} · every figure computed by deterministic code")


@st.cache_data(show_spinner=False)
def _change_log(seed_marker: float) -> list[dict]:
    """M1 change log as plain dicts (cached per seed-folder modification time)."""
    return [e.model_dump() for e in data_loaders.load_and_clean(config.SEED_DIR).change_log]


def _seed_marker() -> float:
    files = list(config.SEED_DIR.glob("*.*"))
    return max((f.stat().st_mtime for f in files), default=0.0)


tab_score, tab_dq, tab_eval = st.tabs(["Scorecard", "Data quality log", "Evaluation"])

with tab_score:
    try:
        rows = scorecard_store.load_scorecard(config.DB_PATH)
    except NotImplementedError:
        rows = None
        st.warning("Scorecard store is not implemented yet (M1).")
    except Exception as exc:
        rows = None
        logger.exception("load_scorecard failed")
        st.error(f"Could not load the scorecard: {exc}")

    if rows is not None and not rows:
        st.info("No scorecard yet. Use **Build / refresh data** on the home page.")
    elif rows:
        counts = {s: sum(r.status == s for r in rows) for s in ("Green", "Amber", "Red")}
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Initiatives", len(rows))
        c2.metric(f"{STATUS_ICON['Green']} Green", counts["Green"])
        c3.metric(f"{STATUS_ICON['Amber']} Amber", counts["Amber"])
        c4.metric(f"{STATUS_ICON['Red']} Red", counts["Red"])

        chosen = st.multiselect("Filter by status", ["Red", "Amber", "Green"], default=["Red", "Amber", "Green"])
        shown = [r for r in rows if r.status in chosen]
        st.dataframe(
            [{"Initiative": label(r), "Type": r.inputs.initiative_type, "Status": f"{STATUS_ICON[r.status]} {r.status}",
              "Adoption": format_pct(r.adoption), "WAU change": format_pct(r.wau_change), "ROI": format_pct(r.roi),
              "Avg monthly benefit": format_usd(r.avg_monthly_benefit), "Payback (months)": format_months(r.payback_months),
              "Run-rate vs plan": format_pct(r.run_rate_vs_plan)} for r in shown],
            width="stretch", hide_index=True)

        st.subheader("Source inputs")
        pick = st.selectbox("Initiative", [label(r) for r in shown] or ["-"])
        row = next((r for r in shown if label(r) == pick), None)
        if row:
            i = row.inputs
            st.markdown(f"**{i.initiative_name}** · {i.agency} · charter: `{i.charter_file or 'n/a'}`")
            st.dataframe([
                {"Input": "Go-live date", "Value": i.go_live_date.isoformat()},
                {"Input": "Months live", "Value": str(i.months_live)},
                {"Input": "Licensed users", "Value": f"{i.licensed_users:,}"},
                {"Input": "WAU week 1 / 2 / 3", "Value": f"{i.wau_week1:,} / {i.wau_week2:,} / {i.wau_week3:,}"},
                {"Input": "Total cost to date", "Value": format_usd(i.total_cost_to_date_usd)},
                {"Input": "Realised benefit to date", "Value": format_usd(i.realised_benefit_to_date_usd)},
                {"Input": "Planned annual benefit", "Value": format_usd(i.planned_annual_benefit_usd)},
            ], width="stretch", hide_index=True)

with tab_dq:
    st.caption("Every correction and standardisation applied to the supplied spreadsheets (FR-02).")
    try:
        log = _change_log(_seed_marker())
        if log:
            st.dataframe(log, width="stretch", hide_index=True)
        else:
            st.info("The change log is empty.")
    except NotImplementedError:
        st.warning("Data cleaning is not implemented yet (M1).")
    except Exception as exc:
        logger.exception("change log failed")
        st.error(f"Could not build the change log: {exc}")

with tab_eval:
    summary = run_eval.read_summary()
    if summary:
        st.caption(f"Last run: {summary['generated_at']}")
        st.dataframe([{"Metric": k, "Score": f"{v:.3f}"} for k, v in summary["metrics"].items()],
                     width="stretch", hide_index=True)
        if summary.get("skipped"):
            st.warning("Skipped steps: " + "; ".join(f"{k}: {v}" for k, v in summary["skipped"].items()))
    else:
        st.info("No evaluation has been run yet.")
    if st.button("Run evaluation", help="Runs the full pipeline on data/truth questions; calls the LLM."):
        with st.spinner("Evaluating..."):
            run_eval.run_evaluation(config.TRUTH_DIR)
        st.rerun()
