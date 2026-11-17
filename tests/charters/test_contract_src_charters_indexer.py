"""Contract test for src.charters.indexer (owner: M2). Keeps public signatures as listed in CLAUDE.md section 5."""
import inspect

import src.charters.indexer as m


def test_build_index_signature() -> None:
    assert list(inspect.signature(m.build_index).parameters) == ['charter_dir', 'chroma_dir']
