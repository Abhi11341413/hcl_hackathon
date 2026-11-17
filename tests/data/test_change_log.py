"""Unit tests for src.data.change_log (owner: M1)."""
import csv

import pytest

from src.data.change_log import AREA_REGISTER, AREA_USAGE, ChangeLog, write_change_log_csv


def test_ids_are_numbered_per_area() -> None:
    log = ChangeLog()
    log.add(AREA_REGISTER, "f", "R1")
    log.add(AREA_USAGE, "f", "R2")
    log.add(AREA_REGISTER, "f", "R3", before=None, after=12000)
    assert [e.issue_id for e in log.entries] == ["DQ-REG-01", "DQ-USE-01", "DQ-REG-02"]
    assert log.entries[-1].before == "" and log.entries[-1].after == "12000"


def test_add_once_deduplicates_by_key() -> None:
    log = ChangeLog()
    assert log.add_once(("k",), AREA_USAGE, "f", "R") is not None
    assert log.add_once(("k",), AREA_USAGE, "f", "R") is None
    assert len(log.entries) == 1


def test_add_requires_area_and_rule() -> None:
    with pytest.raises(ValueError):
        ChangeLog().add("", "f", "R")


def test_write_change_log_csv(tmp_path) -> None:
    log = ChangeLog()
    log.add(AREA_REGISTER, "portfolio_register.xlsx", "TRIM_WHITESPACE", initiative_id="NIM-07")
    path = write_change_log_csv(log.entries, tmp_path / "out" / "log.csv")
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert rows[0]["issue_id"] == "DQ-REG-01" and rows[0]["initiative_id"] == "NIM-07"
