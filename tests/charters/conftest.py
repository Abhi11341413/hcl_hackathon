"""Fixtures for M2 charter tests: an offline fake embedder and a built temp index."""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

import pytest

from src import config

DIM = 128


def fake_embed(texts: list[str]) -> list[list[float]]:
    """Deterministic hashed bag-of-words vectors (unit length); no model download."""
    out: list[list[float]] = []
    for text in texts:
        vec = [0.0] * DIM
        for tok in re.findall(r"[a-z0-9]+", text.lower()):
            vec[int(hashlib.md5(tok.encode()).hexdigest(), 16) % DIM] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        out.append([v / norm for v in vec])
    return out


@pytest.fixture
def fake_embeddings(monkeypatch):
    """Route every embedding call in src.charters through fake_embed."""
    import src.charters.indexer as indexer

    monkeypatch.setattr(indexer, "get_embedding_function", lambda: fake_embed)
    return fake_embed


@pytest.fixture
def built_index(tmp_path: Path, monkeypatch, fake_embeddings):
    """Index the seed charters into a temp Chroma dir and point config.CHROMA_DIR at it."""
    from src.charters.indexer import build_index

    chroma_dir = tmp_path / "chroma"
    monkeypatch.setattr(config, "CHROMA_DIR", chroma_dir)
    stats = build_index(config.CHARTER_DIR, chroma_dir)
    return chroma_dir, stats
