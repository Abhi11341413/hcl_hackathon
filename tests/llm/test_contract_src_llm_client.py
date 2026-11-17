"""Contract test for src.llm.client (owner: M3). Keeps public signatures as listed in CLAUDE.md section 5."""
import inspect

import src.llm.client as m


def test_generate_json_signature() -> None:
    assert list(inspect.signature(m.generate_json).parameters) == ['prompt', 'schema']
