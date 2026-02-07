"""Report builders and renderers for collection-oriented commands."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import yaml

from slurmkit.cli.ui.backend import UIBackend
from slurmkit.cli.ui.models import (
    CollectionAnalyzeReport,
    CollectionShowReport,
    MetricItem,
    TableSection,
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


def build_collection_show_report(
    *,
    collection: Any,
    jobs: Sequence[Dict[str, Any]],
    summary: Dict[str, int],
    attempt_mode: str,
    submission_group: Optional[str],
    show_primary: bool = False,
    show_history: bool = False,
) -> CollectionShowReport:
    """Build view-model for collection show output."""
    total = max(summary.get("total", 0), 1)
    primary_jobs_count = len(jobs)
    submitted_primary_count = sum(
        1 for job in jobs if _has_submitted_job_id(job.get("primary_job_id"))
    )
    resubmitted_jobs_count = sum(
        _to_non_negative_int(job.get("resubmissions_count", 0)) for job in jobs
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

    parameters_yaml = None
    if collection.parameters:
        parameters_yaml = yaml.dump(
            collection.parameters,
            default_flow_style=False,
            sort_keys=False,
            indent=2,
        ).rstrip()

    summary_metrics = []
    for key in ("completed", "failed", "running", "pending", "not_submitted"):
        count = int(summary.get(key, 0))
        summary_metrics.append(
            MetricItem(
                label=key.replace("_", " ").title(),
                value=str(count),
                percent=(count * 100.0 / total),
                state=key.replace("_", " "),
            )
        )

    rows = []
    for job in jobs:
        row = [
            str(job.get("job_name", "")),
            str(job.get("effective_job_id", "N/A")),
            str(job.get("effective_state_raw", "N/A")),
            str(job.get("effective_attempt_label", "")),
            str(job.get("effective_submission_group", "") or ""),
            str(job.get("resubmissions_count", "") or ""),
            str(job.get("effective_hostname", "") or ""),
        ]
        if show_primary:
            row.extend(
                [
                    str(job.get("primary_job_id", "N/A")),
                    str(job.get("primary_state_raw", "N/A")),
                ]
            )
        if show_history:
            row.append(" -> ".join(job.get("attempt_history", [])))

        rows.append(row)

    headers = [
        "Job Name",
        "Job ID",
        "State",
        "Attempt",
        "Submission Group",
        "Resubmissions",
        "Hostname",
    ]
    status_columns = [2]
    if show_primary:
        headers.extend(["Primary Job ID", "Primary State"])
        status_columns.append(len(headers) - 1)
    if show_history:
        headers.append("History")

    jobs_table = TableSection(
        title=f"Jobs ({len(jobs)}):",
        headers=headers,
        rows=rows,
        status_columns=tuple(status_columns),
        empty_message="  (no jobs)",
    )

    return CollectionShowReport(
        title=f"Collection: {collection.name}",
        metadata=metadata,
        parameters_yaml=parameters_yaml,
        summary_title=(
            "Summary: "
            f"{primary_jobs_count} primary jobs | "
            f"{submitted_slurm_jobs_count} submitted SLURM jobs "
            "(incl. resubmissions)"
        ),
        summary_metrics=summary_metrics,
        jobs_table=jobs_table,
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
    if report.parameters_yaml:
        backend.section("Generation Parameters:")
        backend.text(report.parameters_yaml)
    backend.metrics(report.summary_title, report.summary_metrics)
    backend.table(
        title=report.jobs_table.title,
        headers=report.jobs_table.headers,
        rows=report.jobs_table.rows,
        status_columns=report.jobs_table.status_columns,
        empty_message=report.jobs_table.empty_message,
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
