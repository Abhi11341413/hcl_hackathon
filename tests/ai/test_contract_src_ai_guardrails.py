"""Contract test for src.ai.guardrails (owner: M3). Keeps public signatures as listed in CLAUDE.md section 5."""
import inspect

import src.ai.guardrails as m


def test_check_input_signature() -> None:
    assert list(inspect.signature(m.check_input).parameters) == ['question']

def test_validate_signature() -> None:
    assert list(inspect.signature(m.validate).parameters) == ['draft', 'evidence']
