"""Contract test for src.scorecard.engine (owner: M1). Keeps public signatures as listed in CLAUDE.md section 5."""
import inspect

import src.scorecard.engine as m


def test_compute_scorecard_signature() -> None:
    assert list(inspect.signature(m.compute_scorecard).parameters) == ['records']
