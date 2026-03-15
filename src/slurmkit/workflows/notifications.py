"""Notification workflows."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from slurmkit.notifications import (
    EVENT_COLLECTION_COMPLETED,
    EVENT_COLLECTION_FAILED,
    EVENT_JOB_COMPLETED,
    EVENT_JOB_FAILED,
    NotificationService,
)


def _compute_exit_code(*, success_count: int, attempted_count: int, strict: bool) -> int:
    if attempted_count == 0:
        return 0
    if success_count == 0:
        return 1
    if strict and success_count != attempted_count:
        return 1
    return 0


def summarize_delivery_results(
    *,
    delivery_results: list[Any],
    errors: list[str],
    warnings: list[str],
) -> list[str]:
    lines: list[str] = []
    for warning in warnings:
        lines.append(f"[route-warning] {warning}")
    for error in errors:
        lines.append(f"[route-error] {error}")
    for result in delivery_results:
        if result.warning:
            lines.append(f"[delivery-warning] {result.route_name}: {result.warning}")
        if result.success:
            suffix = "dry-run" if result.dry_run else f"{result.attempts} attempt(s)"
            lines.append(f"[sent] {result.route_name} ({result.route_type}) - {suffix}")
        else:
            details = result.error or "unknown error"
            if result.status_code is not None:
                details = f"HTTP {result.status_code} - {details}"
            lines.append(f"[failed] {result.route_name} ({result.route_type}) - {details}")
    return lines


@dataclass
class NotificationRun:
    payload: Dict[str, Any]
    route_names: list[str]
    messages: list[str]
    exit_code: int


def run_job_notification(
    *,
    service: NotificationService,
    job_id: Optional[str],
    collection_name: Optional[str],
    exit_code: int,
    on: str,
    routes: Optional[list[str]],
    tail_lines: Optional[int],
    strict: bool,
    dry_run: bool,
) -> NotificationRun:
    resolved_job_id = job_id or os.environ.get("SLURM_JOB_ID")
    if not resolved_job_id:
        raise ValueError("Missing job ID. Pass --job-id or set SLURM_JOB_ID.")

    event = EVENT_JOB_FAILED if int(exit_code) != 0 else EVENT_JOB_COMPLETED
    if on == "failed" and event != EVENT_JOB_FAILED:
        return NotificationRun(payload={}, route_names=[], messages=[
            "Skipping notification: event is job_completed and --on failed is active."
        ], exit_code=0)

    payload, context_warnings = service.build_job_payload(
        job_id=resolved_job_id,
        exit_code=int(exit_code),
        event=event,
        collection_name=collection_name,
        tail_lines=tail_lines,
    )
    messages = [f"[context-warning] {warning}" for warning in context_warnings]
    ai_summary, ai_status, ai_warning = service.run_job_ai_callback(payload)
    if ai_warning:
        messages.append(f"[ai-warning] {ai_warning}")
    payload["ai_status"] = ai_status
    payload["ai_summary"] = ai_summary

    route_resolution = service.resolve_routes(
        event=event,
        route_names=routes,
        collection_name=(
            payload.get("collection", {}).get("name")
            if isinstance(payload.get("collection"), dict)
            else None
        ),
    )
    if not route_resolution.routes and not route_resolution.errors:
        messages.append(f"No notification routes matched event '{event}'.")
        return NotificationRun(payload=payload, route_names=[], messages=messages, exit_code=0)

    if dry_run:
        messages.append("Dry run enabled. Payload preview:")
        messages.append(json.dumps(payload, indent=2, default=str))
        if route_resolution.routes:
            messages.append("Resolved routes: " + ", ".join(route.name for route in route_resolution.routes))
        else:
            messages.append("Resolved routes: (none)")

    delivery_results = service.dispatch(
        payload=payload,
        routes=route_resolution.routes,
        dry_run=dry_run,
    )
    messages.extend(
        summarize_delivery_results(
            delivery_results=delivery_results,
            errors=route_resolution.errors,
            warnings=route_resolution.warnings,
        )
    )
    success_count = sum(1 for result in delivery_results if result.success)
    attempted_count = len(delivery_results) + len(route_resolution.errors)
    return NotificationRun(
        payload=payload,
        route_names=[route.name for route in route_resolution.routes],
        messages=messages,
        exit_code=_compute_exit_code(
            success_count=success_count,
            attempted_count=attempted_count,
            strict=strict,
        ),
    )


def run_test_notification(
    *,
    service: NotificationService,
    routes: Optional[list[str]],
    strict: bool,
    dry_run: bool,
) -> NotificationRun:
    payload = service.build_test_payload()
    route_resolution = service.resolve_routes(event=None, route_names=routes)
    messages: list[str] = []
    if not route_resolution.routes and not route_resolution.errors:
        messages.append("No enabled notification routes configured.")
        return NotificationRun(payload=payload, route_names=[], messages=messages, exit_code=0)

    if dry_run:
        messages.append("Dry run enabled. Payload preview:")
        messages.append(json.dumps(payload, indent=2, default=str))
        if route_resolution.routes:
            messages.append("Resolved routes: " + ", ".join(route.name for route in route_resolution.routes))
        else:
            messages.append("Resolved routes: (none)")

    delivery_results = service.dispatch(payload=payload, routes=route_resolution.routes, dry_run=dry_run)
    messages.extend(
        summarize_delivery_results(
            delivery_results=delivery_results,
            errors=route_resolution.errors,
            warnings=route_resolution.warnings,
        )
    )
    success_count = sum(1 for result in delivery_results if result.success)
    attempted_count = len(delivery_results) + len(route_resolution.errors)
    return NotificationRun(
        payload=payload,
        route_names=[route.name for route in route_resolution.routes],
        messages=messages,
        exit_code=_compute_exit_code(
            success_count=success_count,
            attempted_count=attempted_count,
            strict=strict,
        ),
    )


def run_collection_final_notification(
    *,
    service: NotificationService,
    job_id: Optional[str],
    trigger_exit_code: Optional[int],
    collection_name: Optional[str],
    routes: Optional[list[str]],
    strict: bool,
    dry_run: bool,
    force: bool,
    no_refresh: bool,
) -> NotificationRun:
    trigger_job_id = job_id or os.environ.get("SLURM_JOB_ID")
    if not trigger_job_id:
        raise ValueError("Missing job ID. Pass --job-id or set SLURM_JOB_ID.")

    resolution = service.resolve_collection_for_job(
        job_id=trigger_job_id,
        collection_name=collection_name,
    )
    messages = [f"[context-warning] {warning}" for warning in resolution.warnings]
    if resolution.collection is None:
        raise ValueError("Could not resolve a single collection for collection-final notification.")

    resolved_collection_name = resolution.collection.name
    manager = service.collection_manager
    with service.collection_lock(resolved_collection_name):
        collection = manager.load(resolved_collection_name)
        if not no_refresh:
            collection.refresh_states()
            manager.save(collection)

        cfg_warnings: List[str] = []
        cfg = service.get_collection_final_config(collection=collection, warnings=cfg_warnings)
        messages.extend(f"[context-warning] {warning}" for warning in cfg_warnings)

        finality = service.evaluate_collection_finality(
            collection=collection,
            attempt_mode=cfg.attempt_mode,
            trigger_job_id=trigger_job_id,
            trigger_exit_code=trigger_exit_code,
        )
        messages.extend(f"[finality-warning] {warning}" for warning in finality.warnings)
        if not finality.terminal:
            messages.append(
                "Collection is not terminal yet: "
                f"pending={finality.counts.get('pending', 0)}, running={finality.counts.get('running', 0)}"
            )
            return NotificationRun(payload={}, route_names=[], messages=messages, exit_code=0)

        event = finality.event
        if event not in (EVENT_COLLECTION_COMPLETED, EVENT_COLLECTION_FAILED):
            raise ValueError("Failed to determine collection terminal event.")

        fingerprint = service.compute_collection_final_fingerprint(
            collection_name=collection.name,
            event=event,
            effective_rows=finality.effective_rows,
        )
        if not force and service.should_skip_collection_final(
            collection=collection,
            event=event,
            fingerprint=fingerprint,
        ):
            messages.append(
                "Skipping notification: collection-final notification for this terminal snapshot was already sent."
            )
            return NotificationRun(payload={}, route_names=[], messages=messages, exit_code=0)

        report = service.build_collection_report(
            collection=collection,
            trigger_job_id=trigger_job_id,
            attempt_mode=cfg.attempt_mode,
            min_support=cfg.min_support,
            top_k=cfg.top_k,
            failed_tail_lines=cfg.include_failed_output_tail_lines,
            precomputed_finality=finality,
        )
        ai_summary, ai_status, ai_warning = service.run_collection_ai_callback(report)
        if ai_warning:
            messages.append(f"[ai-warning] {ai_warning}")
        payload = service.build_collection_final_payload(
            collection=collection,
            event=event,
            trigger_job_id=trigger_job_id,
            report=report,
            ai_status=ai_status,
            ai_summary=ai_summary,
        )

        route_resolution = service.resolve_routes(
            event=event,
            route_names=routes,
            collection_name=collection.name,
        )
        if not route_resolution.routes and not route_resolution.errors:
            messages.append(f"No notification routes matched event '{event}'.")
            return NotificationRun(payload=payload, route_names=[], messages=messages, exit_code=0)

        if dry_run:
            messages.append("Dry run enabled. Payload preview:")
            messages.append(json.dumps(payload, indent=2, default=str))
            if route_resolution.routes:
                messages.append("Resolved routes: " + ", ".join(route.name for route in route_resolution.routes))
            else:
                messages.append("Resolved routes: (none)")

        delivery_results = service.dispatch(
            payload=payload,
            routes=route_resolution.routes,
            dry_run=dry_run,
        )
        messages.extend(
            summarize_delivery_results(
                delivery_results=delivery_results,
                errors=route_resolution.errors,
                warnings=route_resolution.warnings,
            )
        )

        success_count = sum(1 for result in delivery_results if result.success)
        attempted_count = len(delivery_results) + len(route_resolution.errors)
        computed_exit_code = _compute_exit_code(
            success_count=success_count,
            attempted_count=attempted_count,
            strict=strict,
        )
        if computed_exit_code == 0 and not dry_run:
            service.mark_collection_final_sent(
                collection=collection,
                event=event,
                fingerprint=fingerprint,
                trigger_job_id=trigger_job_id,
            )
            manager.save(collection)
        return NotificationRun(
            payload=payload,
            route_names=[route.name for route in route_resolution.routes],
            messages=messages,
            exit_code=computed_exit_code,
        )
