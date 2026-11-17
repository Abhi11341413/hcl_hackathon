"""Contract test for src.scorecard.store (owner: M1). Keeps public signatures as listed in CLAUDE.md section 5."""
import inspect

import src.scorecard.store as m


def test_save_scorecard_signature() -> None:
    assert list(inspect.signature(m.save_scorecard).parameters) == ['rows', 'db_path']

def test_load_scorecard_signature() -> None:
    assert list(inspect.signature(m.load_scorecard).parameters) == ['db_path']

def test_lookup_signature() -> None:
    assert list(inspect.signature(m.lookup).parameters) == ['initiative_ids', 'metrics', 'db_path']
