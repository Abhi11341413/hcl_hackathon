"""Contract test for src.eval.run_eval (owner: M4). Keeps public signatures as listed in CLAUDE.md section 5."""
import inspect

import src.eval.run_eval as m


def test_run_evaluation_signature() -> None:
    assert list(inspect.signature(m.run_evaluation).parameters) == ['truth_dir']
