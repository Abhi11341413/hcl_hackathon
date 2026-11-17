"""HLD 3: section-aware chunking into CharterChunk (internal to M2).

Owner: M2 (see CLAUDE.md). Not part of the cross-module contract: only
`src.charters.indexer.build_index` and `src.charters.retriever.retrieve` are public.

Charters use numbered headings ("1. Initiative Overview" ... "8. Roles and Accountability"),
optional appendices ("Appendix A. Stakeholder Feedback (verbatim)") and a closing
"Source notes" section. Each section becomes one chunk; a long section is split on
line, then sentence, boundaries so no chunk exceeds `max_chars`. Every chunk keeps the
section name so answers can cite "<file> # <section>".
"""
from __future__ import annotations

import logging
import re

from src.contracts import CharterChunk

logger = logging.getLogger(__name__)

MAX_CHUNK_CHARS = 1200
PREAMBLE_SECTION = "Title"
# Not indexed: the title block repeats section 1, and "Source notes" only lists provenance
# per heading, which would match almost any query and crowd out real content.
SKIP_SECTIONS: frozenset[str] = frozenset({PREAMBLE_SECTION, "Source notes"})

_HEADING_RE = re.compile(
    r"^(?:\d{1,2}\.\s+[A-Z][^.:;]{2,80}"           # 1. Initiative Overview
    r"|Appendix\s+[A-Z]\.?\s+[A-Z][^:;]{2,80}"    # Appendix A. Stakeholder Feedback (verbatim)
    r"|Source notes)$"
)
_INITIATIVE_ID_RE = re.compile(r"(?<![A-Za-z0-9])(NIM-\d{2})(?!\d)")  # "_" may follow, as in file names
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def is_heading(line: str) -> bool:
    """True when a line is a charter section heading."""
    return bool(_HEADING_RE.match(line.strip()))


def initiative_id_from(file_name: str, lines: list[str]) -> str | None:
    """Return the NIM-xx id from the file name, else from the first id found in the text."""
    match = _INITIATIVE_ID_RE.search(file_name)
    if match:
        return match.group(1)
    for line in lines:
        match = _INITIATIVE_ID_RE.search(line)
        if match:
            return match.group(1)
    return None


def split_sections(lines: list[str]) -> list[tuple[str, list[str]]]:
    """Group lines under their heading. Lines before the first heading go to `PREAMBLE_SECTION`.

    Returns (section_name, body_lines) pairs in document order; sections with no body are dropped.
    """
    sections: list[tuple[str, list[str]]] = []
    current_name = PREAMBLE_SECTION
    current_body: list[str] = []
    for line in lines:
        if is_heading(line):
            if current_body:
                sections.append((current_name, current_body))
            current_name, current_body = line.strip(), []
        else:
            current_body.append(line)
    if current_body:
        sections.append((current_name, current_body))
    return sections


def section_slug(section: str) -> str:
    """Short, stable id fragment for a section: "6. Risks..." -> "s6", "Appendix A. ..." -> "appendix-a"."""
    numbered = re.match(r"^(\d{1,2})\.", section)
    if numbered:
        return f"s{int(numbered.group(1))}"
    appendix = re.match(r"^Appendix\s+([A-Z])", section)
    if appendix:
        return f"appendix-{appendix.group(1).lower()}"
    return re.sub(r"[^a-z0-9]+", "-", section.lower()).strip("-") or "section"


def split_text(body_lines: list[str], max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Pack lines into pieces of at most `max_chars`; over-long lines are split by sentence,
    and a single over-long sentence is hard-wrapped. Returns no empty pieces."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    units: list[str] = []
    for line in body_lines:
        if len(line) <= max_chars:
            units.append(line)
            continue
        for sentence in _SENTENCE_SPLIT_RE.split(line):
            units.extend(sentence[i:i + max_chars] for i in range(0, len(sentence), max_chars))

    pieces: list[str] = []
    current = ""
    for unit in (u.strip() for u in units):
        if not unit:
            continue
        candidate = f"{current}\n{unit}" if current else unit
        if len(candidate) <= max_chars:
            current = candidate
        else:
            pieces.append(current)
            current = unit
    if current:
        pieces.append(current)
    return pieces


def chunk_charter(
    lines: list[str], source_file: str, initiative_id: str, max_chars: int = MAX_CHUNK_CHARS
) -> list[CharterChunk]:
    """Turn one charter's extracted lines into section chunks with FR-04 metadata.

    chunk_id format: "<initiative_id>:<section_slug>:<n>", e.g. "NIM-04:s6:1".
    """
    if not initiative_id:
        raise ValueError(f"initiative_id is required to chunk {source_file}")
    chunks: list[CharterChunk] = []
    for section, body in split_sections(lines):
        if section in SKIP_SECTIONS:
            continue
        slug = section_slug(section)
        for n, piece in enumerate(split_text(body, max_chars), start=1):
            chunks.append(CharterChunk(
                chunk_id=f"{initiative_id}:{slug}:{n}",
                initiative_id=initiative_id,
                source_file=source_file,
                section=section,
                text=piece,
            ))
    if not chunks:
        logger.warning("No indexable sections found in %s", source_file)
    return chunks
