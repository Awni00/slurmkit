"""View models for human-readable CLI reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple


KeyValueList = Sequence[Tuple[str, str]]


@dataclass(frozen=True)
class MetricItem:
    """A summary metric with optional percentage and semantic state."""

    label: str
    value: str
    percent: Optional[float] = None
    state: Optional[str] = None


@dataclass(frozen=True)
class TableSection:
    """A titled table section."""

    title: str
    headers: Sequence[str]
    rows: Sequence[Sequence[str]]
    status_columns: Sequence[int] = field(default_factory=tuple)
    empty_message: str = "  (no rows)"


@dataclass(frozen=True)
class CollectionShowReport:
    """View model for `collection show` table output."""

    title: str
    metadata: KeyValueList
    parameters_yaml: Optional[str]
    summary_title: str
    summary_metrics: Sequence[MetricItem]
    jobs_table: TableSection


@dataclass(frozen=True)
class CollectionAnalyzeReport:
    """View model for `collection analyze` table output."""

    title: str
    metadata_lines: Sequence[str]
    overall_title: str
    overall_metrics: Sequence[MetricItem]
    info_messages: Sequence[str]
    parameter_tables: Sequence[TableSection]
    top_risky_table: Optional[TableSection]
    top_stable_table: Optional[TableSection]
    notes: Sequence[str]
