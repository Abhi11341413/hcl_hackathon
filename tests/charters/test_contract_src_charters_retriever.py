"""Contract test for src.charters.retriever (owner: M2). Keeps public signatures as listed in CLAUDE.md section 5."""
import inspect

import src.charters.retriever as m


def test_retrieve_signature() -> None:
    assert list(inspect.signature(m.retrieve).parameters) == ['query', 'initiative_ids', 'k']
