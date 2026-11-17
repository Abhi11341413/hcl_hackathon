"""HLD 1: Data Quality and Assumptions Log helpers (internal to M1).

Owner: M1 (see CLAUDE.md). Public functions here are listed in CLAUDE.md section 5.

Every cleaning or standardisation action is recorded as a ChangeLogEntry so that
each number in the scorecard can be traced back to the raw cell it came from.
Issue IDs are generated here (``DQ-<AREA>-<NN>``), never copied from the answer key.
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path

from src.contracts import ChangeLogEntry

logger = logging.getLogger(__name__)

# Area prefixes used in generated issue IDs.
AREA_REGISTER = "REG"
AREA_USAGE = "USE"
AREA_COST = "COST"
AREA_BENEFIT = "BEN"
AREA_ASSUMPTION = "ASM"

CSV_COLUMNS: tuple[str, ...] = tuple(ChangeLogEntry.model_fields)


class ChangeLog:
    """Collects ChangeLogEntry objects and numbers them per area (DQ-REG-01, DQ-USE-01, ...)."""

    def __init__(self) -> None:
        self._entries: list[ChangeLogEntry] = []
        self._counters: dict[str, int] = {}
        self._seen_keys: set[tuple[str, ...]] = set()

    def add(
        self,
        area: str,
        file: str,
        rule: str,
        *,
        initiative_id: str = "",
        field: str = "",
        before: object = "",
        after: object = "",
        effect: str = "",
    ) -> ChangeLogEntry:
        """Record one action and return the entry. ``before``/``after`` are stringified."""
        if not area or not rule:
            raise ValueError("ChangeLog.add needs a non-empty area and rule")
        self._counters[area] = self._counters.get(area, 0) + 1
        entry = ChangeLogEntry(
            issue_id=f"DQ-{area}-{self._counters[area]:02d}",
            file=file,
            initiative_id=initiative_id,
            field=field,
            before=_to_text(before),
            after=_to_text(after),
            rule=rule,
            effect=effect,
        )
        self._entries.append(entry)
        logger.debug("change log %s: %s %s %s", entry.issue_id, rule, initiative_id, field)
        return entry

    def add_once(self, key: tuple[str, ...], area: str, file: str, rule: str, **fields: object) -> ChangeLogEntry | None:
        """Like add(), but records nothing if an entry with the same ``key`` was already added."""
        if key in self._seen_keys:
            return None
        self._seen_keys.add(key)
        return self.add(area, file, rule, **fields)  # type: ignore[arg-type]

    @property
    def entries(self) -> list[ChangeLogEntry]:
        """A copy of the entries recorded so far, in insertion order."""
        return list(self._entries)


def write_change_log_csv(entries: list[ChangeLogEntry], path: Path) -> Path:
    """Write entries to a CSV (one column per ChangeLogEntry field) and return the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CSV_COLUMNS))
        writer.writeheader()
        for entry in entries:
            writer.writerow(entry.model_dump())
    logger.info("wrote %d change-log entries to %s", len(entries), path)
    return path


def _to_text(value: object) -> str:
    """Render a before/after value as plain text ('' for None)."""
    if value is None:
        return ""
    return str(value)
