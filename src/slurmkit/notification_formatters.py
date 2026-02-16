"""Formatting helpers for notification route payloads."""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, Optional, Tuple

EVENT_JOB_COMPLETED = "job_completed"
EVENT_JOB_FAILED = "job_failed"
EVENT_COLLECTION_COMPLETED = "collection_completed"
EVENT_COLLECTION_FAILED = "collection_failed"

_ALLOWED_FORMATTER_FIELDS = {"chat", "email_subject", "email_body"}


def render_default_chat(payload: Dict[str, Any]) -> str:
    """Render human-readable message for chat adapters."""
    event = payload.get("event")
    job = payload.get("job", {}) or {}
    collection = payload.get("collection", {}) or {}

    if event == EVENT_JOB_FAILED:
        title = "SLURMKIT ALERT: Job failed"
    elif event == EVENT_JOB_COMPLETED:
        title = "SLURMKIT: Job completed"
    elif event == EVENT_COLLECTION_FAILED:
        title = "SLURMKIT ALERT: Collection failed"
    elif event == EVENT_COLLECTION_COMPLETED:
        title = "SLURMKIT: Collection completed"
    else:
        title = "SLURMKIT: Test notification"

    lines = [title, f"Event: {event}"]

    if event in (EVENT_COLLECTION_COMPLETED, EVENT_COLLECTION_FAILED):
        lines.append(f"Collection: {collection.get('name') or 'unknown'}")
        report = payload.get("collection_report", {}) or {}
        summary = report.get("summary", {}) or {}
        counts = summary.get("counts", {}) or {}
        lines.append(f"Total jobs: {summary.get('total_jobs', 'unknown')}")
        lines.append(
            "Counts: "
            f"completed={counts.get('completed', 0)}, "
            f"failed={counts.get('failed', 0)}, "
            f"unknown={counts.get('unknown', 0)}, "
            f"running={counts.get('running', 0)}, "
            f"pending={counts.get('pending', 0)}"
        )

        failed_jobs = report.get("failed_jobs", []) or []
        if failed_jobs:
            first = failed_jobs[0]
            lines.append(
                f"Sample issue: {first.get('job_name')} ({first.get('job_id')}) state={first.get('state')}"
            )

        ai_summary = payload.get("ai_summary")
        if ai_summary:
            lines.append("AI summary:")
            lines.append(ai_summary)

    else:
        lines.append(f"Job: {job.get('job_name') or 'unknown'}")
        lines.append(f"Job ID: {job.get('job_id') or 'unknown'}")
        if collection:
            lines.append(f"Collection: {collection.get('name') or 'unknown'}")
        if job.get("exit_code") is not None:
            lines.append(f"Exit code: {job.get('exit_code')}")
        if job.get("state"):
            lines.append(f"State: {job.get('state')}")

        output_tail = job.get("output_tail")
        if output_tail:
            lines.append("Output tail:")
            lines.append(output_tail)

        ai_summary = payload.get("ai_summary")
        if ai_summary:
            lines.append("AI summary:")
            lines.append(ai_summary)

    lines.append(f"Host: {payload.get('host', {}).get('hostname', 'unknown')}")

    return "\n".join(lines)


def render_default_email_subject(payload: Dict[str, Any]) -> str:
    """Render concise subject line for email delivery."""
    event = payload.get("event")
    job = payload.get("job", {}) or {}
    collection = payload.get("collection", {}) or {}

    if event == EVENT_JOB_FAILED:
        return f"SLURMKIT ALERT: job_failed ({job.get('job_id') or 'unknown'})"
    if event == EVENT_JOB_COMPLETED:
        return f"SLURMKIT: job_completed ({job.get('job_id') or 'unknown'})"
    if event == EVENT_COLLECTION_FAILED:
        return f"SLURMKIT ALERT: collection_failed ({collection.get('name') or 'unknown'})"
    if event == EVENT_COLLECTION_COMPLETED:
        return f"SLURMKIT: collection_completed ({collection.get('name') or 'unknown'})"
    return "SLURMKIT: test_notification"


