"""Report builders and renderers for collection-oriented commands."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from slurmkit.cli.ui.backend import UIBackend
from slurmkit.cli.ui.models import (
    CollectionAnalyzeReport,
    CollectionListReport,
    CollectionShowReport,
    MetricItem,
    TableSection,
)


DEFAULT_COLLECTION_SHOW_COLUMNS: tuple[str, ...] = (
    "job_name",
    "job_id",
    "state",
    "runtime",
    "attempt",
    "submission_group",
    "resubmissions",
    "output_path",
)


def _format_pct(value: float) -> str:
    return f"{value * 100.0:.1f}"


def _has_submitted_job_id(job_id: Any) -> bool:
    if job_id is None:
        return False
    value = str(job_id).strip()
    if not value:
        return False
    return value.upper() not in {"N/A", "NONE", "NULL"}


def _to_non_negative_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _normalize_raw_state(value: Any) -> Optional[str]:
    if value is None:
        return None
    raw_state = str(value).strip()
    if not raw_state:
        return None
    raw_state_upper = raw_state.upper()
    if raw_state_upper in {"N/A", "NONE", "NULL"}:
        return None
    return raw_state_upper


def _parse_time(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_duration(delta_seconds: int) -> str:
    if delta_seconds < 0:
        return ""
    hours, rem = divmod(delta_seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours > 0:
        return f"{hours}h {minutes:02d}m {seconds:02d}s"
    if minutes > 0:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def _format_runtime(job: Dict[str, Any], now_utc: datetime) -> str:
    started = _parse_time(job.get("effective_started_at"))
    completed = _parse_time(job.get("effective_completed_at"))
    if started is None:
        return ""
    if completed is not None:
        if completed < started:
            return ""
        return _format_duration(int((completed - started).total_seconds()))
    raw_state = str(job.get("effective_state_raw", "")).strip().upper()
    if raw_state not in {"RUNNING", "COMPLETING"}:
        return ""
    return _format_duration(int((now_utc - started).total_seconds()))


def _string_or_empty(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _string_or_na(value: Any) -> str:
    if value is None:
        return "N/A"
    text = str(value).strip()
    return text if text else "N/A"


def _history_string(job: Dict[str, Any]) -> str:
    return " -> ".join(str(item) for item in job.get("attempt_history", []))


def _normalize_path_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


_COLUMN_DEF = Tuple[str, Callable[[Dict[str, Any], datetime], str], bool]


def _collection_show_column_registry() -> Dict[str, _COLUMN_DEF]:
    return {
        "job_name": ("Job Name", lambda job, _now: _string_or_empty(job.get("job_name", "")), False),
        "job_id": ("Job ID", lambda job, _now: _string_or_na(job.get("effective_job_id")), False),
        "state": ("State", lambda job, _now: _string_or_na(job.get("effective_state_raw")), True),
        "runtime": ("Runtime", lambda job, now: _format_runtime(job, now), False),
        "attempt": ("Attempt", lambda job, _now: _string_or_empty(job.get("effective_attempt_label", "")), False),
        "submission_group": (
            "Submission Group",
            lambda job, _now: _string_or_empty(job.get("effective_submission_group", "")),
            False,
        ),
        "resubmissions": ("Resubmissions", lambda job, _now: _string_or_empty(job.get("resubmissions_count", "")), False),
        "hostname": ("Hostname", lambda job, _now: _string_or_empty(job.get("effective_hostname", "")), False),
        "output_path": ("Output Path", lambda job, _now: _normalize_path_value(job.get("effective_output_path")), False),
        "script_path": ("Script Path", lambda job, _now: _normalize_path_value(job.get("effective_script_path")), False),
        "primary_job_id": ("Primary Job ID", lambda job, _now: _string_or_na(job.get("primary_job_id")), False),
        "primary_state": ("Primary State", lambda job, _now: _string_or_na(job.get("primary_state_raw")), True),
        "history": ("History", lambda job, _now: _history_string(job), False),
    }


def _resolve_collection_show_columns(configured: Optional[Sequence[str]]) -> tuple[str, ...]:
    registry = _collection_show_column_registry()
    selected: list[str] = []
    for candidate in configured or ():
        key = str(candidate).strip()
        if key and key in registry and key not in selected:
            selected.append(key)
    if not selected:
        selected = list(DEFAULT_COLLECTION_SHOW_COLUMNS)
    return tuple(selected)


def _build_collection_show_jobs_table(
    jobs: Sequence[Dict[str, Any]],
    *,
    columns: Optional[Sequence[str]],
    now_utc: datetime,
) -> TableSection:
    registry = _collection_show_column_registry()
    resolved_columns = _resolve_collection_show_columns(columns)

    headers = [registry[column_id][0] for column_id in resolved_columns]
    status_columns = tuple(
        idx for idx, column_id in enumerate(resolved_columns) if registry[column_id][2]
    )
    rows: list[list[str]] = []
    for job in jobs:
        rows.append([registry[column_id][1](job, now_utc) for column_id in resolved_columns])

    return TableSection(
        title=f"Jobs ({len(jobs)}):",
        headers=headers,
        rows=rows,
        status_columns=status_columns,
        empty_message="  (no jobs)",
    )


def build_collection_show_report(
    *,
    collection: Any,
    jobs: Sequence[Dict[str, Any]],
    summary: Dict[str, int],
    attempt_mode: str,
    submission_group: Optional[str],
    summary_jobs: Optional[Sequence[Dict[str, Any]]] = None,
    include_jobs_table: bool = True,
    jobs_table_columns: Optional[Sequence[str]] = None,
    metadata_links: Optional[Sequence[Tuple[str, str]]] = None,
    runtime_now: Optional[datetime] = None,
) -> CollectionShowReport:
    """Build view-model for collection show output."""
    summary_source_jobs = summary_jobs if summary_jobs is not None else jobs
    total = max(summary.get("total", 0), 1)
    primary_jobs_count = len(summary_source_jobs)
    submitted_primary_count = sum(
        1 for job in summary_source_jobs if _has_submitted_job_id(job.get("primary_job_id"))
    )
    resubmitted_jobs_count = sum(
        _to_non_negative_int(job.get("resubmissions_count", 0)) for job in summary_source_jobs
    )
    submitted_slurm_jobs_count = submitted_primary_count + resubmitted_jobs_count

    metadata = [
        ("Collection", str(collection.name)),
        ("Description", str(collection.description or "")),
        ("Created", str(collection.created_at)),
        ("Updated", str(collection.updated_at)),
        ("Cluster", str(collection.cluster or "")),
        ("Attempt mode", str(attempt_mode)),
    ]
    if submission_group:
        metadata.append(("Submission group", submission_group))
    for label, value in metadata_links or ():
        if value:
            metadata.append((label, value))

    raw_state_breakdowns: Dict[str, Dict[str, int]] = {}
    for job in summary_source_jobs:
        normalized_state = str(job.get("effective_state", "")).strip().lower()
        if not normalized_state:
            continue
        raw_state = _normalize_raw_state(job.get("effective_state_raw"))
        if raw_state is None:
            continue
        breakdown = raw_state_breakdowns.setdefault(normalized_state, {})
        breakdown[raw_state] = breakdown.get(raw_state, 0) + 1

    summary_metrics = []
    for key in ("completed", "failed", "running", "pending", "not_submitted"):
        count = int(summary.get(key, 0))
        details = None
        breakdown = raw_state_breakdowns.get(key)
        if breakdown:
            sorted_pairs = sorted(
                breakdown.items(),
                key=lambda item: (-item[1], item[0]),
            )
            details = ", ".join(
                f"{raw_state}: {raw_count}" for raw_state, raw_count in sorted_pairs
            )
        summary_metrics.append(
            MetricItem(
                label=key.replace("_", " ").title(),
                value=str(count),
                percent=(count * 100.0 / total),
                state=key.replace("_", " "),
                details=details,
            )
        )

    jobs_table = None
    if include_jobs_table:
        jobs_table = _build_collection_show_jobs_table(
            jobs,
            columns=jobs_table_columns,
            now_utc=runtime_now or datetime.now(timezone.utc),
        )

    return CollectionShowReport(
        title=f"Collection: {collection.name}",
        metadata=metadata,
        summary_title=(
            "Summary: "
            f"{primary_jobs_count} primary jobs | "
            f"{submitted_slurm_jobs_count} submitted SLURM jobs "
            "(incl. resubmissions)"
        ),
        summary_metrics=summary_metrics,
        jobs_table=jobs_table,
    )


def build_collection_list_report(
    *,
    rows: Sequence[Dict[str, Any]],
) -> CollectionListReport:
    """Build view-model for collection list output."""
    table_rows = []
    for row in rows:
        table_rows.append(
            [
                str(row.get("name", "")),
                str(row.get("total", 0)),
                str(row.get("completed", 0)),
                str(row.get("failed", 0)),
                str(row.get("running", 0)),
                str(row.get("pending", 0)),
                str(row.get("not_submitted", 0)),
                str(row.get("updated_at", "") or ""),
            ]
        )

    return CollectionListReport(
        title="Collections",
        table=TableSection(
            title=f"Collections ({len(rows)}):",
            headers=[
                "Name",
                "Total",
                "Completed",
                "Failed",
                "Running",
                "Pending",
                "Not Submitted",
                "Updated",
            ],
            rows=table_rows,
            empty_message="  (no collections)",
        ),
    )


def build_collection_analyze_report(
    *,
    collection_name: str,
    analysis: Dict[str, Any],
    attempt_mode: str,
    min_support: int,
    top_k: int,
    selected_params: Optional[Sequence[str]],
    submission_group: Optional[str] = None,
) -> CollectionAnalyzeReport:
    """Build view-model for collection analyze output."""
    summary = analysis["summary"]
    counts = summary["counts"]
    rates = summary["rates"]
    parameters = analysis["parameters"]
    skipped = analysis["metadata"]["skipped_params"]

    metadata_lines = [
        f"Attempt mode: {attempt_mode} | Min support: {min_support} | Top-k: {top_k}",
    ]
    if submission_group:
        metadata_lines.append(
            f"Submission group: {submission_group} (latest attempt within group)"
        )
    if selected_params:
        metadata_lines.append(f"Selected params: {', '.join(selected_params)}")

    overall_metrics = []
    for state in ["completed", "failed", "running", "pending", "unknown"]:
        overall_metrics.append(
            MetricItem(
                label=state,
                value=str(counts[state]),
                percent=rates[state] * 100.0,
                state=state,
            )
        )

    info_messages: List[str] = []
    parameter_tables: List[TableSection] = []
    top_risky_table: Optional[TableSection] = None
    top_stable_table: Optional[TableSection] = None
    notes: List[str] = [f"Low N marks groups with n < min_support ({min_support})."]

    if not parameters:
        info_messages.append("No analyzable parameters found.")
        if skipped:
            info_messages.append(f"Skipped requested params: {', '.join(skipped)}")
    else:
        varying_parameters = [p for p in parameters if len(p.get("values", [])) >= 2]
        varying_param_names = {p["param"] for p in varying_parameters}

        if not varying_parameters:
            info_messages.append(
                "No parameter breakdown shown: all analyzed parameters have only one distinct value."
            )
            if skipped:
                info_messages.append(f"Skipped requested params: {', '.join(skipped)}")
        else:
            for param_block in varying_parameters:
                rows = []
                for value_entry in param_block["values"]:
                    c = value_entry["counts"]
                    r = value_entry["rates"]
                    rows.append(
                        [
                            str(value_entry["value"]),
                            str(value_entry["n"]),
                            str(c["failed"]),
                            str(c["completed"]),
                            str(c["running"]),
                            str(c["pending"]),
                            str(c["unknown"]),
                            _format_pct(r["failure_rate"]),
                            _format_pct(r["completion_rate"]),
                            "yes" if value_entry["low_sample"] else "",
                        ]
                    )

                parameter_tables.append(
                    TableSection(
                        title=f"Parameter: {param_block['param']}",
                        headers=[
                            "Value",
                            "N",
                            "Failed",
                            "Completed",
                            "Running",
                            "Pending",
                            "Unknown",
                            "Fail %",
                            "Complete %",
                            "Low N",
                        ],
                        rows=rows,
                    )
                )

            top_risky_display = [
                e for e in analysis["top_risky_values"] if e["param"] in varying_param_names
            ]
            top_stable_display = [
                e for e in analysis["top_stable_values"] if e["param"] in varying_param_names
            ]

            top_risky_table = _build_top_values_table(
                "Top risky values:",
                top_risky_display,
                "failure_rate",
            )
            top_stable_table = _build_top_values_table(
                "Top stable values:",
                top_stable_display,
                "completion_rate",
            )

            if skipped:
                notes.append(f"Skipped requested params not found: {', '.join(skipped)}")

    return CollectionAnalyzeReport(
        title=f"Collection Analysis: {collection_name}",
        metadata_lines=metadata_lines,
        overall_title=f"Overall summary ({summary['total_jobs']} jobs):",
        overall_metrics=overall_metrics,
        info_messages=info_messages,
        parameter_tables=parameter_tables,
        top_risky_table=top_risky_table,
        top_stable_table=top_stable_table,
        notes=notes,
    )


def _build_top_values_table(
    title: str,
    entries: Sequence[Dict[str, Any]],
    rate_key: str,
) -> TableSection:
    rows = []
    for entry in entries:
        rows.append(
            [
                str(entry["param"]),
                str(entry["value"]),
                str(entry["n"]),
                _format_pct(entry["rates"][rate_key]),
                str(entry["counts"]["failed"]),
                str(entry["counts"]["completed"]),
            ]
        )
    return TableSection(
        title=title,
        headers=["Param", "Value", "N", "Rate %", "Failed", "Completed"],
        rows=rows,
        empty_message="  (no groups met min support)",
    )


def render_collection_show_report(report: CollectionShowReport, backend: UIBackend) -> None:
    """Render collection show report with selected backend."""
    backend.heading(report.title)
    backend.kv_block(report.metadata)
    backend.metrics(report.summary_title, report.summary_metrics)
    if report.jobs_table is not None:
        backend.table(
            title=report.jobs_table.title,
            headers=report.jobs_table.headers,
            rows=report.jobs_table.rows,
            status_columns=report.jobs_table.status_columns,
            empty_message=report.jobs_table.empty_message,
        )


def render_collection_list_report(report: CollectionListReport, backend: UIBackend) -> None:
    """Render collection list report with selected backend."""
    backend.heading(report.title)
    backend.table(
        title=report.table.title,
        headers=report.table.headers,
        rows=report.table.rows,
        status_columns=report.table.status_columns,
        empty_message=report.table.empty_message,
    )


def render_collection_analyze_report(report: CollectionAnalyzeReport, backend: UIBackend) -> None:
    """Render collection analyze report with selected backend."""
    backend.heading(report.title)
    for line in report.metadata_lines:
        backend.text(f"  {line}")
    backend.divider()
    backend.metrics(report.overall_title, report.overall_metrics)

    for message in report.info_messages:
        backend.section(message if message.endswith(".") else f"{message}")

    for table in report.parameter_tables:
        backend.table(
            title=table.title,
            headers=table.headers,
            rows=table.rows,
            status_columns=table.status_columns,
            empty_message=table.empty_message,
        )

    if report.parameter_tables:
        if report.top_risky_table:
            backend.table(
                title=report.top_risky_table.title,
                headers=report.top_risky_table.headers,
                rows=report.top_risky_table.rows,
                status_columns=report.top_risky_table.status_columns,
                empty_message=report.top_risky_table.empty_message,
            )
        if report.top_stable_table:
            backend.table(
                title=report.top_stable_table.title,
                headers=report.top_stable_table.headers,
                rows=report.top_stable_table.rows,
                status_columns=report.top_stable_table.status_columns,
                empty_message=report.top_stable_table.empty_message,
            )
        backend.notes(report.notes)
