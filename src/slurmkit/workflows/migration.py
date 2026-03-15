"""One-time migration helpers for local config and collections."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

from slurmkit.collections import COLLECTION_SCHEMA_VERSION
from slurmkit.config import DEFAULT_CONFIG

from .configuration import deep_merge


@dataclass
class MigrationResult:
    backup_dir: Path
    migrated_config: bool
    migrated_collections: int
    skipped_collections: int


def _timestamp_label() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _ensure_backup_dir(project_root: Path) -> Path:
    backup_dir = project_root / ".slurm-kit" / "backups" / f"migrate-{_timestamp_label()}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def _backup_path(source: Path, backup_dir: Path, project_root: Path) -> None:
    if not source.exists():
        return
    try:
        relative = source.relative_to(project_root)
    except ValueError:
        relative = Path(source.name)
    target = backup_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True)
    else:
        shutil.copy2(source, target)


def _normalize_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    return deep_merge(DEFAULT_CONFIG, raw)


def _migrate_collection_data(raw: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    version = int(raw.get("version", 0) or 0)
    if version == COLLECTION_SCHEMA_VERSION:
        return raw, False

    meta = raw.get("meta", {}) or {}
    generation = meta.get("generation", {}) if isinstance(meta, dict) else {}
    notifications = meta.get("notifications", {}) if isinstance(meta, dict) else {}

    jobs = []
    for raw_job in raw.get("jobs", []) or []:
        attempts = [
            {
                "kind": "primary",
                "job_id": raw_job.get("job_id"),
                "state": raw_job.get("state"),
                "hostname": raw_job.get("hostname"),
                "submitted_at": raw_job.get("submitted_at"),
                "started_at": raw_job.get("started_at"),
                "completed_at": raw_job.get("completed_at"),
                "script_path": raw_job.get("script_path"),
                "output_path": raw_job.get("output_path"),
                "submission_group": None,
                "job_name": raw_job.get("job_name"),
                "parameters": raw_job.get("parameters", {}) or {},
                "extra_params": {},
                "regenerated": False,
                "git_branch": raw_job.get("git_branch"),
                "git_commit_id": raw_job.get("git_commit_id"),
            }
        ]
        for raw_attempt in raw_job.get("resubmissions", []) or []:
            attempts.append(
                {
                    "kind": "resubmission",
                    "job_id": raw_attempt.get("job_id"),
                    "state": raw_attempt.get("state"),
                    "hostname": raw_attempt.get("hostname"),
                    "submitted_at": raw_attempt.get("submitted_at"),
                    "started_at": raw_attempt.get("started_at"),
                    "completed_at": raw_attempt.get("completed_at"),
                    "script_path": raw_attempt.get("script_path"),
                    "output_path": raw_attempt.get("output_path"),
                    "submission_group": raw_attempt.get("submission_group"),
                    "job_name": raw_attempt.get("job_name") or raw_job.get("job_name"),
                    "parameters": raw_attempt.get("parameters", {}) or {},
                    "extra_params": raw_attempt.get("extra_params", {}) or {},
                    "regenerated": raw_attempt.get("regenerated"),
                    "git_branch": raw_attempt.get("git_branch"),
                    "git_commit_id": raw_attempt.get("git_commit_id"),
                }
            )
        jobs.append(
            {
                "job_name": raw_job.get("job_name"),
                "parameters": raw_job.get("parameters", {}) or {},
                "attempts": attempts,
            }
        )

    migrated = {
        "version": COLLECTION_SCHEMA_VERSION,
        "name": raw.get("name", "unnamed"),
        "description": raw.get("description", ""),
        "created_at": raw.get("created_at"),
        "updated_at": raw.get("updated_at"),
        "cluster": raw.get("cluster"),
        "parameters": raw.get("parameters", {}) or {},
        "generation": generation if isinstance(generation, dict) else {},
        "notifications": notifications if isinstance(notifications, dict) else {},
        "jobs": jobs,
    }
    return migrated, True


def run_migration(
    *,
    project_root: Path,
    config_path: Path,
    collections_dir: Path,
) -> MigrationResult:
    backup_dir = _ensure_backup_dir(project_root)
    migrated_config = False
    migrated_collections = 0
    skipped_collections = 0

    if config_path.exists():
        raw_config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        normalized = _normalize_config(raw_config)
        if normalized != raw_config:
            _backup_path(config_path, backup_dir, project_root)
            with open(config_path, "w", encoding="utf-8") as handle:
                yaml.dump(normalized, handle, default_flow_style=False, sort_keys=False)
            migrated_config = True

    if collections_dir.exists():
        for path in sorted(collections_dir.glob("*.yaml")):
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            migrated, changed = _migrate_collection_data(raw)
            if not changed:
                skipped_collections += 1
                continue
            _backup_path(path, backup_dir, project_root)
            with open(path, "w", encoding="utf-8") as handle:
                yaml.dump(migrated, handle, default_flow_style=False, sort_keys=False)
            migrated_collections += 1

    return MigrationResult(
        backup_dir=backup_dir,
        migrated_config=migrated_config,
        migrated_collections=migrated_collections,
        skipped_collections=skipped_collections,
    )
