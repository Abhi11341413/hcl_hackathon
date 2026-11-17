"""SQLite scorecard table + HLD 5a scorecard lookup.

Owner: M1 (see CLAUDE.md). Public functions here are listed in CLAUDE.md section 5.

One table, ``scorecard``: one row per initiative with the six metrics (NULL = undefined),
the status, and the full InitiativeRecord as JSON so every value stays traceable to its inputs.
``lookup`` turns stored values into citable Evidence. The display text is formatted here, in
code, so the LLM only ever copies a number and never has to round or convert one.
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from pathlib import Path

from src import config
from src.contracts import METRIC_NAMES, Evidence, InitiativeRecord, ScorecardRow

logger = logging.getLogger(__name__)

TABLE = "scorecard"
SOURCE_FILE = "scorecard.db"
EVIDENCE_PREFIX = "scorecard"  # evidence_id = "scorecard:<initiative_id>:<metric>", e.g. "scorecard:NIM-05:roi"
NUMERIC_METRICS: tuple[str, ...] = tuple(m for m in METRIC_NAMES if m != "status")

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    initiative_id       TEXT PRIMARY KEY,
    initiative_name     TEXT NOT NULL,
    short_name          TEXT NOT NULL,
    adoption            REAL,
    wau_change          REAL,
    roi                 REAL,
    avg_monthly_benefit REAL,
    payback_months      REAL,
    run_rate_vs_plan    REAL,
    status              TEXT NOT NULL CHECK (status IN ('Green', 'Amber', 'Red')),
    inputs_json         TEXT NOT NULL
)"""
_COLUMNS: tuple[str, ...] = ("initiative_id", "initiative_name", "short_name", *NUMERIC_METRICS,
                             "status", "inputs_json")

# metric -> (label, how the value is shown, definition used in the evidence text)
METRIC_INFO: dict[str, tuple[str, str, str]] = {
    "adoption": ("Adoption", "percent", "latest-week weekly active users / licensed users"),
    "wau_change": ("WAU change", "percent", "(week 3 WAU - week 1 WAU) / week 1 WAU over the three reporting weeks"),
    "roi": ("ROI", "percent", "(realised benefit to date - total cost to date) / total cost to date"),
    "avg_monthly_benefit": ("Average monthly benefit", "usd", "realised benefit to date / months live"),
    "payback_months": ("Payback period", "months", "total cost to date / average monthly benefit"),
    "run_rate_vs_plan": ("Run-rate vs plan", "percent", "average monthly benefit x 12 / planned annual benefit"),
    "status": ("Portfolio status", "text",
               f"Green: adoption >= {config.GREEN_MIN_ADOPTION:.0%} and ROI > {config.ROI_ZERO:.0%}; "
               f"Red: adoption < {config.RED_MAX_ADOPTION:.0%} or ROI < {config.ROI_ZERO:.0%}; otherwise Amber"),
}