def render_default_email_body(payload: Dict[str, Any]) -> str:
    """Render plain-text email body."""
    return render_default_chat(payload)


def resolve_global_formatter_callback(
    notifications_cfg: Dict[str, Any],
) -> Tuple[Optional[str], Optional[str]]:
    """Resolve optional global formatter callback from notifications config."""
    formatter_cfg = notifications_cfg.get("formatter", {}) or {}
    if not isinstance(formatter_cfg, dict):
        return (
            None,
            "Configuration key 'notifications.formatter' must be a mapping; ignoring formatter callback.",
        )

    raw_callback = formatter_cfg.get("callback")
    if raw_callback is None:
        return None, None
    if not isinstance(raw_callback, str):
        return (
            None,
            "Configuration key 'notifications.formatter.callback' must be a string or null; ignoring.",
        )
    normalized = raw_callback.strip()
    if not normalized:
        return None, None
    return normalized, None


def resolve_formatter_callback_path(
    route_config: Dict[str, Any],
    route_name: str,
    global_callback_path: Optional[str],
) -> Tuple[Optional[str], Optional[str]]:
    """Resolve callback path for one route with route-level override precedence."""
    if "formatter_callback" not in route_config:
        return global_callback_path, None

    raw_callback = route_config.get("formatter_callback")
    if raw_callback is None:
        return None, None
    if not isinstance(raw_callback, str):
        return (
            None,
            f"Route '{route_name}' field 'formatter_callback' must be a string or null; ignoring.",
        )

    normalized = raw_callback.strip()
    if not normalized:
        return None, None
    return normalized, None


def apply_formatter_callback(
    payload: Dict[str, Any],
    callback_loader: Callable[[str], Callable[[Dict[str, Any]], Any]],
    callback_path: Optional[str],
) -> Tuple[Dict[str, str], Optional[str]]:
    """Apply formatter callback and return valid overrides plus optional warning."""
    if callback_path is None:
        return {}, None

    route_name = str(((payload.get("meta") or {}).get("route_name")) or "unknown")

    try:
        callback = callback_loader(callback_path)
    except Exception as exc:
        return (
            {},
            f"Route '{route_name}' formatter callback '{callback_path}' failed to load: {exc}. "
            "Falling back to built-in formatter.",
        )

    try:
        output = callback(copy.deepcopy(payload))
    except Exception as exc:
        return (
            {},
            f"Route '{route_name}' formatter callback '{callback_path}' failed: {exc}. "
            "Falling back to built-in formatter.",
        )

    if not isinstance(output, dict):
        return (
            {},
            f"Route '{route_name}' formatter callback '{callback_path}' must return a mapping, "
            f"got {type(output).__name__}; falling back to built-in formatter.",
        )

    overrides: Dict[str, str] = {}
    invalid_fields: list = []
    invalid_type_fields: list = []

    for key, value in output.items():
        normalized_key = str(key)
        if normalized_key not in _ALLOWED_FORMATTER_FIELDS:
            invalid_fields.append(normalized_key)
            continue
        if not isinstance(value, str):
            invalid_type_fields.append(normalized_key)
            continue
        overrides[normalized_key] = value

    warning_parts: list = []
    if invalid_fields:
        warning_parts.append(
            "ignored unsupported keys: " + ", ".join(sorted(set(invalid_fields)))
        )
    if invalid_type_fields:
        warning_parts.append(
            "fields must be strings: " + ", ".join(sorted(set(invalid_type_fields)))
        )

    if warning_parts:
        return (
            overrides,
            f"Route '{route_name}' formatter callback '{callback_path}' "
            + "; ".join(warning_parts)
            + ". Falling back to built-in formatter for missing/invalid fields.",
        )

    return overrides, None
