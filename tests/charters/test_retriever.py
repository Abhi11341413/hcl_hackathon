"""Behaviour tests for src.charters.retriever.retrieve (owner: M2). Offline: fake embeddings."""
from pathlib import Path

import pytest

from src import config
from src.charters.retriever import hinted_sections, lexical_score, retrieve


def test_returns_charter_evidence_with_metadata(built_index) -> None:
    hits = retrieve("latest CIO risk rating", ["NIM-01"], k=3)
    assert 0 < len(hits) <= 3
    for ev in hits:
        assert ev.kind == "charter"
        assert ev.initiative_id == "NIM-01"
        assert ev.evidence_id.startswith("charter:NIM-01:")
        assert ev.source_file == "NIM-01_PHIS_charter.pdf"
        assert ev.section and ev.text
        assert ev.metric is None and ev.value is None
        assert config.MIN_RETRIEVAL_SCORE <= ev.score <= 1.0
    assert [e.score for e in hits] == sorted((e.score for e in hits), reverse=True)


def test_finds_expected_section(built_index) -> None:
    hits = retrieve("What did the latest operational analysis conclude?", ["NIM-03"], k=3)
    assert hits[0].section == "7. Latest Operational Analysis"


def test_filter_to_several_initiatives(built_index) -> None:
    hits = retrieve("benefit levers planned annual benefit", ["NIM-03", "NIM-06"], k=10)
    assert hits and {e.initiative_id for e in hits} <= {"NIM-03", "NIM-06"}


def test_no_filter_searches_whole_portfolio(built_index) -> None:
    hits = retrieve("Benefits Case planned annual benefit steady state", None, k=10)
    assert len({e.initiative_id for e in hits}) > 1


def test_k_limits_results(built_index) -> None:
    assert len(retrieve("risks", None, k=2)) <= 2


@pytest.mark.parametrize("query,k", [("", 3), ("   ", 3), ("risks", 0), ("risks", -1)])
def test_empty_query_or_bad_k_returns_nothing(built_index, query: str, k: int) -> None:
    assert retrieve(query, None, k) == []


def test_unknown_initiative_returns_nothing(built_index) -> None:
    assert retrieve("risks", ["NIM-99"], k=3) == []


def test_threshold_drops_weak_hits(built_index, monkeypatch) -> None:
    monkeypatch.setattr(config, "MIN_RETRIEVAL_SCORE", 0.999)
    assert retrieve("zebra quantum marmalade", None, k=5) == []


def test_missing_index_returns_nothing(tmp_path: Path, monkeypatch, fake_embeddings) -> None:
    monkeypatch.setattr(config, "CHROMA_DIR", tmp_path / "no_index")
    assert retrieve("risks", None, k=3) == []
    assert not (tmp_path / "no_index").exists()


def test_injection_text_is_returned_verbatim_as_data(built_index) -> None:
    hits = retrieve("stakeholder feedback pilot retrospective", ["NIM-09"], k=5)
    appendix = [e for e in hits if e.section.startswith("Appendix A")]
    assert appendix and appendix[0].kind == "charter"


@pytest.mark.parametrize("query,expected", [
    ("What is the latest CIO risk rating for PHIS?", {"6."}),
    ("What did the latest operational analysis conclude for RBIS?", {"7."}),
    ("Is RBIS on track against its planned benefit?", {"4."}),
    ("Summarise the stakeholder feedback", {"Appendix A"}),
    ("Who is the executive sponsor?", {"8."}),
    ("hello there", set()),
])
def test_hinted_sections(query: str, expected: set[str]) -> None:
    assert hinted_sections(query) == expected


def test_short_name_alias_is_searchable(built_index) -> None:
    hits = retrieve("DACoE", None, k=3)
    assert hits and hits[0].initiative_id == "NIM-05"


def test_section_hint_ranks_risk_section_first(built_index) -> None:
    hits = retrieve("Why does EPS need attention and what risks does its charter record?", ["NIM-04"], k=3)
    assert hits[0].section == "6. Risks and Governance"


def test_lexical_score() -> None:
    assert lexical_score("RBIS risk rating", "The RBIS CIO risk rating is 4") == 1.0
    assert lexical_score("RBIS risk", "nothing relevant") == 0.0
    assert lexical_score("the a of", "anything") == 0.0
