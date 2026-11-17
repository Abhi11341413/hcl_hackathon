"""Contract test for src.ai.router (owner: M3). Keeps public signatures as listed in CLAUDE.md section 5."""
import inspect

import src.ai.router as m


def test_route_signature() -> None:
    assert list(inspect.signature(m.route).parameters) == ['question', 'initiative_ids']
