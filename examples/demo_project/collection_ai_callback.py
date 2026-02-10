"""Demo AI callback for collection-final notifications."""

from __future__ import annotations

from typing import Any, Dict, List


def _top_items(rows: List[Dict[str, Any]], key: str, n: int = 2) -> List[str]:
    """Format top risky/stable rows for compact markdown output."""
    items: List[str] = []
    for row in rows[:n]:
        param = row.get("param", "unknown")
        value = row.get("value", "unknown")
        rates = row.get("rates", {}) or {}
        metric = rates.get(key)
        if metric is None:
            items.append(f"- `{param}={value}`")
        else:
            items.append(f"- `{param}={value}` ({key}={metric:.2f})")
    return items


def summarize_collection_report(report: Dict[str, Any]) -> str:
    """
    Return concise markdown summary for collection-final payloads.

    Args:
        report: Deterministic report dictionary produced by slurmkit.

    Returns:
        Markdown string included as `ai_summary` in outgoing payload.
    """
    summary = report.get("summary", {}) or {}
    counts = summary.get("counts", {}) or {}
    failed_jobs = report.get("failed_jobs", []) or []
    risky = report.get("top_risky_values", []) or []
    stable = report.get("top_stable_values", []) or []

    lines = [
        "### AI Summary (Demo Callback)",
        f"- Collection: `{report.get('collection_name', 'unknown')}`",
        f"- Terminal: `{summary.get('terminal')}`",
        (
            "- Counts:"
            f" completed={counts.get('completed', 0)},"
            f" failed={counts.get('failed', 0)},"
            f" unknown={counts.get('unknown', 0)},"
            f" running={counts.get('running', 0)},"
            f" pending={counts.get('pending', 0)}"
        ),
    ]

    if failed_jobs:
        lines.append("- Failed jobs:")
        for row in failed_jobs[:3]:
            lines.append(
                f"  - `{row.get('job_name', 'unknown')}`"
                f" (`{row.get('job_id', 'unknown')}`, state={row.get('state', 'unknown')})"
            )

    risky_lines = _top_items(risky, key="failure_rate")
    if risky_lines:
        lines.append("- Top risky values:")
        lines.extend([f"  {item}" for item in risky_lines])

    stable_lines = _top_items(stable, key="completion_rate")
    if stable_lines:
        lines.append("- Top stable values:")
        lines.extend([f"  {item}" for item in stable_lines])

    return "\n".join(lines)


def summarize_job_payload(payload: Dict[str, Any]) -> str:
    """
    Return concise markdown summary for job-level notification payloads.

    Args:
        payload: Canonical job payload dictionary produced by slurmkit notify job.

    Returns:
        Markdown string included as `ai_summary` in outgoing payload.
    """
    job = payload.get("job", {}) or {}
    collection = payload.get("collection", {}) or {}

    lines = [
        "### AI Summary (Job Demo Callback)",
        f"- Event: `{payload.get('event', 'unknown')}`",
        f"- Job: `{job.get('job_name') or 'unknown'}` (`{job.get('job_id') or 'unknown'}`)",
        f"- State: `{job.get('state') or 'unknown'}`",
    ]

    if job.get("exit_code") is not None:
        lines.append(f"- Exit code: `{job.get('exit_code')}`")

    if collection:
        lines.append(f"- Collection: `{collection.get('name') or 'unknown'}`")

    output_tail = job.get("output_tail")
    if output_tail:
        first_line = str(output_tail).splitlines()[0] if str(output_tail).splitlines() else ""
        if first_line:
            lines.append(f"- First output-tail line: `{first_line}`")

    return "\n".join(lines)
