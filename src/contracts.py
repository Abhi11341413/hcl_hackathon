"""Shared data contracts. SHARED FILE: agents must not edit (see CLAUDE.md, rule 2).

Every object that crosses a module boundary is one of these Pydantic models.
Money is always USD after cleaning; ratios are plain fractions (0.6 == 60%).
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

Route = Literal["numeric", "narrative", "mixed", "out_of_scope"]
Status = Literal["Green", "Amber", "Red"]
AnswerStatus = Literal["answered", "insufficient_evidence", "refused"]
EvidenceKind = Literal["scorecard", "charter"]

METRIC_NAMES: tuple[str, ...] = (
    "adoption", "wau_change", "roi", "avg_monthly_benefit",
    "payback_months", "run_rate_vs_plan", "status",
)


# ---------------------------------------------------------------- M1: data + scorecard
class InitiativeRecord(BaseModel):
    """One cleaned row per initiative: the only input the scorecard engine accepts."""
    initiative_id: str
    initiative_name: str
    short_name: str = ""
    initiative_type: str = ""
    agency: str = ""
    go_live_date: date
    months_live: int = Field(ge=0)
    licensed_users: int = Field(ge=0)
    wau_week1: int = Field(ge=0)
    wau_week2: int = Field(ge=0)
    wau_week3: int = Field(ge=0)
    total_cost_to_date_usd: float = Field(ge=0)
    realised_benefit_to_date_usd: float
    planned_annual_benefit_usd: float = Field(ge=0)
    charter_file: str = ""


class ChangeLogEntry(BaseModel):
    """One cleaning or standardisation action, written to the Data Quality and Assumptions Log."""
    issue_id: str
    file: str
    initiative_id: str = ""
    field: str = ""
    before: str = ""
    after: str = ""
    rule: str
    effect: str = ""


class CleanResult(BaseModel):
    """Output of load_and_clean: clean records plus the change log that explains them."""
    records: list[InitiativeRecord]
    change_log: list[ChangeLogEntry]


class ScorecardRow(BaseModel):
    """Governed metrics for one initiative. The only source of numbers shown to users."""
    initiative_id: str
    initiative_name: str
    short_name: str = ""
    adoption: float | None
    wau_change: float | None
    roi: float | None
    avg_monthly_benefit: float | None
    payback_months: float | None
    run_rate_vs_plan: float | None
    status: Status
    inputs: InitiativeRecord


# ---------------------------------------------------------------- M2: charters
class CharterChunk(BaseModel):
    """One indexed charter chunk with the metadata required by FR-04."""
    chunk_id: str
    initiative_id: str
    source_file: str
    section: str
    text: str


class IndexStats(BaseModel):
    """Summary of a build_index run."""
    files_indexed: int
    chunks_written: int
    chunks_per_initiative: dict[str, int] = Field(default_factory=dict)


# ---------------------------------------------------------------- shared evidence
class Evidence(BaseModel):
    """One citable item: a scorecard value or a retrieved charter chunk."""
    evidence_id: str
    kind: EvidenceKind
    initiative_id: str
    text: str
    metric: str | None = None
    value: float | str | None = None
    source_file: str
    section: str | None = None
    score: float | None = None


# ---------------------------------------------------------------- M3: AI layer
class RouteDecision(BaseModel):
    """Router output: which evidence path(s) answer the question."""
    route: Route
    initiative_ids: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    reason: str = ""


class Citation(BaseModel):
    """Links one claim in an answer to the evidence item that supports it."""
    evidence_id: str
    claim: str


class Answer(BaseModel):
    """Final (or draft) answer shown in the chat."""
    status: AnswerStatus
    text: str
    citations: list[Citation] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    route: Route | None = None


class GuardrailResult(BaseModel):
    """Validator verdict; `answer` is what may be shown (possibly replaced by the fallback)."""
    approved: bool
    violations: list[str] = Field(default_factory=list)
    answer: Answer


# ---------------------------------------------------------------- M4: reporting
class ReportItem(BaseModel):
    """One initiative needing attention in the weekly report, with traceable reasons."""
    initiative_id: str
    status: Status
    reasons: list[str]
    citations: list[Citation] = Field(default_factory=list)


class WeeklyReport(BaseModel):
    """Generated weekly executive report."""
    report_date: date
    status_counts: dict[str, int]
    summary: str
    items: list[ReportItem]
    markdown: str
