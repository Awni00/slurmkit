"""Collection inspection and maintenance workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from slurmkit.cli.ui import (
    build_collection_analyze_report,
    build_collection_show_report,
)
from slurmkit.collections import Collection, CollectionManager, JOB_STATE_PENDING, JOB_STATE_RUNNING
from slurmkit.config import Config
from slurmkit.slurm import cancel_job

from .shared import ReviewPlan, format_review


@dataclass
class RenderableReport:
    report: Any
    payload: Optional[Dict[str, Any]]


def list_collection_summaries(
    *,
    manager: CollectionManager,
    attempt_mode: str = "latest",
) -> List[Dict[str, Any]]:
    return manager.list_collections_with_summary(attempt_mode=attempt_mode)


def load_collection(
    *,
    manager: CollectionManager,
    name: str,
) -> Collection:
    return manager.load(name)


def show_collection(
    *,
    config: Config,
    manager: CollectionManager,
    name: str,
    refresh: bool,
    state_filter: str,
    json_mode: bool,
    attempt_mode: str,
    show_primary: bool,
    show_history: bool,
    submission_group: Optional[str] = None,
) -> RenderableReport:
    collection = manager.load(name)
    if refresh:
        collection.refresh_states()
        manager.save(collection)

    effective_state = None if state_filter == "all" else state_filter
    effective_jobs = collection.get_effective_jobs(
        attempt_mode=attempt_mode,
        submission_group=submission_group,
        state=effective_state,
    )
    effective_summary = collection.get_effective_summary(
        attempt_mode=attempt_mode,
        submission_group=submission_group,
    )
    summary_jobs = effective_jobs
    if effective_state is not None:
        summary_jobs = collection.get_effective_jobs(
            attempt_mode=attempt_mode,
            submission_group=submission_group,
            state=None,
        )

    serialized_jobs = []
    for row in effective_jobs:
        serialized = {
            "job_name": row["job_name"],
            "parameters": row.get("parameters", {}),
            "attempts_count": row.get("attempts_count"),
            "resubmissions_count": row.get("resubmissions_count"),
            "effective_job_id": row.get("effective_job_id"),
            "effective_state": row.get("effective_state_raw"),
            "effective_state_normalized": row.get("effective_state"),
            "effective_hostname": row.get("effective_hostname"),
            "effective_attempt_label": row.get("effective_attempt_label"),
            "effective_attempt_index": row.get("effective_attempt_index"),
            "effective_submission_group": row.get("effective_submission_group"),
            "primary_job_id": row.get("primary_job_id"),
            "primary_state": row.get("primary_state_raw"),
        }
        if show_history:
            serialized["effective_attempt_history"] = row.get("attempt_history", [])
        serialized_jobs.append(serialized)

    payload = None
    if json_mode:
        payload = {
            **collection.to_dict(),
            "jobs": serialized_jobs,
            "effective_summary": effective_summary,
            "effective_attempt_mode": attempt_mode,
            "effective_submission_group": submission_group,
        }

    report = build_collection_show_report(
        collection=collection,
        jobs=effective_jobs,
        summary=effective_summary,
        attempt_mode=attempt_mode,
        submission_group=submission_group,
        show_primary=show_primary,
        show_history=show_history,
        summary_jobs=summary_jobs,
    )
    return RenderableReport(report=report, payload=payload)


def analyze_collection(
    *,
    manager: CollectionManager,
    name: str,
    refresh: bool,
    json_mode: bool,
    attempt_mode: str,
    min_support: int,
    params: Optional[List[str]],
    submission_group: Optional[str],
    top_k: int,
) -> RenderableReport:
    collection = manager.load(name)
    if refresh:
        collection.refresh_states()
        manager.save(collection)
    analysis = collection.analyze_status_by_params(
        attempt_mode=attempt_mode,
        submission_group=submission_group,
        min_support=min_support,
        selected_params=params,
        top_k=top_k,
    )
    payload = analysis if json_mode else None
    report = build_collection_analyze_report(
        collection_name=collection.name,
        analysis=analysis,
        attempt_mode=analysis["metadata"]["attempt_mode"],
        min_support=min_support,
        top_k=top_k,
        selected_params=params,
        submission_group=submission_group,
    )
    return RenderableReport(report=report, payload=payload)


def refresh_collections(
    *,
    manager: CollectionManager,
    name: Optional[str],
    refresh_all: bool,
) -> Dict[str, int]:
    names = manager.list_collections() if refresh_all else [str(name)]
    total_updates = 0
    refreshed = 0
    for collection_name in names:
        if not collection_name or not manager.exists(collection_name):
            continue
        collection = manager.load(collection_name)
        total_updates += collection.refresh_states()
        manager.save(collection)
        refreshed += 1
    return {"collections_refreshed": refreshed, "jobs_updated": total_updates}


@dataclass
class CancelPlan:
    collection: Collection
    targets: List[Dict[str, Any]]
    review: ReviewPlan


def plan_cancel_collection(
    *,
    collection: Collection,
) -> CancelPlan:
    targets = []
    for job in collection.jobs:
        for index, attempt in enumerate(job.get("attempts", [])):
            normalized = collection._normalize_state(attempt.get("state"))
            if normalized not in {JOB_STATE_PENDING, JOB_STATE_RUNNING}:
                continue
            targets.append(
                {
                    "job_name": job["job_name"],
                    "attempt_index": index,
                    "attempt_label": "primary" if index == 0 else f"resubmission #{index}",
                    "job_id": str(attempt.get("job_id")),
                    "state": str(attempt.get("state") or "UNKNOWN"),
                }
            )
    review = format_review(
        "Cancel plan",
        [
            f"Collection: {collection.name}",
            f"Active attempts to cancel: {len(targets)}",
        ],
        [
            f"{target['job_name']} [{target['attempt_label']}] (ID: {target['job_id']}, State: {target['state']})"
            for target in targets
        ],
    )
    return CancelPlan(collection=collection, targets=targets, review=review)


def execute_cancel_collection(
    *,
    manager: CollectionManager,
    plan: CancelPlan,
    dry_run: bool,
) -> Dict[str, Any]:
    cancelled_ids: List[str] = []
    errors: List[str] = []
    for target in plan.targets:
        if dry_run:
            continue
        success, message = cancel_job(target["job_id"], dry_run=False)
        if success:
            cancelled_ids.append(target["job_id"])
        else:
            errors.append(f"{target['job_id']}: {message}")

    if not dry_run and cancelled_ids:
        for job in plan.collection.jobs:
            for attempt in job.get("attempts", []):
                if str(attempt.get("job_id")) in cancelled_ids:
                    attempt["state"] = "CANCELLED"
        manager.save(plan.collection)

    return {"cancelled_ids": cancelled_ids, "errors": errors}


def delete_collection(
    *,
    manager: CollectionManager,
    name: str,
) -> bool:
    return manager.delete(name)
