"""Unit tests for src.charters.chunker (owner: M2)."""
import pytest

from src.charters.chunker import (
    chunk_charter,
    initiative_id_from,
    is_heading,
    section_slug,
    split_sections,
    split_text,
)

LINES = [
    "NIM-04 - Enterprise Platform Services",
    "Nimbus Group AI Portfolio - Initiative Charter (hackathon demo data)",
    "1. Initiative Overview",
    "Initiative ID: NIM-04",
    "Go-live: March 2025",
    "6. Risks and Governance",
    "Programme risks: model output quality.",
    "Appendix A. Stakeholder Feedback (verbatim)",
    "\"Useful pilot.\"",
    "Source notes",
    "1. Initiative Overview: real",
]


@pytest.mark.parametrize("line,expected", [
    ("1. Initiative Overview", True),
    ("3. Governance Profile (AI Use Case Inventory responses)", True),
    ("Appendix A. Stakeholder Feedback (verbatim)", True),
    ("Source notes", True),
    ("Initiative ID: NIM-04", False),
    ("1. Initiative Overview: real", False),           # source-notes body line
    ("Date: 2024-08-10. Conclusion: initiate modernization.", False),
    ("", False),
])
def test_is_heading(line: str, expected: bool) -> None:
    assert is_heading(line) is expected


def test_split_sections_groups_lines_in_order() -> None:
    names = [name for name, _ in split_sections(LINES)]
    assert names == ["Title", "1. Initiative Overview", "6. Risks and Governance",
                     "Appendix A. Stakeholder Feedback (verbatim)", "Source notes"]


def test_split_sections_empty() -> None:
    assert split_sections([]) == []


@pytest.mark.parametrize("section,slug", [
    ("6. Risks and Governance", "s6"),
    ("10. Something", "s10"),
    ("Appendix A. Stakeholder Feedback (verbatim)", "appendix-a"),
    ("Source notes", "source-notes"),
])
def test_section_slug(section: str, slug: str) -> None:
    assert section_slug(section) == slug


def test_initiative_id_prefers_file_name_then_text() -> None:
    assert initiative_id_from("NIM-03_RBIS_charter.pdf", ["NIM-07"]) == "NIM-03"
    assert initiative_id_from("charter.pdf", ["x", "Initiative ID: NIM-07"]) == "NIM-07"
    assert initiative_id_from("charter.pdf", ["nothing here"]) is None


def test_split_text_respects_max_and_keeps_content() -> None:
    body = ["short line", "Sentence one is here. " * 30, "tail"]
    pieces = split_text(body, max_chars=100)
    assert pieces and all(0 < len(p) <= 100 for p in pieces)
    joined = " ".join(pieces)
    assert "short line" in joined and "tail" in joined


def test_split_text_hard_wraps_unbroken_text() -> None:
    pieces = split_text(["x" * 250], max_chars=100)
    assert [len(p) for p in pieces] == [100, 100, 50]


def test_split_text_rejects_bad_max() -> None:
    with pytest.raises(ValueError):
        split_text(["a"], max_chars=0)


def test_chunk_charter_metadata_and_skips() -> None:
    chunks = chunk_charter(LINES, source_file="NIM-04_EPS_charter.docx", initiative_id="NIM-04")
    assert [c.chunk_id for c in chunks] == ["NIM-04:s1:1", "NIM-04:s6:1", "NIM-04:appendix-a:1"]
    assert {c.section for c in chunks} == {"1. Initiative Overview", "6. Risks and Governance",
                                           "Appendix A. Stakeholder Feedback (verbatim)"}
    assert all(c.initiative_id == "NIM-04" and c.source_file == "NIM-04_EPS_charter.docx" for c in chunks)


def test_chunk_charter_requires_initiative_id() -> None:
    with pytest.raises(ValueError):
        chunk_charter(LINES, source_file="x.pdf", initiative_id="")


def test_chunk_charter_no_sections_returns_empty() -> None:
    assert chunk_charter(["just a title"], source_file="x.pdf", initiative_id="NIM-01") == []
