"""HLD 3: charter indexer -> ChromaDB (chunk text, metadata, vector).

Owner: M2 (see CLAUDE.md). Public function (CLAUDE.md section 5): `build_index`.
`get_embedding_function`, `embed_texts`, `embedding_header` and `open_collection` are
shared with `src.charters.retriever` (same owner) and are not part of the team contract.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from src import config
from src.charters.chunker import chunk_charter, initiative_id_from
from src.charters.extract import SUPPORTED_SUFFIXES, extract_lines
from src.contracts import CharterChunk, IndexStats

logger = logging.getLogger(__name__)

EmbedFn = Callable[[list[str]], Any]
_DEFAULT_MODEL = "all-MiniLM-L6-v2"
_BATCH_SIZE = 64


@lru_cache(maxsize=1)
def get_embedding_function() -> EmbedFn:
    """Return the embedding function named by config.EMBEDDING_MODEL.

    all-MiniLM-L6-v2 uses ChromaDB's bundled ONNX build (no torch needed; weights are
    downloaded once on first use). Any other name needs sentence-transformers installed;
    if it is missing we log an error and fall back to the default model.
    """
    from chromadb.utils import embedding_functions as ef

    model = config.EMBEDDING_MODEL
    if model != _DEFAULT_MODEL:
        try:
            return ef.SentenceTransformerEmbeddingFunction(model_name=model)
        except Exception:
            logger.exception("Embedding model %r unavailable; falling back to %s", model, _DEFAULT_MODEL)
    return ef.DefaultEmbeddingFunction()


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed texts in batches and return plain float lists (Chroma-ready)."""
    if not texts:
        return []
    embed = get_embedding_function()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), _BATCH_SIZE):
        for vector in embed(texts[start:start + _BATCH_SIZE]):
            vectors.append([float(x) for x in vector])
    return vectors


def embedding_header(title: str, section: str) -> str:
    """Context line prepended to a chunk before embedding (not stored in the chunk text)."""
    return f"{title} | {section}".strip(" |")


def open_collection(chroma_dir: Path, create: bool) -> Any | None:
    """Open the charter collection in `chroma_dir`; None if it does not exist and create is False."""
    import chromadb

    if not create and not chroma_dir.exists():
        return None
    chroma_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(chroma_dir))
    if create:
        return client.get_or_create_collection(
            name=config.CHROMA_COLLECTION,
            embedding_function=None,  # vectors are always supplied explicitly
            metadata={"hnsw:space": "cosine", "embedding_model": config.EMBEDDING_MODEL},
        )
    try:
        return client.get_collection(name=config.CHROMA_COLLECTION, embedding_function=None)
    except Exception:
        logger.warning("Charter collection %r not found in %s", config.CHROMA_COLLECTION, chroma_dir)
        return None


def _reset_collection(chroma_dir: Path) -> Any:
    """Drop and recreate the charter collection so a rebuild never leaves stale chunks."""
    import chromadb

    chroma_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(chroma_dir))
    try:
        client.delete_collection(name=config.CHROMA_COLLECTION)
    except Exception:
        logger.debug("No existing collection to delete in %s", chroma_dir)
    return open_collection(chroma_dir, create=True)


def short_name_from_file(file_name: str, initiative_id: str) -> str:
    """Short name encoded in the file name: "NIM-05_DACoE_charter.pdf" -> "DACoE"."""
    stem = Path(file_name).stem
    if stem.startswith(initiative_id):
        stem = stem[len(initiative_id):]
    if stem.lower().endswith("_charter"):
        stem = stem[: -len("_charter")]
    return stem.replace("_", " ").strip()


def _title_of(lines: list[str], initiative_id: str, file_name: str) -> str:
    """The charter's title line ("NIM-03 - <name>") plus the file's short name when the title
    lacks it, so acronyms users type (e.g. "DACoE") match; the bare id if no title line."""
    title = next((line for line in lines[:3] if line.startswith(initiative_id)), initiative_id)
    short = short_name_from_file(file_name, initiative_id)
    if short and short.lower() not in title.lower():
        title = f"{title} ({short})"
    return title


def _chunk_file(path: Path) -> tuple[list[CharterChunk], str]:
    """Extract and chunk one charter; returns (chunks, title). Empty list if unusable."""
    try:
        lines = extract_lines(path)
    except Exception:
        logger.exception("Could not extract text from %s; skipping", path.name)
        return [], ""
    initiative_id = initiative_id_from(path.name, lines)
    if not initiative_id:
        logger.warning("No initiative id (NIM-xx) in %s; skipping", path.name)
        return [], ""
    chunks = chunk_charter(lines, source_file=path.name, initiative_id=initiative_id)
    return chunks, _title_of(lines, initiative_id, path.name)


def _assert_not_truth_dir(charter_dir: Path) -> None:
    """Refuse to index the answer key (CLAUDE.md rule 13)."""
    truth = config.TRUTH_DIR.resolve()
    target = charter_dir.resolve()
    if target == truth or truth in target.parents:
        raise ValueError(f"Refusing to index the answer key directory: {charter_dir}")


def build_index(charter_dir: Path, chroma_dir: Path) -> IndexStats:
    """Extract every PDF/DOCX in charter_dir, chunk by section, embed, and (re)write the
    ChromaDB collection with metadata: chunk_id, initiative_id, source_file, section.

    Raises:
        FileNotFoundError: if charter_dir does not exist.
        ValueError: if charter_dir is (inside) data/truth/.
    """
    charter_dir, chroma_dir = Path(charter_dir), Path(chroma_dir)
    if not charter_dir.is_dir():
        raise FileNotFoundError(f"Charter directory not found: {charter_dir}")
    _assert_not_truth_dir(charter_dir)

    files = sorted(p for p in charter_dir.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES)
    if not files:
        logger.warning("No PDF/DOCX charters in %s", charter_dir)

    chunks: list[CharterChunk] = []
    titles: dict[str, str] = {}
    files_indexed = 0
    for path in files:
        file_chunks, title = _chunk_file(path)
        if file_chunks:
            files_indexed += 1
            chunks.extend(file_chunks)
            titles[path.name] = title

    seen: set[str] = set()
    for chunk in chunks:  # two files for one initiative would otherwise collide
        if chunk.chunk_id in seen:
            raise ValueError(f"Duplicate chunk id {chunk.chunk_id}: more than one charter for {chunk.initiative_id}?")
        seen.add(chunk.chunk_id)

    collection = _reset_collection(chroma_dir)
    if chunks:
        texts = [f"{embedding_header(titles[c.source_file], c.section)}\n{c.text}" for c in chunks]
        collection.add(
            ids=[c.chunk_id for c in chunks],
            documents=[c.text for c in chunks],
            embeddings=embed_texts(texts),
            metadatas=[{
                "chunk_id": c.chunk_id,
                "initiative_id": c.initiative_id,
                "source_file": c.source_file,
                "section": c.section,
                "title": titles[c.source_file],
            } for c in chunks],
        )

    per_initiative: dict[str, int] = {}
    for c in chunks:
        per_initiative[c.initiative_id] = per_initiative.get(c.initiative_id, 0) + 1
    stats = IndexStats(files_indexed=files_indexed, chunks_written=len(chunks),
                       chunks_per_initiative=dict(sorted(per_initiative.items())))
    logger.info("Charter index built: %d files, %d chunks in %s", files_indexed, len(chunks), chroma_dir)
    return stats
