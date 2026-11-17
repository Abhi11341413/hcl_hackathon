"""Shared test fixtures (SHARED FILE: agents must not edit; see CLAUDE.md, rule 2)."""
from pathlib import Path

import pytest

from src import config


@pytest.fixture
def seed_dir() -> Path:
    """The generated, deliberately messy seed data."""
    return config.SEED_DIR


@pytest.fixture
def truth_dir() -> Path:
    """The answer key (tests and eval only)."""
    return config.TRUTH_DIR


@pytest.fixture
def mock_llm(monkeypatch):
    """Replace src.llm.client.generate_json with a stub. Usage: mock_llm(lambda prompt, schema: schema(...))."""
    import src.llm.client as client

    def install(fn):
        monkeypatch.setattr(client, "generate_json", fn)
        return fn

    return install
