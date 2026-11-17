"""Contract test for src.ai.answer (owner: M3). Keeps public signatures as listed in CLAUDE.md section 5."""
import inspect

import src.ai.answer as m


def test_answer_question_signature() -> None:
    assert list(inspect.signature(m.answer_question).parameters) == ['question']
