"""HLD 3: charter indexer -> ChromaDB (chunk text, metadata, vector).

Owner: M2 (see CLAUDE.md). Public functions here are listed in CLAUDE.md section 5.
"""
from __future__ import annotations

import logging

from pathlib import Path

from src.contracts import IndexStats

logger = logging.getLogger(__name__)


def build_index(charter_dir: Path, chroma_dir: Path) -> IndexStats:
    """Extract every PDF/DOCX in charter_dir, chunk by section, embed, and (re)write the
    ChromaDB collection with metadata: chunk_id, initiative_id, source_file, section."""
    raise NotImplementedError("M2: build_index")
