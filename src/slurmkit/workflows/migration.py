"""One-time migration helpers for local config, collections, and specs."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple

import yaml

from slurmkit.collections import COLLECTION_SCHEMA_VERSION
from slurmkit.config import (
    BACKUPS_SUBDIR,
    COLLECTIONS_SUBDIR,
    CONFIG_FILENAME,
    JOB_LOGS_SUBDIR,
    JOB_SCRIPTS_SUBDIR,
    METADATA_DIRNAME,
)

from .configuration import normalize_config_data


OLD_METADATA_DIRNAME = ".slurm-kit"
OLD_COLLECTIONS_DIRNAME = ".job-collections"


@dataclass
class MigrationResult:
    backup_dir: Path
    migrated_config: bool
    migrated_collections: int
    skipped_collections: int
    migrated_specs: int
    skipped_specs: int


def _timestamp_label() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _metadata_dir(project_root: Path) -> Path:
    return project_root / METADATA_DIRNAME


def _collections_dir(project_root: Path) -> Path:
    return _metadata_dir(project_root) / COLLECTIONS_SUBDIR


def _backup_dir(project_root: Path) -> Path:
    return _metadata_dir(project_root) / BACKUPS_SUBDIR / f"migrate-{_timestamp_label()}"


def _backup_path(source: Path, backup_dir: Path, project_root: Path) -> None:
    if not source.exists():
        return
    try:
        relative = source.relative_to(project_root)
    except ValueError:
        relative = Path(source.name)
    target = backup_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _move_tree_contents(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        destination = target / child.name
        if destination.exists() and child.is_dir() and destination.is_dir():
            _move_tree_contents(child, destination)
            if child.exists():
                shutil.rmtree(child)
            continue
        if destination.exists():
            raise RuntimeError(f"Cannot migrate path because destination already exists: {destination}")
        shutil.move(str(child), str(destination))
    if source.exists():
        source.rmdir()


def _ensure_new_layout(project_root: Path) -> Tuple[Path, Path]:
    old_metadata_dir = project_root / OLD_METADATA_DIRNAME
    new_metadata_dir = _metadata_dir(project_root)

    if old_metadata_dir.exists():
        if new_metadata_dir.exists():
            _move_tree_contents(old_metadata_dir, new_metadata_dir)
        else:
            old_metadata_dir.rename(new_metadata_dir)
    else:
        new_metadata_dir.mkdir(parents=True, exist_ok=True)

    collections_dir = _collections_dir(project_root)
    collections_dir.mkdir(parents=True, exist_ok=True)
    (new_metadata_dir / "sync").mkdir(parents=True, exist_ok=True)

    old_collections_dir = project_root / OLD_COLLECTIONS_DIRNAME
    if old_collections_dir.exists():
        for child in sorted(old_collections_dir.glob("*.yaml")):
            destination = collections_dir / child.name
            if destination.exists():
                raise RuntimeError(f"Cannot migrate collection because destination already exists: {destination}")
            shutil.move(str(child), str(destination))
        shutil.rmtree(old_collections_dir)

    return new_metadata_dir / CONFIG_FILENAME, collections_dir


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


def _resolve_old_spec_path(spec_path: Path, raw_value: Any) -> Path:
    value = Path(str(raw_value))
    if not value.is_absolute():
        value = spec_path.parent / value
    return value.resolve()


def _derive_job_subdir(spec_path: Path, spec_data: Dict[str, Any], jobs_dir: Path) -> str | None:
    if spec_data.get("job_subdir"):
        return str(spec_data["job_subdir"])

    output_dir = spec_data.get("output_dir")
    logs_dir = spec_data.get("logs_dir")
    if output_dir is None and logs_dir is None:
        return None

    candidates: list[Path] = []
    if output_dir is not None:
        resolved_output = _resolve_old_spec_path(spec_path, output_dir)
        if resolved_output.name != JOB_SCRIPTS_SUBDIR:
            raise ValueError(f"{spec_path}: output_dir must end with '{JOB_SCRIPTS_SUBDIR}' to migrate automatically.")
        candidates.append(resolved_output.parent)
    if logs_dir is not None:
        resolved_logs = _resolve_old_spec_path(spec_path, logs_dir)
        if resolved_logs.name != JOB_LOGS_SUBDIR:
            raise ValueError(f"{spec_path}: logs_dir must end with '{JOB_LOGS_SUBDIR}' to migrate automatically.")
        candidates.append(resolved_logs.parent)

    if not candidates:
        return None

    job_dir = candidates[0]
    if any(candidate != job_dir for candidate in candidates[1:]):
        raise ValueError(f"{spec_path}: output_dir and logs_dir do not refer to the same job directory.")

    try:
        return job_dir.relative_to(jobs_dir.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(
            f"{spec_path}: output/log paths must live under jobs_dir '{jobs_dir}'."
        ) from exc


def _migrate_spec_file(spec_path: Path, jobs_dir: Path, backup_dir: Path, project_root: Path) -> bool:
    raw = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return False

    job_subdir = _derive_job_subdir(spec_path, raw, jobs_dir)
    if job_subdir is None:
        return False

    updated = dict(raw)
    updated.pop("output_dir", None)
    updated.pop("logs_dir", None)
    updated["job_subdir"] = job_subdir
    if updated == raw:
        return False

    _backup_path(spec_path, backup_dir, project_root)
    with open(spec_path, "w", encoding="utf-8") as handle:
        yaml.dump(updated, handle, default_flow_style=False, sort_keys=False)
    return True


def _iter_spec_candidates(project_root: Path) -> list[Path]:
    candidates: list[Path] = []
    skip_dirs = {METADATA_DIRNAME, OLD_METADATA_DIRNAME, OLD_COLLECTIONS_DIRNAME, ".git"}
    for pattern in ("*.yaml", "*.yml"):
        for path in project_root.rglob(pattern):
            if any(part in skip_dirs for part in path.parts):
                continue
            candidates.append(path)
    return sorted(set(candidates))


def run_migration(
    *,
    project_root: Path,
) -> MigrationResult:
    new_config_path, new_collections_dir = _ensure_new_layout(project_root)
    backup_dir = _backup_dir(project_root)
    backup_dir.mkdir(parents=True, exist_ok=True)

    migrated_config = False
    migrated_collections = 0
    skipped_collections = 0
    migrated_specs = 0
    skipped_specs = 0

    raw_config = {}
    if new_config_path.exists():
        raw_config = yaml.safe_load(new_config_path.read_text(encoding="utf-8")) or {}
    normalized = normalize_config_data(raw_config)
    if normalized != raw_config:
        if new_config_path.exists():
            _backup_path(new_config_path, backup_dir, project_root)
        else:
            new_config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(new_config_path, "w", encoding="utf-8") as handle:
            yaml.dump(normalized, handle, default_flow_style=False, sort_keys=False)
        migrated_config = True

    jobs_dir_value = normalized.get("jobs_dir", ".jobs/")
    jobs_dir = Path(str(jobs_dir_value))
    if not jobs_dir.is_absolute():
        jobs_dir = (project_root / jobs_dir).resolve()
    else:
        jobs_dir = jobs_dir.resolve()

    if new_collections_dir.exists():
        for path in sorted(new_collections_dir.glob("*.yaml")):
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            migrated, changed = _migrate_collection_data(raw)
            if not changed:
                skipped_collections += 1
                continue
            _backup_path(path, backup_dir, project_root)
            with open(path, "w", encoding="utf-8") as handle:
                yaml.dump(migrated, handle, default_flow_style=False, sort_keys=False)
            migrated_collections += 1

    for spec_path in _iter_spec_candidates(project_root):
        changed = _migrate_spec_file(spec_path, jobs_dir, backup_dir, project_root)
        if changed:
            migrated_specs += 1
        else:
            skipped_specs += 1

    return MigrationResult(
        backup_dir=backup_dir,
        migrated_config=migrated_config,
        migrated_collections=migrated_collections,
        skipped_collections=skipped_collections,
        migrated_specs=migrated_specs,
        skipped_specs=skipped_specs,
    )
