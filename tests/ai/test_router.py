"""Tests for src.ai.router (owner: M3). LLM is mocked."""
from __future__ import annotations

from pathlib import Path

import pytest

import src.ai.router as router
import src.llm.client as llm
from src import config
from src.contracts import RouteDecision

CATALOGUE = {
    "NIM-01": ["PHIS"], "NIM-02": ["IA CoE"], "NIM-03": ["RBIS"], "NIM-04": ["EPS"],
    "NIM-05": ["DACoE"], "NIM-06": ["DCC Aidan"], "NIM-07": ["ATS"], "NIM-08": ["StateChat"],
    "NIM-09": ["DHS GenAI Chat"], "NIM-10": ["SOII Autocoder"],
}


@pytest.fixture(autouse=True)
def fixed_catalogue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(router, "initiative_catalogue", lambda: {k: list(v) for k, v in CATALOGUE.items()})


@pytest.mark.parametrize(
    ("question", "expected_route", "ids", "metric"),
    [
        ("What is the adoption rate of PHIS?", "numeric", ["NIM-01"], "adoption"),
        ("What is the payback period for RBIS?", "numeric", ["NIM-03"], "payback_months"),
        ("Which initiatives are Red?", "numeric", [], "status"),
        ("What is the latest CIO risk rating for ATS and what did the CIO say?", "narrative", ["NIM-07"], None),
        ("What is StateChat and what does it produce?", "narrative", ["NIM-08"], None),
        ("Why does EPS need attention and what risks does its charter record?", "mixed", ["NIM-04"], "status"),
        ("Summarise the DHS GenAI chatbot: status, ROI and stakeholder feedback.", "mixed", ["NIM-09"], "roi"),
        ("What will the portfolio ROI be next year?", "out_of_scope", [], None),
        ("If we doubled ATS licences, what would adoption be?", "out_of_scope", ["NIM-07"], None),
        ("What is the average adoption across the whole portfolio?", "out_of_scope", [], None),
    ],
)
def test_rule_routes(question: str, expected_route: str, ids: list[str], metric: str | None) -> None:
    decision = router.route(question, list(CATALOGUE))
    assert decision.route == expected_route
    assert decision.initiative_ids == ids
    if metric:
        assert metric in decision.metrics


def test_short_alias_needs_whole_word() -> None:
    assert router.find_initiatives("show me the stats", CATALOGUE, None) == []
    assert router.find_initiatives("nim-7 and NIM-10", CATALOGUE, None) == ["NIM-07", "NIM-10"]


def test_empty_question_is_out_of_scope() -> None:
    assert router.route("   ", []).route == "out_of_scope"


def test_no_signal_uses_llm_and_filters_its_output(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(prompt: str, schema: type) -> RouteDecision:
        assert "QUESTION:" in prompt and "NIM-01" in prompt
        return RouteDecision(route="numeric", initiative_ids=["NIM-01", "NIM-99"], metrics=["roi", "made_up"])

    monkeypatch.setattr(llm, "generate_json", fake)
    decision = router.route("Tell me something interesting", list(CATALOGUE))
    assert decision.route == "numeric"
    assert decision.initiative_ids == ["NIM-01"] and decision.metrics == ["roi"]


def test_catalogue_falls_back_to_charter_file_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()  # use the real initiative_catalogue
    (tmp_path / "NIM-09_DHS_GenAI_Chat_charter.pdf").write_bytes(b"")
    (tmp_path / "notes.txt").write_text("x")
    monkeypatch.setattr(config, "CHARTER_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "missing.db")
    router.clear_catalogue_cache()
    try:
        assert router.initiative_catalogue()["NIM-09"] == ["DHS GenAI Chat"]
    finally:
        router.clear_catalogue_cache()
