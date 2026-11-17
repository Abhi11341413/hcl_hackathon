"""Unit tests for src.charters.extract (owner: M2). Reads the committed seed charters."""
from pathlib import Path

import pytest

from src import config
from src.charters.extract import extract_lines


@pytest.mark.parametrize("name", ["NIM-01_PHIS_charter.pdf", "NIM-02_IA_CoE_charter.docx"])
def test_extracts_headings_from_pdf_and_docx(name: str) -> None:
    lines = extract_lines(config.CHARTER_DIR / name)
    assert lines and lines[0].startswith(name[:6])
    assert "1. Initiative Overview" in lines
    assert "4. Benefits Case" in lines
    assert all(line == line.strip() and line for line in lines)


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        extract_lines(tmp_path / "nope.pdf")


def test_unsupported_type_raises(tmp_path: Path) -> None:
    f = tmp_path / "notes.txt"
    f.write_text("1. Initiative Overview")
    with pytest.raises(ValueError):
        extract_lines(f)


def test_docx_tables_are_extracted(tmp_path: Path) -> None:
    import docx

    d = docx.Document()
    d.add_paragraph("4. Benefits Case")
    table = d.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Lever"
    table.cell(0, 1).text = "Calls deflected"
    path = tmp_path / "NIM-99_t.docx"
    d.save(str(path))
    assert extract_lines(path) == ["4. Benefits Case", "Lever | Calls deflected"]
