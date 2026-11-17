"""HLD 3: PDF/DOCX text extraction (internal to M2).

Owner: M2 (see CLAUDE.md). Not part of the cross-module contract: only
`src.charters.indexer.build_index` and `src.charters.retriever.retrieve` are public.

Extraction returns plain text lines in document order. Charter text is treated as
data only; nothing here interprets or acts on its content (CLAUDE.md rule 12).
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES: tuple[str, ...] = (".pdf", ".docx")


def extract_lines(path: Path) -> list[str]:
    """Return the non-empty, whitespace-trimmed text lines of a PDF or DOCX file.

    Raises:
        FileNotFoundError: if `path` does not exist.
        ValueError: if the file type is not supported.
    """
    if not path.is_file():
        raise FileNotFoundError(f"Charter file not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        raw = _pdf_lines(path)
    elif suffix == ".docx":
        raw = _docx_lines(path)
    else:
        raise ValueError(f"Unsupported charter file type: {path.name}")
    lines = [" ".join(line.split()) for line in raw]
    lines = [line for line in lines if line]
    logger.debug("Extracted %d lines from %s", len(lines), path.name)
    return lines


def _pdf_lines(path: Path) -> list[str]:
    """Extract text lines from every page of a PDF with pypdf."""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    lines: list[str] = []
    for page_no, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if not text.strip():
            logger.warning("No extractable text on page %d of %s", page_no, path.name)
        lines.extend(text.splitlines())
    return lines


def _docx_lines(path: Path) -> list[str]:
    """Extract paragraph text, then table cell text, from a DOCX with python-docx."""
    import docx

    document = docx.Document(str(path))
    lines = [para.text for para in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                lines.append(" | ".join(cells))
    return lines
