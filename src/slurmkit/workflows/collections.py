"""Collection inspection and maintenance workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from slurmkit.collections import Collection, CollectionManager, JOB_STATE_PENDING, JOB_STATE_RUNNING
from slurmkit.config import Config
from slurmkit.slurm import cancel_job, get_active_queue_timing

from .shared import ReviewPlan, format_review


@dataclass
class RenderableReport:
    report: Any
    payload: Optional[Dict[str, Any]]


def _parse_sort_timestamp(value: Any) -> Optional[float]:
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
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    try:
        return parsed.timestamp()
    except (OverflowError, OSError, ValueError):
        return None


def _sort_collection_summaries(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def _sort_key(row: Dict[str, Any]) -> tuple[bool, float, str]:
        timestamp = _parse_sort_timestamp(row.get("updated_at"))
        return (
            timestamp is None,
            -timestamp if timestamp is not None else 0.0,
            str(row.get("name", "")),
        )

    return sorted(
        rows,
        key=_sort_key,
    )


def _row_eta_key(row: Dict[str, Any]) -> tuple[str, int]:
    job_name = str(row.get("job_name", ""))
    try:
        attempt_index = int(row.get("effective_attempt_index", -1))
    except (TypeError, ValueError):
        attempt_index = -1
    return job_name, attempt_index


def _empty_eta_fields() -> Dict[str, Optional[Any]]:
    return {
        "effective_eta_start_at": None,
        "effective_eta_completion_at": None,
        "effective_eta_remaining_seconds": None,
    }


def _parse_eta_timestamp(value: Any, *, local_tz: tzinfo) -> Optional[datetime]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text in {"N/A", "UNKNOWN", "Unknown"}:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=local_tz)
    return parsed.astimezone(local_tz)


def list_collection_summaries(
    *,
    manager: CollectionManager,
    attempt_mode: str = "latest",
) -> List[Dict[str, Any]]:
    rows = manager.list_collections_with_summary(attempt_mode=attempt_mode)
    return _sort_collection_summaries(rows)


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
    state_filter: str = "all",
    json_mode: bool,
    attempt_mode: str,
    submission_group: Optional[str] = None,
    include_jobs_table: bool = True,
    include_jobs_in_payload: bool = True,
    jobs_table_columns: Optional[List[str]] = None,
    compact_payload: bool = False,
) -> RenderableReport:
    from slurmkit.cli.ui import build_collection_show_report

    def _resolve_link_path(raw: Any) -> Optional[str]:
        if raw is None:
            return None
        text = str(raw).strip()
        if not text:
            return None
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = config.project_root / path
        try:
            return str(path.resolve())
        except OSError:
            return str(path)

    def _display_link_path(resolved: Optional[str]) -> Optional[str]:
        if resolved is None:
            return None
        text = str(resolved).strip()
        if not text:
            return None
        path = Path(text).expanduser()
        if not path.is_absolute():
            return text
        try:
            return str(path.relative_to(config.project_root.resolve()))
        except ValueError:
            return str(path)

    collection = manager.load(name)
    if refresh:
        collection.refresh_states()
        manager.save(collection)

    effective_state = None if state_filter == "all" else state_filter
    all_effective_jobs = collection.get_effective_jobs(
        attempt_mode=attempt_mode,
        submission_group=submission_group,
        state=None,
    )
    effective_jobs = all_effective_jobs
    if effective_state is not None:
        effective_jobs = collection.get_effective_jobs(
            attempt_mode=attempt_mode,
            submission_group=submission_group,
            state=effective_state,
        )
    effective_summary = collection.get_effective_summary(
        attempt_mode=attempt_mode,
        submission_group=submission_group,
    )
    summary_jobs = all_effective_jobs

    now_local = datetime.now().astimezone().replace(microsecond=0)
    runtime_now = now_local.astimezone(timezone.utc)
    eta_by_row: Dict[tuple[str, int], Dict[str, Optional[Any]]] = {
        _row_eta_key(row): _empty_eta_fields()
        for row in summary_jobs
    }
    active_rows: List[Dict[str, Any]] = []
    active_job_ids: set[str] = set()
    for row in summary_jobs:
        normalized = str(row.get("effective_state", "")).strip().lower()
        effective_job_id = row.get("effective_job_id")
        if normalized not in {JOB_STATE_PENDING, JOB_STATE_RUNNING}:
            continue
        if effective_job_id is None or not str(effective_job_id).strip():
            continue
        active_rows.append(row)
        active_job_ids.add(str(effective_job_id).strip())

    queue_timing = (
        get_active_queue_timing(job_ids=sorted(active_job_ids))
        if active_job_ids
        else {}
    )
    estimable_active_jobs = 0
    aggregate_completion: Optional[datetime] = None
    for row in active_rows:
        key = _row_eta_key(row)
        normalized = str(row.get("effective_state", "")).strip().lower()
        job_id = str(row.get("effective_job_id")).strip()
        timing = queue_timing.get(job_id, {})

        start_dt: Optional[datetime] = None
        completion_dt: Optional[datetime] = None

        if normalized == JOB_STATE_PENDING:
            start_dt = _parse_eta_timestamp(
                timing.get("estimated_start_at"),
                local_tz=now_local.tzinfo,
            )
            time_limit_seconds = timing.get("time_limit_seconds")
            if start_dt is not None and isinstance(time_limit_seconds, int):
                completion_dt = start_dt + timedelta(seconds=time_limit_seconds)

        elif normalized == JOB_STATE_RUNNING:
            time_left_seconds = timing.get("time_left_seconds")
            if isinstance(time_left_seconds, int):
                completion_dt = now_local + timedelta(seconds=time_left_seconds)
                start_dt = _parse_eta_timestamp(
                    row.get("effective_started_at"),
                    local_tz=now_local.tzinfo,
                )
            else:
                start_dt = _parse_eta_timestamp(
                    row.get("effective_started_at"),
                    local_tz=now_local.tzinfo,
                )
                time_limit_seconds = timing.get("time_limit_seconds")
                if start_dt is not None and isinstance(time_limit_seconds, int):
                    completion_dt = start_dt + timedelta(seconds=time_limit_seconds)

        if completion_dt is None:
            eta_by_row[key] = _empty_eta_fields()
            continue

        estimable_active_jobs += 1
        if aggregate_completion is None or completion_dt > aggregate_completion:
            aggregate_completion = completion_dt
        eta_by_row[key] = {
            "effective_eta_start_at": (
                start_dt.isoformat(timespec="seconds")
                if start_dt is not None
                else None
            ),
            "effective_eta_completion_at": completion_dt.isoformat(timespec="seconds"),
            "effective_eta_remaining_seconds": max(
                int((completion_dt - now_local).total_seconds()),
                0,
            ),
        }

    for row in summary_jobs:
        row.update(eta_by_row.get(_row_eta_key(row), _empty_eta_fields()))
    for row in effective_jobs:
        row.update(eta_by_row.get(_row_eta_key(row), _empty_eta_fields()))

    active_jobs = len(active_rows)
    estimated_completion_at = (
        aggregate_completion.isoformat(timespec="seconds")
        if aggregate_completion is not None
        else None
    )
    estimated_remaining_seconds = None
    if aggregate_completion is not None:
        estimated_remaining_seconds = max(
            int((aggregate_completion - now_local).total_seconds()),
            0,
        )

    generation = collection.generation if isinstance(collection.generation, dict) else {}
    links = {
        "spec_path": _resolve_link_path(generation.get("spec_path")),
        "collection_file": _resolve_link_path(manager.collections_dir / f"{collection.name}.yaml"),
        "scripts_dir": _resolve_link_path(generation.get("scripts_dir")),
        "logs_dir": _resolve_link_path(generation.get("logs_dir")),
    }
    metadata_links = [
        ("Spec", _display_link_path(links["spec_path"])),
        ("Collection File", _display_link_path(links["collection_file"])),
        ("Scripts Dir", _display_link_path(links["scripts_dir"])),
        ("Logs Dir", _display_link_path(links["logs_dir"])),
    ]

    payload = None
    if json_mode:
        if compact_payload:
            payload = {
                "collection": {
                    "name": collection.name,
                    "description": collection.description,
                    "created_at": collection.created_at,
                    "updated_at": collection.updated_at,
                    "cluster": collection.cluster,
                    "attempt_mode": attempt_mode,
                    "submission_group": submission_group,
                    "estimated_completion_at": estimated_completion_at,
                    "estimated_remaining_seconds": estimated_remaining_seconds,
                    "estimable_active_jobs": estimable_active_jobs,
                    "active_jobs": active_jobs,
                },
                "summary": effective_summary,
                "links": links,
            }
        else:
            payload = {
                **collection.to_dict(),
                "effective_summary": effective_summary,
                "effective_attempt_mode": attempt_mode,
                "effective_submission_group": submission_group,
                "links": links,
                "estimated_completion_at": estimated_completion_at,
                "estimated_remaining_seconds": estimated_remaining_seconds,
                "estimable_active_jobs": estimable_active_jobs,
                "active_jobs": active_jobs,
            }
            if include_jobs_in_payload:
                serialized_jobs = []
                for row in effective_jobs:
                    serialized_jobs.append(
                        {
                            "job_name": row["job_name"],
                            "parameters": row.get("parameters", {}),
                            "attempts_count": row.get("attempts_count"),
                            "resubmissions_count": row.get("resubmissions_count"),
                            "effective_job_id": row.get("effective_job_id"),
                            "effective_state": row.get("effective_state_raw"),
                            "effective_state_normalized": row.get("effective_state"),
                            # JSON/debug contract: expose full row diagnostics
                            # without altering default human table rendering.
                            "effective_raw_state": row.get("effective_raw_state"),
                            "effective_hostname": row.get("effective_hostname"),
                            "effective_attempt_label": row.get("effective_attempt_label"),
                            "effective_attempt_index": row.get("effective_attempt_index"),
                            "effective_submission_group": row.get("effective_submission_group"),
                            "effective_started_at": row.get("effective_started_at"),
                            "effective_completed_at": row.get("effective_completed_at"),
                            "effective_eta_start_at": row.get("effective_eta_start_at"),
                            "effective_eta_completion_at": row.get("effective_eta_completion_at"),
                            "effective_eta_remaining_seconds": row.get("effective_eta_remaining_seconds"),
                            "effective_script_path": row.get("effective_script_path"),
                            "effective_output_path": row.get("effective_output_path"),
                            "effective_attempt_history": row.get("attempt_history", []),
                            "primary_job_id": row.get("primary_job_id"),
                            "primary_state": row.get("primary_state_raw"),
                        }
                    )
                payload["jobs"] = serialized_jobs

    report = build_collection_show_report(
        collection=collection,
        jobs=effective_jobs,
        summary=effective_summary,
        attempt_mode=attempt_mode,
        submission_group=submission_group,
        summary_jobs=summary_jobs,
        include_jobs_table=include_jobs_table,
        jobs_table_columns=jobs_table_columns,
        runtime_now=runtime_now,
        estimated_completion_at=estimated_completion_at,
        estimated_remaining_seconds=estimated_remaining_seconds,
        estimable_active_jobs=estimable_active_jobs,
        active_jobs=active_jobs,
        metadata_links=[
            (label, str(value))
            for label, value in metadata_links
            if value is not None and str(value).strip()
        ],
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
    from slurmkit.cli.ui import build_collection_analyze_report

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
