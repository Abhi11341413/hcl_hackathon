"""HLD 5b: charter retriever over the ChromaDB index.

Owner: M2 (see CLAUDE.md). Public function (CLAUDE.md section 5): `retrieve`.

Hybrid ranking, capped at 1.0:
    score = VECTOR_WEIGHT * cosine similarity + LEXICAL_WEIGHT * keyword overlap
            + SECTION_BOOST if the question asks about that chunk's section
The keyword part helps with acronyms and exact terms ("RBIS", "CIO") that small embedding
models blur; the section boost keeps "what risks..." on section 6 even when a mixed
question is padded with scorecard words. Hints are matched against the user's question
only, never against charter text, so retrieved text (untrusted data) cannot steer ranking.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from src import config
from src.charters.indexer import embed_texts, open_collection
from src.contracts import Evidence

logger = logging.getLogger(__name__)

VECTOR_WEIGHT = 0.7
LEXICAL_WEIGHT = 0.3
SECTION_BOOST = 0.2
MAX_CANDIDATES = 200
EVIDENCE_PREFIX = "charter:"

# Question phrasing -> section-number prefix of the charter heading it points to.
SECTION_HINTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("2.", re.compile(r"\b(objective|deliver|scope|purpose|goal|produce|output|classif|meant to)", re.I)),
    ("3.", re.compile(r"\b(kpi|performance measure|agency measure|governance profile|target)", re.I)),
    ("4.", re.compile(r"\b(benefit|lever|on track|planned|plan figure|saving)", re.I)),
    ("5.", re.compile(r"\b(adoption plan|roll-?out|licen[cs]e|training|champion)", re.I)),
    ("6.", re.compile(r"\b(risk|cio|concern)", re.I)),
    ("7.", re.compile(r"\b(operational analysis|conclu|modernization|replacement)", re.I)),
    ("8.", re.compile(r"\b(sponsor|owner|accountab|responsible|roles?)\b", re.I)),
    ("Appendix A", re.compile(r"\b(feedback|stakeholder|retrospective)", re.I)),
)

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_STOPWORDS: frozenset[str] = frozenset(
    "a an and are as at be by did do does for from has have how in is it its me of on or "
    "said say says should tell than that the their them there this to was what when where "
    "which who why will with".split()
)


def _tokens(text: str) -> set[str]:
    """Lower-cased content words (stopwords and 1-char tokens removed)."""
    return {t for t in _TOKEN_RE.findall(text.lower()) if len(t) > 1 and t not in _STOPWORDS}


def lexical_score(query: str, document: str) -> float:
    """Fraction of the query's content words that appear in the document (0 when the query has none)."""
    q = _tokens(query)
    if not q:
        return 0.0
    return len(q & _tokens(document)) / len(q)


def hinted_sections(query: str) -> set[str]:
    """Section prefixes ("6.", "Appendix A") the question's wording points to."""
    return {prefix for prefix, pattern in SECTION_HINTS if pattern.search(query)}


def _where(initiative_ids: list[str] | None) -> dict | None:
    """Chroma metadata filter for the requested initiatives (None = whole portfolio)."""
    if not initiative_ids:
        return None
    ids = sorted({i.strip() for i in initiative_ids if i and i.strip()})
    if not ids:
        return None
    return {"initiative_id": ids[0]} if len(ids) == 1 else {"initiative_id": {"$in": ids}}


def retrieve(query: str, initiative_ids: list[str] | None, k: int) -> list[Evidence]:
    """Return the k best charter chunks as Evidence (kind="charter"), filtered to
    initiative_ids when given, dropping results below config.MIN_RETRIEVAL_SCORE.

    Never raises: an empty query, k <= 0, a missing index or a Chroma error all return [].
    """
    if not query or not query.strip() or k <= 0:
        return []
    try:
        return _retrieve(query.strip(), initiative_ids, k, Path(config.CHROMA_DIR))
    except Exception:
        logger.exception("Charter retrieval failed for query %r", query[:200])
        return []


def _retrieve(query: str, initiative_ids: list[str] | None, k: int, chroma_dir: Path) -> list[Evidence]:
    """Vector-query all candidates in scope, re-rank with the hybrid score, and threshold."""
    collection = open_collection(chroma_dir, create=False)
    if collection is None:
        logger.warning("Charter index missing at %s; run build_index first", chroma_dir)
        return []
    total = collection.count()
    if total == 0:
        return []

    result = collection.query(
        query_embeddings=embed_texts([query]),
        n_results=min(total, MAX_CANDIDATES),
        where=_where(initiative_ids),
        include=["documents", "metadatas", "distances"],
    )
    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]

    hints = hinted_sections(query)
    scored: list[tuple[float, Evidence]] = []
    for doc, meta, dist in zip(documents, metadatas, distances):
        meta = meta or {}
        section = str(meta.get("section", ""))
        cosine = max(0.0, min(1.0, 1.0 - float(dist)))
        lexical = lexical_score(query, f"{meta.get('title', '')} {section} {doc}")
        boost = SECTION_BOOST if any(section.startswith(h) for h in hints) else 0.0
        score = round(min(1.0, VECTOR_WEIGHT * cosine + LEXICAL_WEIGHT * lexical + boost), 4)
        if score < config.MIN_RETRIEVAL_SCORE:
            continue
        scored.append((score, Evidence(
            evidence_id=f"{EVIDENCE_PREFIX}{meta.get('chunk_id', '')}",
            kind="charter",
            initiative_id=str(meta.get("initiative_id", "")),
            text=doc or "",
            source_file=str(meta.get("source_file", "")),
            section=meta.get("section"),
            score=score,
        )))
    scored.sort(key=lambda item: (-item[0], item[1].evidence_id))
    hits = [ev for _, ev in scored[:k]]
    logger.info("retrieve: %d/%d chunks kept (k=%d, filter=%s)", len(hits), len(documents), k, initiative_ids)
    return hits
