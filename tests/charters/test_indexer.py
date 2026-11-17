"""Behaviour tests for src.charters.indexer.build_index (owner: M2). Offline: fake embeddings."""
from pathlib import Path

import pytest

from src import config
from src.charters.indexer import build_index, open_collection, short_name_from_file
from src.contracts import IndexStats

INITIATIVES = [f"NIM-{n:02d}" for n in range(1, 11)]


def test_indexes_all_seed_charters(built_index) -> None:
    chroma_dir, stats = built_index
    assert isinstance(stats, IndexStats)
    assert stats.files_indexed == 10
    assert sorted(stats.chunks_per_initiative) == INITIATIVES
    assert stats.chunks_written == sum(stats.chunks_per_initiative.values())
    assert open_collection(chroma_dir, create=False).count() == stats.chunks_written


def test_metadata_and_sections(built_index) -> None:
    chroma_dir, _ = built_index
    got = open_collection(chroma_dir, create=False).get(include=["metadatas"])
    metas = got["metadatas"]
    assert all({"chunk_id", "initiative_id", "source_file", "section"} <= set(m) for m in metas)
    sections = {(m["initiative_id"], m["section"]) for m in metas}
    assert ("NIM-04", "6. Risks and Governance") in sections
    assert ("NIM-03", "4. Benefits Case") in sections
    assert ("NIM-09", "Appendix A. Stakeholder Feedback (verbatim)") in sections
    assert not any(m["section"] in {"Source notes", "Title"} for m in metas)
    assert all(m["source_file"].startswith(m["initiative_id"]) for m in metas)


@pytest.mark.parametrize("file_name,iid,short", [
    ("NIM-05_DACoE_charter.pdf", "NIM-05", "DACoE"),
    ("NIM-02_IA_CoE_charter.docx", "NIM-02", "IA CoE"),
    ("NIM-09_DHS_GenAI_Chat_charter.pdf", "NIM-09", "DHS GenAI Chat"),
    ("NIM-01.pdf", "NIM-01", ""),
])
def test_short_name_from_file(file_name: str, iid: str, short: str) -> None:
    assert short_name_from_file(file_name, iid) == short


def test_titles_carry_short_name(built_index) -> None:
    chroma_dir, _ = built_index
    metas = open_collection(chroma_dir, create=False).get(where={"initiative_id": "NIM-05"})["metadatas"]
    assert metas and all("(DACoE)" in m["title"] for m in metas)


def test_rebuild_replaces_instead_of_duplicating(built_index) -> None:
    chroma_dir, first = built_index
    second = build_index(config.CHARTER_DIR, chroma_dir)
    assert second == first
    assert open_collection(chroma_dir, create=False).count() == first.chunks_written


def test_empty_dir_gives_empty_index(tmp_path: Path, fake_embeddings) -> None:
    (tmp_path / "charters").mkdir()
    stats = build_index(tmp_path / "charters", tmp_path / "chroma")
    assert stats == IndexStats(files_indexed=0, chunks_written=0)


def test_unreadable_and_unknown_files_are_skipped(tmp_path: Path, fake_embeddings) -> None:
    charters = tmp_path / "charters"
    charters.mkdir()
    (charters / "NIM-01_broken.pdf").write_bytes(b"not a pdf")
    (charters / "readme.txt").write_text("ignore me")
    stats = build_index(charters, tmp_path / "chroma")
    assert stats.files_indexed == 0


def test_missing_dir_raises(tmp_path: Path, fake_embeddings) -> None:
    with pytest.raises(FileNotFoundError):
        build_index(tmp_path / "missing", tmp_path / "chroma")


def test_refuses_truth_dir(tmp_path: Path, fake_embeddings) -> None:
    with pytest.raises(ValueError):
        build_index(config.TRUTH_DIR, tmp_path / "chroma")
