"""Contract test for src.report.weekly (owner: M4). Keeps public signatures as listed in CLAUDE.md section 5."""
import inspect

import src.report.weekly as m


def test_build_weekly_report_signature() -> None:
    assert list(inspect.signature(m.build_weekly_report).parameters) == ['rows']
