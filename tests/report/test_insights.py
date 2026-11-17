"""Tests for src.report.insights and the week-aware report builder (owner: M4)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import src.ai.answer as ai_answer
import src.charters.retriever as charter_retriever
import src.scorecard.store as scorecard_store
from src import config
from src.contracts import Answer, Citation, Evidence, ScorecardRow
from src.data.loaders import load_and_clean
from src.report import insights
from src.report.weekly import build_report_for_date, build_weekly_report
from src.scorecard.engine import compute_scorecard

PAGES = Path(__file__).resolve().parents[2] / "pages"


@pytest.fixture(scope="module")
def rows() -> list[ScorecardRow]:
    return compute_scorecard(load_and_clean(config.SEED_DIR).records)


def by_id(rows: list[ScorecardRow], initiative_id: str) -> ScorecardRow:
    return next(r for r in rows if r.initiative_id == initiative_id)


def test_latest_week_returns_governed_rows(rows):
    assert insights.scorecard_as_of_week(rows, insights.LATEST_WEEK) == rows


def test_earlier_week_rescored_by_m1(rows):
    week1, week2 = insights.WEEKS[0], insights.WEEKS[1]
    for week, n in ((week1, 1), (week2, 2)):
        out = insights.scorecard_as_of_week(rows, week)
        for r in out:
            base = by_id(rows, r.initiative_id).inputs
            wau = (base.wau_week1, base.wau_week2, base.wau_week3)[n - 1]
            assert r.inputs.wau_week3 == wau
            assert r.adoption == pytest.approx(wau / base.licensed_users)
            assert r.roi == by_id(rows, r.initiative_id).roi  # financials do not change by week
    assert all(r.wau_change == 0 for r in insights.scorecard_as_of_week(rows, week1))


def test_unknown_week_rejected(rows):
    with pytest.raises(ValueError):
        insights.scorecard_as_of_week(rows, "2020-01-01")
    assert insights.scorecard_as_of_week([], "2020-01-01") == []


def test_report_for_date_uses_week_and_default_unchanged(rows):
    week = insights.WEEKS[1]
    report = build_report_for_date(insights.scorecard_as_of_week(rows, week), date.fromisoformat(week))
    assert report.report_date.isoformat() == week and week in report.markdown
    assert "over the three weeks" not in report.markdown
    assert build_weekly_report(rows).report_date.isoformat() == config.REPORT_DATE


def test_insights_explain_status_with_row_values(rows):
    red = by_id(rows, "NIM-04")
    notes = insights.initiative_insights(red)
    assert notes[0].startswith("Red:")
    assert any("28.8%" in n or "28.7%" in n for n in notes)
    green = insights.initiative_insights(by_id(rows, "NIM-10"))
    assert green[0].startswith("Green:") and len(green) == len(set(green))


@pytest.fixture
def fakes(monkeypatch, rows):
    monkeypatch.setattr(scorecard_store, "load_scorecard", lambda db_path: rows)
    monkeypatch.setattr(scorecard_store, "lookup", lambda ids, metrics, db: [
        Evidence(evidence_id="SC-NIM-01-adoption", kind="scorecard", initiative_id="NIM-01", text="x",
                 metric="adoption", value=0.6889, source_file="scorecard.db")])
    monkeypatch.setattr(charter_retriever, "retrieve", lambda q, ids, k: [
        Evidence(evidence_id="charter:NIM-07:s6:1", kind="charter", initiative_id="NIM-07", text="Risk text",
                 source_file="NIM-07_ATS_charter.pdf", section="6. Risks", score=0.71)])
    monkeypatch.setattr(ai_answer, "answer_question", lambda q: Answer(
        status="answered", text="ok", route="numeric",
        citations=[Citation(evidence_id="SC-NIM-01-adoption", claim="ok")]))


def test_weekly_report_page_week_dropdown(fakes):
    at = AppTest.from_file(str(PAGES / "3_Weekly_Report.py"), default_timeout=60).run()
    at.selectbox[0].set_value(insights.WEEKS[0]).run()
    at.button[0].click().run()
    assert not at.exception
    assert any(insights.WEEKS[0] in m.value for m in at.markdown)
    assert len(at.dataframe) == 1  # week-over-week view


def test_dashboard_insights_tab(fakes, monkeypatch):
    import src.data.loaders as loaders
    from src.contracts import CleanResult

    monkeypatch.setattr(loaders, "load_and_clean", lambda seed: CleanResult(records=[], change_log=[]))
    at = AppTest.from_file(str(PAGES / "1_Portfolio_Dashboard.py"), default_timeout=60).run()
    assert not at.exception
    assert any(m.value.startswith("### ") for m in at.markdown)


@pytest.mark.parametrize("question, route", [
    ("What is the adoption rate of PHIS?", "numeric"),
    ("What is the latest CIO risk rating for ATS and what did the CIO say?", "narrative"),
    ("What will the portfolio ROI be next year?", "out_of_scope"),
])
def test_decision_flow_page(fakes, question, route):
    at = AppTest.from_file(str(PAGES / "4_Decision_Flow.py"), default_timeout=60).run()
    at.text_input[0].set_value(question).run()
    assert not at.exception
    assert at.metric[0].value == route


def test_decision_flow_page_refusal(fakes):
    at = AppTest.from_file(str(PAGES / "4_Decision_Flow.py"), default_timeout=60).run()
    at.text_input[0].set_value("What is the email address of Meera Sethi?").run()
    assert not at.exception and at.warning