# ----------------------------------------------------------------------------- write / read
def save_scorecard(rows: list[ScorecardRow], db_path: Path) -> None:
    """Write one row per initiative to the SQLite scorecard table (replace on rebuild)."""
    ids = [r.initiative_id for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("save_scorecard: duplicate initiative IDs")
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    placeholders = ", ".join("?" for _ in _COLUMNS)
    with closing(sqlite3.connect(db_path)) as conn, conn:  # one transaction: all rows or none
        conn.execute(_SCHEMA)
        conn.execute(f"DELETE FROM {TABLE}")
        conn.executemany(f"INSERT INTO {TABLE} ({', '.join(_COLUMNS)}) VALUES ({placeholders})",
                         [_to_db_row(r) for r in rows])
    logger.info("saved %d scorecard rows to %s", len(rows), db_path)


def load_scorecard(db_path: Path) -> list[ScorecardRow]:
    """Read the full scorecard table; empty list if the database does not exist yet."""
    db_path = Path(db_path)
    if not db_path.is_file():
        logger.info("no scorecard database at %s yet", db_path)
        return []
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        if not _table_exists(conn):
            return []
        rows = conn.execute(f"SELECT {', '.join(_COLUMNS)} FROM {TABLE} ORDER BY initiative_id").fetchall()
    return [_from_db_row(r) for r in rows]


# ----------------------------------------------------------------------------- 5a lookup
def lookup(initiative_ids: list[str], metrics: list[str], db_path: Path) -> list[Evidence]:
    """Return exact scorecard values for the named initiatives/metrics as Evidence (kind="scorecard").
    Empty initiative_ids means all initiatives; empty metrics means all metrics."""
    wanted_ids = {i.strip().upper() for i in initiative_ids if i and i.strip()}
    wanted_metrics = _valid_metrics(metrics)
    rows = [r for r in load_scorecard(db_path) if not wanted_ids or r.initiative_id in wanted_ids]
    missing = wanted_ids - {r.initiative_id for r in rows}
    if missing:
        logger.info("lookup: no scorecard rows for %s", sorted(missing))
    return [metric_evidence(row, metric) for row in rows for metric in wanted_metrics]


def scorecard_evidence_id(initiative_id: str, metric: str) -> str:
    """Team-agreed evidence ID for a scorecard value: 'scorecard:<initiative_id>:<metric>'."""
    return f"{EVIDENCE_PREFIX}:{initiative_id}:{metric}"


def metric_evidence(row: ScorecardRow, metric: str) -> Evidence:
    """One citable Evidence item for a metric of one scorecard row."""
    label, _, definition = METRIC_INFO[metric]
    value = getattr(row, metric)
    name = f"{row.short_name} ({row.initiative_id})" if row.short_name else row.initiative_id
    if metric == "status":
        text = (f"{name} {label.lower()}: {value}. Adoption {format_metric('adoption', row.adoption)}, "
                f"ROI {format_metric('roi', row.roi)}. Rule: {definition}.")
    else:
        text = f"{name} {label.lower()}: {format_metric(metric, value)}. Definition: {definition}."
    return Evidence(evidence_id=scorecard_evidence_id(row.initiative_id, metric), kind="scorecard",
                    initiative_id=row.initiative_id, text=text, metric=metric, value=value,
                    source_file=SOURCE_FILE, section=metric)


def format_metric(metric: str, value: float | str | None) -> str:
    """Display text for a stored metric value ('undefined' when None)."""
    if value is None:
        return "undefined (not computable from the supplied data)"
    if metric not in METRIC_INFO:
        raise ValueError(f"unknown metric: {metric}")
    kind = METRIC_INFO[metric][1]
    if kind == "percent":
        return f"{value * 100:.1f}%"
    if kind == "usd":
        return f"${value:,.2f}"
    if kind == "months":
        return f"{value:.2f} months"
    return str(value)


# ----------------------------------------------------------------------------- helpers
def _valid_metrics(metrics: list[str]) -> list[str]:
    """Normalise requested metric names; empty means all, unknown names are dropped and logged."""
    requested = [m.strip().lower() for m in metrics if m and m.strip()]
    if not requested:
        return list(METRIC_NAMES)
    unknown = [m for m in requested if m not in METRIC_NAMES]
    if unknown:
        logger.warning("lookup: ignoring unknown metrics %s", unknown)
    return [m for m in dict.fromkeys(requested) if m in METRIC_NAMES]


def _table_exists(conn: sqlite3.Connection) -> bool:
    """True when the scorecard table has been created."""
    found = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (TABLE,)).fetchone()
    return found is not None


def _to_db_row(row: ScorecardRow) -> tuple:
    """ScorecardRow -> tuple in _COLUMNS order."""
    return (row.initiative_id, row.initiative_name, row.short_name,
            *(getattr(row, m) for m in NUMERIC_METRICS), row.status, row.inputs.model_dump_json())


def _from_db_row(row: sqlite3.Row) -> ScorecardRow:
    """sqlite3.Row -> ScorecardRow (inputs restored from JSON)."""
    data = {c: row[c] for c in _COLUMNS if c != "inputs_json"}
    return ScorecardRow(**data, inputs=InitiativeRecord.model_validate_json(row["inputs_json"]))
