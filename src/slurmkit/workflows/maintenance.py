"""Maintenance workflows for cleanup and sync."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from slurmkit.collections import Collection, CollectionManager
from slurmkit.config import Config
from slurmkit.slurm import find_job_output, parse_timestamp
from slurmkit.sync import SyncManager

from .shared import ReviewPlan, format_review


@dataclass
class CleanOutputsPlan:
    collection: Collection
    files: List[Dict[str, Any]]
    review: ReviewPlan


def _attempt_runtime_seconds(attempt: Dict[str, Any]) -> Optional[int]:
    started_at = parse_timestamp(attempt.get("started_at"))
    completed_at = parse_timestamp(attempt.get("completed_at"))
    if started_at is None or completed_at is None:
        return None
    return max(int((completed_at - started_at).total_seconds()), 0)


def plan_clean_collection_outputs(
    *,
    config: Config,
    collection: Collection,
    threshold_seconds: int,
    min_age_days: int,
) -> CleanOutputsPlan:
    age_cutoff = datetime.now() - timedelta(days=min_age_days)
    jobs_dir = config.get_path("jobs_dir")
    files: List[Dict[str, Any]] = []
    seen_paths: set[str] = set()

    for job in collection.jobs:
        for attempt in job.get("attempts", []):
            if str(attempt.get("state") or "").upper() != "FAILED":
                continue
            completed_at = parse_timestamp(attempt.get("completed_at"))
            if completed_at is None or completed_at > age_cutoff:
                continue
            runtime_seconds = _attempt_runtime_seconds(attempt)
            if runtime_seconds is None or runtime_seconds > threshold_seconds:
                continue

            output_path = attempt.get("output_path")
            path_obj: Optional[Path] = None
            if output_path:
                candidate = Path(str(output_path))
                if candidate.exists():
                    path_obj = candidate
            if path_obj is None and jobs_dir is not None and attempt.get("job_id"):
                matches = find_job_output(str(attempt["job_id"]), jobs_dir, config)
                if matches:
                    path_obj = matches[0]
            if path_obj is None:
                continue

            resolved = str(path_obj.resolve())
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            files.append(
                {
                    "path": path_obj,
                    "job_name": job["job_name"],
                    "job_id": attempt.get("job_id"),
                    "runtime_seconds": runtime_seconds,
                }
            )

    review = format_review(
        "Clean outputs plan",
        [
            f"Collection: {collection.name}",
            f"Threshold: {threshold_seconds}s",
            f"Minimum age: {min_age_days} days",
            f"Files to delete: {len(files)}",
        ],
        [
            f"{item['job_name']} (ID: {item['job_id']}, runtime: {item['runtime_seconds']}s) -> {item['path']}"
            for item in files
        ],
    )
    return CleanOutputsPlan(collection=collection, files=files, review=review)


def execute_clean_collection_outputs(
    *,
    plan: CleanOutputsPlan,
    dry_run: bool,
) -> Dict[str, Any]:
    deleted = 0
    errors: List[str] = []
    for item in plan.files:
        if dry_run:
            continue
        try:
            item["path"].unlink()
            deleted += 1
        except OSError as exc:
            errors.append(f"{item['path']}: {exc}")
    return {"deleted": deleted, "errors": errors}


def clean_wandb_runs(
    *,
    config: Config,
    projects: List[str],
    entity: Optional[str],
    threshold_seconds: int,
    min_age_days: int,
    dry_run: bool,
) -> Dict[str, Any]:
    try:
        from slurmkit.wandb_utils import format_runs_table, get_failed_runs
    except ImportError as exc:
        raise RuntimeError("wandb is not installed. Install it with: pip install wandb") from exc

    resolved_entity = entity or config.get("wandb.entity")
    all_failed_runs = []
    errors = []
    for project in projects:
        try:
            failed_runs = get_failed_runs(
                project=project,
                entity=resolved_entity,
                threshold_seconds=threshold_seconds,
                min_age_days=min_age_days,
                config=config,
            )
            for run_info in failed_runs:
                run_info["project"] = project
            all_failed_runs.extend(failed_runs)
        except Exception as exc:  # pragma: no cover - network/service dependent
            errors.append(f"{project}: {exc}")

    deleted = 0
    if not dry_run:
        for run_info in all_failed_runs:
            try:
                run_info["_run_obj"].delete()
                deleted += 1
            except Exception as exc:  # pragma: no cover - network/service dependent
                errors.append(f"{run_info.get('name', 'unknown')}: {exc}")

    return {
        "runs": all_failed_runs,
        "table": format_runs_table(all_failed_runs),
        "deleted": deleted,
        "errors": errors,
    }


def sync_collections(
    *,
    config: Config,
    collection_names: Optional[List[str]],
    push: bool,
) -> Dict[str, Any]:
    sync_manager = SyncManager(config=config)
    result = sync_manager.sync_all(collection_names=collection_names)
    pushed = False
    if push:
        pushed = sync_manager.push()
    return {
        "hostname": sync_manager.hostname,
        "sync_file": sync_manager.get_sync_file_path(),
        "result": result,
        "pushed": pushed,
    }
