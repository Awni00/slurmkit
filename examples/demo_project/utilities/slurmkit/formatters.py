"""Demo formatter callbacks for slurmkit notification routes."""

from __future__ import annotations

from typing import Any, Dict


def _route_meta(payload: Dict[str, Any]) -> tuple[str, str]:
    meta = payload.get("meta", {}) or {}
    route_name = str(meta.get("route_name") or "unknown-route")
    route_type = str(meta.get("route_type") or "unknown-type")
    return route_name, route_type


def _job_bits(payload: Dict[str, Any]) -> tuple[str, str, str]:
    job = payload.get("job", {}) or {}
    job_id = str(job.get("job_id") or "unknown")
    job_name = str(job.get("job_name") or "unknown")
    event = str(payload.get("event") or "unknown")
    return event, job_id, job_name


def format_notification(payload: Dict[str, Any]) -> Dict[str, str]:
    """Return a global demo formatter payload."""
    route_name, route_type = _route_meta(payload)
    event, job_id, job_name = _job_bits(payload)
    collection = payload.get("collection", {}) or {}
    collection_name = str(collection.get("name") or "n/a")

    chat = (
        f"[demo:{route_name}] event={event} job_id={job_id} "
        f"job_name={job_name} collection={collection_name} route_type={route_type}"
    )
    subject = f"[demo:{route_name}] {event} (job={job_id})"
    body_lines = [
        "Demo formatter callback output",
        f"Route: {route_name} ({route_type})",
        f"Event: {event}",
        f"Job: {job_name} ({job_id})",
        f"Collection: {collection_name}",
    ]

    return {
        "chat": chat,
        "email_subject": subject,
        "email_body": "\n".join(body_lines),
    }


def format_local_email(payload: Dict[str, Any]) -> Dict[str, str]:
    """Return a route-specific email formatter override."""
    event, job_id, job_name = _job_bits(payload)
    return {
        "email_subject": f"[local-email-demo] {event} :: {job_id}",
        "email_body": "\n".join(
            [
                "Local email formatter override",
                f"Event: {event}",
                f"Job: {job_name} ({job_id})",
            ]
        ),
    }
