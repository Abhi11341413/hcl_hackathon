"""Render tests for the M4 Streamlit pages (AppTest), with other members' functions faked."""
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import src.ai.answer as ai_answer
import src.charters.retriever as charter_retriever
import src.data.loaders as data_loaders
import src.scorecard.store as scorecard_store
from src import config
from src.contracts import (Answer, ChangeLogEntry, Citation, CleanResult, Evidence, InitiativeRecord,
                           ScorecardRow)
from src.eval import run_eval

PAGES = Path(__file__).resolve().parents[2] / "pages"


def truth_rows(truth_dir: Path) -> list[ScorecardRow]:
    inputs = pd.read_csv(truth_dir / "expected_clean_inputs.csv").fillna("")
    score = pd.read_csv(truth_dir / "expected_scorecard.csv").set_index("initiative_id")
    out = []
    for rec in inputs.to_dict("records"):
        s = score.loc[rec["initiative_id"]]
        out.append(ScorecardRow(
            initiative_id=rec["initiative_id"], initiative_name=rec["initiative_name"], short_name=rec["short_name"],
            adoption=s.adoption, wau_change=s.wau_change, roi=s.roi, avg_monthly_benefit=s.avg_monthly_benefit_usd,
            payback_months=s.payback_months, run_rate_vs_plan=s.run_rate_vs_plan, status=s.status,
            inputs=InitiativeRecord(**rec)))
    return out


@pytest.fixture
def fakes(monkeypatch, tmp_path, truth_dir):
    rows = truth_rows(truth_dir)
    monkeypatch.setattr(scorecard_store, "load_scorecard", lambda db_path: rows)
    monkeypatch.setattr(data_loaders, "load_and_clean", lambda seed_dir: CleanResult(
        records=[r.inputs for r in rows],
        change_log=[ChangeLogEntry(issue_id="PL-USE-04", file="usage_weekly.csv", initiative_id="NIM-05", rule="drop duplicate")]))
    monkeypatch.setattr(charter_retriever, "retrieve", lambda q, ids, k: [])
    monkeypatch.setattr(run_eval, "SUMMARY_PATH", tmp_path / "eval_summary.json")
    return rows


def run(page: str) -> AppTest:
    at = AppTest.from_file(str(PAGES / page), default_timeout=30)
    return at.run()


def test_dashboard_renders_scorecard(fakes):
    at = run("1_Portfolio_Dashboard.py")
    assert not at.exception
    assert [m.value for m in at.metric][:4] == ["10", "4", "3", "3"]
    assert len(at.dataframe) >= 2  # scorecard + source inputs (+ change log tab)


def test_dashboard_handles_unimplemented_store(monkeypatch):
    def nope(db_path):
        raise NotImplementedError("M1")
    monkeypatch.setattr(scorecard_store, "load_scorecard", nope)
    at = run("1_Portfolio_Dashboard.py")
    assert not at.exception
    assert any("not implemented" in w.value for w in at.warning)


def test_weekly_report_page_generates(fakes):
    at = run("3_Weekly_Report.py")
    at.button[0].click().run()
    assert not at.exception
    assert any("Initiatives requiring attention" in m.value for m in at.markdown)


def test_chat_shows_answer_with_sources(fakes, monkeypatch):
    ev = Evidence(evidence_id="scorecard:NIM-04:adoption", kind="scorecard", initiative_id="NIM-04",
                  text="adoption", metric="adoption", value=0.2875, source_file="scorecard")
    monkeypatch.setattr(ai_answer, "answer_question", lambda q: Answer(
        status="answered", text="EPS adoption is 28.8%.", route="numeric", evidence=[ev],
        citations=[Citation(evidence_id=ev.evidence_id, claim="adoption")]))
    at = run("2_AI_Chat.py")
    at.chat_input[0].set_value("What is the adoption rate of EPS?").run()
    assert not at.exception
    assert any("28.8%" in m.value for m in at.markdown)


def test_chat_no_evidence_uses_exact_fallback(fakes, monkeypatch):
    monkeypatch.setattr(ai_answer, "answer_question",
                        lambda q: Answer(status="insufficient_evidence", text="something else"))
    at = run("2_AI_Chat.py")
    at.chat_input[0].set_value("Which vendor built PHIS?").run()
    assert [i.value for i in at.info] == [config.FALLBACK_TEXT]
