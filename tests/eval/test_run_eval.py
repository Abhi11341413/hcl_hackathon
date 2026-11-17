"""Tests for src/eval/run_eval.py (owner: M4). All other members' functions are faked; no LLM calls."""
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import src.ai.answer as ai_answer
import src.ai.guardrails as ai_guardrails
import src.ai.router as ai_router
import src.charters.retriever as charter_retriever
import src.data.loaders as data_loaders
import src.scorecard.engine as scorecard_engine
from src import config
from src.contracts import (Answer, ChangeLogEntry, Citation, CleanResult, Evidence, InitiativeRecord,
                           RouteDecision, ScorecardRow)
from src.eval import run_eval


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
def truth(truth_dir):
    t = run_eval.load_truth(truth_dir)
    t["scorecard"] = t["scorecard"].rename(columns={"avg_monthly_benefit_usd": "avg_monthly_benefit"})
    return t


# ---------------------------------------------------------------- pure helpers
def test_compare_scorecard_perfect(truth_dir, truth):
    m = run_eval.compare_scorecard(truth_rows(truth_dir), truth["scorecard"])
    assert m == {"scorecard_coverage": 1.0, "scorecard_value_accuracy": 1.0, "status_accuracy": 1.0}


def test_compare_scorecard_detects_wrong_status_and_missing_row(truth_dir, truth):
    rows = truth_rows(truth_dir)
    rows[0] = rows[0].model_copy(update={"status": "Red", "roi": 9.9})
    m = run_eval.compare_scorecard(rows[:-1], truth["scorecard"])
    assert m["scorecard_coverage"] == 0.9
    assert m["status_accuracy"] == 0.8
    assert m["scorecard_value_accuracy"] < 1.0


def test_data_quality_recall():
    issues = [{"id": "PL-USE-04", "file": "usage_weekly.csv", "initiative_id": "NIM-05"},
              {"id": "PL-FIN-06", "file": "financials.xlsx", "initiative_id": "NIM-05"},
              {"id": "PL-CH-01", "file": "x_charter.docx", "initiative_id": "NIM-04"}]
    log = [ChangeLogEntry(issue_id="dup-1", file="data/seed/usage_weekly.csv", initiative_id="NIM-05", rule="drop duplicate")]
    assert run_eval.data_quality_recall(log, issues) == 0.5
    assert run_eval.data_quality_recall([], issues) == 0.0


def test_extract_numbers_ignores_ids_and_dates():
    assert run_eval.extract_numbers("NIM-04 on 2026-11-13: adoption 28.8%, cost $71,153,922") == [28.8, 71153922.0]


def _answer(text, value=0.2875, cite="scorecard:NIM-04:adoption"):
    ev = Evidence(evidence_id="scorecard:NIM-04:adoption", kind="scorecard", initiative_id="NIM-04",
                  text="adoption", metric="adoption", value=value, source_file="scorecard")
    return Answer(status="answered", text=text, citations=[Citation(evidence_id=cite, claim="c")], evidence=[ev])


def test_grounding_and_citations():
    assert run_eval.is_grounded(_answer("EPS adoption is 28.8% (NIM-04)."))
    assert not run_eval.is_grounded(_answer("EPS adoption is 45.0%."))
    assert run_eval.citations_resolve(_answer("x"))
    assert not run_eval.citations_resolve(_answer("x", cite="missing"))


def test_expected_numbers_present():
    assert run_eval.expected_numbers_present("28.8%", "Adoption is 28.8%.")
    assert not run_eval.expected_numbers_present("28.8%", "Adoption is low.")


# ---------------------------------------------------------------- run_evaluation
def _fake_pipeline(monkeypatch, truth_dir):
    rows = truth_rows(truth_dir)
    by_name = {r.short_name.lower(): r for r in rows}
    monkeypatch.setattr(data_loaders, "load_and_clean",
                        lambda seed_dir: CleanResult(records=[r.inputs for r in rows], change_log=[]))
    monkeypatch.setattr(scorecard_engine, "compute_scorecard", lambda records: rows)
    monkeypatch.setattr(ai_router, "route", lambda q, ids: RouteDecision(route="numeric"))
    monkeypatch.setattr(charter_retriever, "retrieve", lambda q, ids, k: [])
    monkeypatch.setattr(ai_guardrails, "check_input", lambda q: None)

    def fake_answer(question):
        row = next((r for n, r in by_name.items() if n and n in question.lower()), None)
        if row is None:
            return Answer(status="insufficient_evidence", text=config.FALLBACK_TEXT)
        return _answer(f"Adoption is {row.adoption * 100:.1f}%.", value=row.adoption)

    monkeypatch.setattr(ai_answer, "answer_question", fake_answer)


def test_run_evaluation_with_fakes_writes_summary(monkeypatch, tmp_path, truth_dir):
    _fake_pipeline(monkeypatch, truth_dir)
    monkeypatch.setattr(run_eval, "SUMMARY_PATH", tmp_path / "eval_summary.json")
    metrics = run_eval.run_evaluation(truth_dir)
    assert metrics["status_accuracy"] == 1.0
    assert 0.0 <= metrics["router_accuracy"] <= 1.0
    assert "no_answer_accuracy" in metrics and "citation_validity" in metrics
    saved = run_eval.read_summary()
    assert saved["metrics"] == metrics and saved["skipped"] == {}


def test_run_evaluation_skips_unimplemented_steps(monkeypatch, tmp_path, truth_dir):
    def nope(*args, **kwargs):
        raise NotImplementedError("stub")
    for mod, fn in [(data_loaders, "load_and_clean"), (ai_router, "route"), (charter_retriever, "retrieve"),
                    (ai_answer, "answer_question"), (ai_guardrails, "check_input")]:
        monkeypatch.setattr(mod, fn, nope)
    monkeypatch.setattr(run_eval, "SUMMARY_PATH", tmp_path / "eval_summary.json")
    assert run_eval.run_evaluation(truth_dir) == {}
    assert set(run_eval.read_summary()["skipped"]) == {"scorecard", "routing", "retrieval", "answers", "input_guard"}


def test_run_evaluation_missing_truth_dir(tmp_path):
    assert run_eval.run_evaluation(tmp_path / "does-not-exist") == {}


def test_read_summary_absent(tmp_path):
    assert run_eval.read_summary(tmp_path / "none.json") is None
