"""
Attempts-based job collections for organizing and tracking SLURM jobs.

Collections are stored as YAML files with a v2 schema. Each tracked job keeps
stable metadata plus an ordered list of attempts, where the first attempt is
the primary/generated submission and later attempts are regenerated or reused
resubmissions.
"""

from __future__ import annotations

import json
import socket
import subprocess
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Union

import yaml

from slurmkit.config import Config, get_config
from slurmkit.slurm import get_sacct_info


COLLECTION_SCHEMA_VERSION = 2

JOB_STATE_PENDING = "pending"
JOB_STATE_RUNNING = "running"
JOB_STATE_COMPLETED = "completed"
JOB_STATE_FAILED = "failed"
JOB_STATE_UNKNOWN = "unknown"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _run_git_command(args: List[str]) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value if value else None


@lru_cache(maxsize=1)
def _get_git_metadata() -> Dict[str, Optional[str]]:
    return {
        "git_branch": _run_git_command(["rev-parse", "--abbrev-ref", "HEAD"]),
        "git_commit_id": _run_git_command(["rev-parse", "HEAD"]),
    }


def _string_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


class Collection:
    """A collection of related SLURM jobs stored in an attempts-based schema."""

    def __init__(
        self,
        name: str,
        description: str = "",
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None,
        cluster: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        jobs: Optional[List[Dict[str, Any]]] = None,
        generation: Optional[Dict[str, Any]] = None,
        notifications: Optional[Dict[str, Any]] = None,
        version: int = COLLECTION_SCHEMA_VERSION,
    ):
        self.version = version
        self.name = name
        self.description = description
        self.cluster = cluster or socket.gethostname()
        now = _now_iso()
        self.created_at = created_at or now
        self.updated_at = updated_at or now
        self.parameters = dict(parameters or {})
        self.generation = dict(generation or {})
        self.notifications = dict(notifications or {})
        self._jobs: List[Dict[str, Any]] = [
            self._normalize_job(job)
            for job in (jobs or [])
        ]

    @property
    def jobs(self) -> List[Dict[str, Any]]:
        return self._jobs

    def _touch(self) -> None:
        self.updated_at = _now_iso()

    def _normalize_state(self, state: Optional[str]) -> str:
        if state is None:
            return JOB_STATE_UNKNOWN
        state_upper = str(state).upper()
        if state_upper in ("PENDING", "REQUEUED", "SUSPENDED"):
            return JOB_STATE_PENDING
        if state_upper in ("RUNNING", "COMPLETING"):
            return JOB_STATE_RUNNING
        if state_upper == "COMPLETED":
            return JOB_STATE_COMPLETED
        if state_upper in (
            "FAILED",
            "CANCELLED",
            "TIMEOUT",
            "NODE_FAIL",
            "PREEMPTED",
            "OUT_OF_MEMORY",
        ):
            return JOB_STATE_FAILED
        return JOB_STATE_UNKNOWN

    def _new_attempt(
        self,
        *,
        kind: str,
        job_id: Optional[str] = None,
        state: Optional[str] = None,
        hostname: Optional[str] = None,
        submitted_at: Optional[str] = None,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
        script_path: Optional[Union[str, Path]] = None,
        output_path: Optional[Union[str, Path]] = None,
        submission_group: Optional[str] = None,
        attempt_job_name: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        extra_params: Optional[Dict[str, Any]] = None,
        regenerated: Optional[bool] = None,
    ) -> Dict[str, Any]:
        git_metadata = _get_git_metadata()
        return {
            "kind": kind,
            "job_id": _string_or_none(job_id),
            "state": _string_or_none(state),
            "hostname": _string_or_none(hostname) or socket.gethostname(),
            "submitted_at": _string_or_none(submitted_at),
            "started_at": _string_or_none(started_at),
            "completed_at": _string_or_none(completed_at),
            "script_path": str(script_path) if script_path else None,
            "output_path": str(output_path) if output_path else None,
            "submission_group": _string_or_none(submission_group),
            "job_name": _string_or_none(attempt_job_name),
            "parameters": dict(parameters or {}),
            "extra_params": dict(extra_params or {}),
            "regenerated": regenerated,
            "git_branch": git_metadata["git_branch"],
            "git_commit_id": git_metadata["git_commit_id"],
        }

    def _normalize_attempt(self, raw_attempt: Dict[str, Any], *, default_kind: str) -> Dict[str, Any]:
        attempt = self._new_attempt(
            kind=str(raw_attempt.get("kind") or default_kind),
            job_id=raw_attempt.get("job_id"),
            state=raw_attempt.get("state"),
            hostname=raw_attempt.get("hostname"),
            submitted_at=raw_attempt.get("submitted_at"),
            started_at=raw_attempt.get("started_at"),
            completed_at=raw_attempt.get("completed_at"),
            script_path=raw_attempt.get("script_path"),
            output_path=raw_attempt.get("output_path"),
            submission_group=raw_attempt.get("submission_group"),
            attempt_job_name=raw_attempt.get("job_name"),
            parameters=raw_attempt.get("parameters"),
            extra_params=raw_attempt.get("extra_params"),
            regenerated=raw_attempt.get("regenerated"),
        )
        if raw_attempt.get("git_branch") is not None:
            attempt["git_branch"] = raw_attempt.get("git_branch")
        if raw_attempt.get("git_commit_id") is not None:
            attempt["git_commit_id"] = raw_attempt.get("git_commit_id")
        return attempt

    def _normalize_job(self, raw_job: Dict[str, Any]) -> Dict[str, Any]:
        attempts = raw_job.get("attempts") or []
        if not isinstance(attempts, list) or not attempts:
            raise ValueError("Collection jobs must define a non-empty 'attempts' list.")

        normalized_attempts = []
        for index, raw_attempt in enumerate(attempts):
            if not isinstance(raw_attempt, dict):
                raise ValueError("Collection attempt entries must be mappings.")
            normalized_attempts.append(
                self._normalize_attempt(
                    raw_attempt,
                    default_kind="primary" if index == 0 else "resubmission",
                )
            )

        return {
            "job_name": str(raw_job.get("job_name") or normalized_attempts[0].get("job_name") or "unnamed"),
            "parameters": dict(raw_job.get("parameters") or normalized_attempts[0].get("parameters") or {}),
            "attempts": normalized_attempts,
        }

    def primary_attempt(self, job: Dict[str, Any]) -> Dict[str, Any]:
        return job["attempts"][0]

    def latest_attempt(self, job: Dict[str, Any]) -> Dict[str, Any]:
        return job["attempts"][-1]

    def add_job(
        self,
        job_name: str,
        script_path: Optional[Union[str, Path]] = None,
        output_path: Optional[Union[str, Path]] = None,
        job_id: Optional[str] = None,
        state: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        hostname: Optional[str] = None,
        submitted_at: Optional[str] = None,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        job = {
            "job_name": job_name,
            "parameters": dict(parameters or {}),
            "attempts": [
                self._new_attempt(
                    kind="primary",
                    job_id=job_id,
                    state=state,
                    hostname=hostname,
                    submitted_at=submitted_at,
                    started_at=started_at,
                    completed_at=completed_at,
                    script_path=script_path,
                    output_path=output_path,
                    attempt_job_name=job_name,
                    parameters=parameters,
                    regenerated=False,
                )
            ],
        }
        self._jobs.append(job)
        self._touch()
        return job

    def get_job(self, job_name: str) -> Optional[Dict[str, Any]]:
        for job in self._jobs:
            if job["job_name"] == job_name:
                return job
        return None

    def get_job_by_id(self, job_id: str) -> Optional[Dict[str, Any]]:
        for job in self._jobs:
            for attempt in job.get("attempts", []):
                if attempt.get("job_id") == job_id:
                    return job
        return None

    def update_job(
        self,
        job_name: str,
        job_id: Optional[str] = None,
        state: Optional[str] = None,
        output_path: Optional[Union[str, Path]] = None,
        submitted_at: Optional[str] = None,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
        **kwargs: Any,
    ) -> bool:
        job = self.get_job(job_name)
        if job is None:
            return False
        attempt = self.primary_attempt(job)
        if job_id is not None:
            attempt["job_id"] = _string_or_none(job_id)
        if state is not None:
            attempt["state"] = _string_or_none(state)
        if output_path is not None:
            attempt["output_path"] = str(output_path)
        if submitted_at is not None:
            attempt["submitted_at"] = _string_or_none(submitted_at)
        if started_at is not None:
            attempt["started_at"] = _string_or_none(started_at)
        if completed_at is not None:
            attempt["completed_at"] = _string_or_none(completed_at)
        for key, value in kwargs.items():
            attempt[key] = value
        self._touch()
        return True

    def add_resubmission(
        self,
        job_name: str,
        job_id: str,
        extra_params: Optional[Dict[str, Any]] = None,
        submission_group: Optional[str] = None,
        hostname: Optional[str] = None,
        attempt_job_name: Optional[str] = None,
        attempt_script_path: Optional[Union[str, Path]] = None,
        attempt_parameters: Optional[Dict[str, Any]] = None,
        regenerated: Optional[bool] = None,
    ) -> bool:
        job = self.get_job(job_name)
        if job is None:
            return False
        attempt = self._new_attempt(
            kind="resubmission",
            job_id=job_id,
            hostname=hostname,
            submitted_at=_now_iso(),
            submission_group=submission_group,
            attempt_job_name=attempt_job_name or job_name,
            script_path=attempt_script_path,
            parameters=attempt_parameters,
            extra_params=extra_params,
            regenerated=regenerated,
        )
        job["attempts"].append(attempt)
        self._touch()
        return True

    def remove_job(self, job_name: str) -> bool:
        for index, job in enumerate(self._jobs):
            if job["job_name"] == job_name:
                del self._jobs[index]
                self._touch()
                return True
        return False

    def filter_jobs(
        self,
        state: Optional[str] = None,
        hostname: Optional[str] = None,
        submitted: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        result = []
        for job in self._jobs:
            primary = self.primary_attempt(job)
            if submitted is not None:
                is_submitted = primary.get("job_id") is not None
                if submitted != is_submitted:
                    continue
            if hostname is not None and primary.get("hostname") != hostname:
                continue
            if state is not None and self._normalize_state(primary.get("state")) != state:
                continue
            result.append(job)
        return result

    def _normalize_attempt_mode(self, attempt_mode: str) -> str:
        normalized = str(attempt_mode).strip().lower()
        if normalized not in {"primary", "latest"}:
            raise ValueError("attempt_mode must be 'primary' or 'latest'")
        return normalized

    def _normalize_submission_group(self, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text if text else None

    def _effective_attempt_for_job(
        self,
        job: Dict[str, Any],
        *,
        attempt_mode: str = "primary",
        submission_group: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        attempt_mode = self._normalize_attempt_mode(attempt_mode)
        group = self._normalize_submission_group(submission_group)
        attempts = job["attempts"]

        if group is not None:
            matched: List[tuple[int, Dict[str, Any]]] = []
            for index, attempt in enumerate(attempts[1:], start=1):
                if self._normalize_submission_group(attempt.get("submission_group")) == group:
                    matched.append((index, attempt))
            if not matched:
                return None
            attempt_index, attempt = matched[-1]
            return {
                "attempt": attempt,
                "attempt_index": attempt_index,
                "attempt_label": f"resubmission #{attempt_index}",
                "is_primary": False,
                "submission_group": self._normalize_submission_group(attempt.get("submission_group")),
            }

        if attempt_mode == "latest":
            attempt_index = len(attempts) - 1
            attempt = attempts[-1]
            return {
                "attempt": attempt,
                "attempt_index": attempt_index,
                "attempt_label": "primary" if attempt_index == 0 else f"resubmission #{attempt_index}",
                "is_primary": attempt_index == 0,
                "submission_group": self._normalize_submission_group(attempt.get("submission_group")),
            }

        attempt = attempts[0]
        return {
            "attempt": attempt,
            "attempt_index": 0,
            "attempt_label": "primary",
            "is_primary": True,
            "submission_group": None,
        }

    def get_effective_jobs(
        self,
        attempt_mode: str = "primary",
        submission_group: Optional[str] = None,
        state: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        state_filter = None if state is None else str(state).strip().lower()
        if state_filter is not None and state_filter not in {
            JOB_STATE_PENDING,
            JOB_STATE_RUNNING,
            JOB_STATE_COMPLETED,
            JOB_STATE_FAILED,
            JOB_STATE_UNKNOWN,
        }:
            raise ValueError("state must be one of pending/running/completed/failed/unknown")

        rows: List[Dict[str, Any]] = []
        for job in self._jobs:
            resolved = self._effective_attempt_for_job(
                job,
                attempt_mode=attempt_mode,
                submission_group=submission_group,
            )
            if resolved is None:
                continue

            primary = self.primary_attempt(job)
            effective = resolved["attempt"]
            effective_state = self._normalize_state(effective.get("state"))
            if state_filter is not None and effective_state != state_filter:
                continue

            history = [
                f"{str(attempt.get('job_id') or 'N/A')}({str(attempt.get('state') or 'N/A')})"
                for attempt in job["attempts"]
            ]

            rows.append(
                {
                    "job_name": job["job_name"],
                    "parameters": dict(job.get("parameters", {}) or {}),
                    "attempts_count": len(job["attempts"]),
                    "resubmissions_count": max(len(job["attempts"]) - 1, 0),
                    "primary_job_id": primary.get("job_id"),
                    "primary_state_raw": primary.get("state"),
                    "primary_state": self._normalize_state(primary.get("state")),
                    "primary_hostname": primary.get("hostname"),
                    "effective_job_id": effective.get("job_id"),
                    "effective_state_raw": effective.get("state"),
                    "effective_state": effective_state,
                    "effective_hostname": effective.get("hostname"),
                    "effective_submitted_at": effective.get("submitted_at"),
                    "effective_is_primary": resolved["is_primary"],
                    "effective_attempt_index": resolved["attempt_index"],
                    "effective_attempt_label": resolved["attempt_label"],
                    "effective_submission_group": resolved["submission_group"],
                    "attempt_history": history,
                    "job": job,
                }
            )
        return rows

    def get_effective_summary(
        self,
        attempt_mode: str = "primary",
        submission_group: Optional[str] = None,
    ) -> Dict[str, int]:
        rows = self.get_effective_jobs(
            attempt_mode=attempt_mode,
            submission_group=submission_group,
        )
        summary = {
            "total": len(rows),
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "unknown": 0,
            "not_submitted": 0,
        }
        for row in rows:
            if row.get("effective_job_id") is None:
                summary["not_submitted"] += 1
                continue
            state = row.get("effective_state", JOB_STATE_UNKNOWN)
            summary[state] = summary.get(state, 0) + 1
        return summary

    def get_submission_groups_summary(self) -> List[Dict[str, Any]]:
        grouped: Dict[str, Dict[str, Any]] = {}
        for job in self._jobs:
            for attempt in job["attempts"][1:]:
                group = self._normalize_submission_group(attempt.get("submission_group"))
                if group is None:
                    continue
                bucket = grouped.setdefault(
                    group,
                    {
                        "submission_group": group,
                        "slurm_job_count": 0,
                        "parent_job_names": set(),
                        "first_submitted_at": None,
                        "last_submitted_at": None,
                    },
                )
                bucket["slurm_job_count"] += 1
                casted_names: Set[str] = bucket["parent_job_names"]
                casted_names.add(job["job_name"])
                submitted_at = attempt.get("submitted_at")
                if submitted_at:
                    if bucket["first_submitted_at"] is None or submitted_at < bucket["first_submitted_at"]:
                        bucket["first_submitted_at"] = submitted_at
                    if bucket["last_submitted_at"] is None or submitted_at > bucket["last_submitted_at"]:
                        bucket["last_submitted_at"] = submitted_at

        rows = []
        for values in grouped.values():
            parent_job_names = values.pop("parent_job_names")
            values["parent_job_count"] = len(parent_job_names)
            rows.append(values)
        rows.sort(key=lambda item: str(item["submission_group"]))
        return rows

    def get_summary(self) -> Dict[str, int]:
        return self.get_effective_summary(attempt_mode="primary")

    def _get_analysis_rows(
        self,
        attempt_mode: str = "primary",
        submission_group: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = self.get_effective_jobs(
            attempt_mode=attempt_mode,
            submission_group=submission_group,
        )
        return [
            {
                "job_name": row["job_name"],
                "state": row.get("effective_state", JOB_STATE_UNKNOWN),
                "parameters": row.get("parameters", {}) or {},
            }
            for row in rows
        ]

    def _format_param_value(self, value: Any) -> str:
        if isinstance(value, (dict, list, tuple)):
            return json.dumps(value, sort_keys=True)
        return str(value)

    def analyze_status_by_params(
        self,
        attempt_mode: str = "primary",
        submission_group: Optional[str] = None,
        min_support: int = 3,
        selected_params: Optional[List[str]] = None,
        top_k: int = 10,
    ) -> Dict[str, Any]:
        if min_support < 1:
            raise ValueError("min_support must be >= 1")
        if top_k < 1:
            raise ValueError("top_k must be >= 1")

        effective_mode = "latest" if self._normalize_submission_group(submission_group) else self._normalize_attempt_mode(attempt_mode)
        rows = self._get_analysis_rows(
            attempt_mode=effective_mode,
            submission_group=submission_group,
        )

        summary_counts = {
            JOB_STATE_COMPLETED: 0,
            JOB_STATE_FAILED: 0,
            JOB_STATE_RUNNING: 0,
            JOB_STATE_PENDING: 0,
            JOB_STATE_UNKNOWN: 0,
        }
        for row in rows:
            summary_counts[row["state"]] = summary_counts.get(row["state"], 0) + 1

        total_jobs = len(rows)
        summary_rates = {
            state: (count / total_jobs) if total_jobs > 0 else 0.0
            for state, count in summary_counts.items()
        }

        available_params = sorted({
            key
            for row in rows
            for key in row.get("parameters", {}).keys()
        })
        if selected_params:
            params_to_analyze = list(dict.fromkeys(selected_params))
            skipped_params = [name for name in params_to_analyze if name not in available_params]
        else:
            params_to_analyze = available_params
            skipped_params = []

        parameter_results = []
        all_value_entries = []
        for param in params_to_analyze:
            grouped: Dict[str, Dict[str, Any]] = {}
            for row in rows:
                params = row.get("parameters", {})
                if param not in params:
                    continue
                value_key = self._format_param_value(params[param])
                if value_key not in grouped:
                    grouped[value_key] = {
                        "value": value_key,
                        "n": 0,
                        "counts": {
                            JOB_STATE_COMPLETED: 0,
                            JOB_STATE_FAILED: 0,
                            JOB_STATE_RUNNING: 0,
                            JOB_STATE_PENDING: 0,
                            JOB_STATE_UNKNOWN: 0,
                        },
                    }
                grouped[value_key]["n"] += 1
                grouped[value_key]["counts"][row["state"]] += 1

            if not grouped:
                continue

            values = []
            for value_key, data in grouped.items():
                count = data["n"]
                failure_rate = data["counts"][JOB_STATE_FAILED] / count
                completion_rate = data["counts"][JOB_STATE_COMPLETED] / count
                entry = {
                    "value": value_key,
                    "n": count,
                    "counts": data["counts"],
                    "rates": {
                        "failure_rate": failure_rate,
                        "completion_rate": completion_rate,
                    },
                    "low_sample": count < min_support,
                }
                values.append(entry)
                all_value_entries.append({"param": param, **entry})

            values.sort(key=lambda item: (-item["rates"]["failure_rate"], -item["n"], item["value"]))
            parameter_results.append({"param": param, "values": values})

        eligible = [entry for entry in all_value_entries if entry["n"] >= min_support]
        top_risky = sorted(
            eligible,
            key=lambda item: (-item["rates"]["failure_rate"], -item["n"], item["param"], item["value"]),
        )[:top_k]
        top_stable = sorted(
            eligible,
            key=lambda item: (-item["rates"]["completion_rate"], -item["n"], item["param"], item["value"]),
        )[:top_k]

        return {
            "summary": {
                "total_jobs": total_jobs,
                "counts": summary_counts,
                "rates": summary_rates,
            },
            "parameters": parameter_results,
            "top_risky_values": top_risky,
            "top_stable_values": top_stable,
            "metadata": {
                "min_support": min_support,
                "attempt_mode": effective_mode,
                "submission_group": self._normalize_submission_group(submission_group),
                "selected_params": selected_params or [],
                "skipped_params": skipped_params,
            },
        }

    def refresh_states(self) -> int:
        job_ids = [
            str(attempt["job_id"])
            for job in self._jobs
            for attempt in job.get("attempts", [])
            if attempt.get("job_id")
        ]
        if not job_ids:
            return 0

        info_map = get_sacct_info(job_ids, fields=["JobID", "State", "Start", "End"])
        updated = 0
        for job in self._jobs:
            for attempt in job["attempts"]:
                job_id = attempt.get("job_id")
                if not job_id or job_id not in info_map:
                    continue
                info = info_map[job_id]
                new_state = info.get("State")
                if attempt.get("state") != new_state:
                    attempt["state"] = new_state
                    updated += 1
                if info.get("Start") and info["Start"] != "Unknown":
                    attempt["started_at"] = info["Start"]
                if info.get("End") and info["End"] != "Unknown":
                    attempt["completed_at"] = info["End"]

        if updated > 0:
            self._touch()
        return updated

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": COLLECTION_SCHEMA_VERSION,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "cluster": self.cluster,
            "parameters": self.parameters,
            "generation": self.generation,
            "notifications": self.notifications,
            "jobs": self._jobs,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Collection":
        version = int(data.get("version", 0) or 0)
        if version != COLLECTION_SCHEMA_VERSION:
            raise ValueError(
                f"Collection schema version {version or 'unknown'} is unsupported. "
                "Run `slurmkit migrate` to upgrade local collections."
            )
        return cls(
            name=str(data.get("name", "unnamed")),
            description=str(data.get("description", "")),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            cluster=data.get("cluster"),
            parameters=data.get("parameters"),
            jobs=data.get("jobs"),
            generation=data.get("generation"),
            notifications=data.get("notifications"),
            version=version,
        )

    def __len__(self) -> int:
        return len(self._jobs)

    def __iter__(self) -> Iterator[Dict[str, Any]]:
        return iter(self._jobs)

    def __repr__(self) -> str:
        return f"Collection(name={self.name!r}, jobs={len(self._jobs)})"


@dataclass
class JobIdMatch:
    """Match payload for a tracked SLURM job ID lookup."""

    collection_name: str
    collection: Collection
    job: Dict[str, Any]


@dataclass
class JobIdResolution:
    """Resolution output for a tracked SLURM job ID lookup."""

    job_id: str
    matches: List[JobIdMatch]
    warnings: List[str]


class CollectionManager:
    """Load, save, and organize v2 collections."""

    def __init__(
        self,
        collections_dir: Optional[Union[str, Path]] = None,
        config: Optional[Config] = None,
    ):
        if config is None:
            config = get_config()
        if collections_dir is not None:
            self.collections_dir = Path(collections_dir)
        else:
            self.collections_dir = config.collections_dir

    def _ensure_dir(self) -> None:
        self.collections_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, name: str) -> Path:
        return self.collections_dir / f"{name}.yaml"

    def exists(self, name: str) -> bool:
        return self._get_path(name).exists()

    def load(self, name: str) -> Collection:
        path = self._get_path(name)
        if not path.exists():
            raise FileNotFoundError(f"Collection not found: {name}")
        with open(path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        return Collection.from_dict(data)

    def save(self, collection: Collection) -> Path:
        self._ensure_dir()
        path = self._get_path(collection.name)
        with open(path, "w", encoding="utf-8") as handle:
            yaml.dump(
                collection.to_dict(),
                handle,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )
        return path

    def create(
        self,
        name: str,
        description: str = "",
        parameters: Optional[Dict[str, Any]] = None,
        overwrite: bool = False,
    ) -> Collection:
        if self.exists(name) and not overwrite:
            raise FileExistsError(
                f"Collection already exists: {name}. Use overwrite=True to replace."
            )
        collection = Collection(
            name=name,
            description=description,
            parameters=parameters,
        )
        self.save(collection)
        return collection

    def get_or_create(
        self,
        name: str,
        description: str = "",
        parameters: Optional[Dict[str, Any]] = None,
    ) -> Collection:
        if self.exists(name):
            return self.load(name)
        return self.create(name, description, parameters)

    def delete(self, name: str) -> bool:
        path = self._get_path(name)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_collections(self) -> List[str]:
        if not self.collections_dir.exists():
            return []
        return sorted(path.stem for path in self.collections_dir.glob("*.yaml"))

    def resolve_job_id(
        self,
        job_id: str,
        *,
        collection_name: Optional[str] = None,
    ) -> JobIdResolution:
        """Resolve one tracked SLURM job ID to matching collection/job records."""
        normalized_job_id = str(job_id).strip()
        warnings: List[str] = []
        matches: List[JobIdMatch] = []

        if not normalized_job_id:
            return JobIdResolution(job_id=normalized_job_id, matches=matches, warnings=warnings)

        if collection_name is not None:
            names = [collection_name]
        else:
            names = self.list_collections()

        for name in names:
            if collection_name is not None and not self.exists(name):
                warnings.append(f"Collection '{name}' was not found.")
                continue
            try:
                collection = self.load(name)
            except Exception as exc:
                warnings.append(f"Failed to load collection '{name}': {exc}")
                continue
            job = collection.get_job_by_id(normalized_job_id)
            if job is None:
                continue
            matches.append(
                JobIdMatch(
                    collection_name=name,
                    collection=collection,
                    job=job,
                )
            )

        return JobIdResolution(job_id=normalized_job_id, matches=matches, warnings=warnings)

    def list_collections_with_summary(self, attempt_mode: str = "primary") -> List[Dict[str, Any]]:
        rows = []
        for name in self.list_collections():
            try:
                collection = self.load(name)
            except Exception:
                continue
            rows.append(
                {
                    "name": name,
                    "description": collection.description,
                    "cluster": collection.cluster,
                    "created_at": collection.created_at,
                    "updated_at": collection.updated_at,
                    **collection.get_effective_summary(attempt_mode=attempt_mode),
                }
            )
        return rows

    def __repr__(self) -> str:
        return f"CollectionManager(collections_dir={self.collections_dir})"


def get_collection_manager(
    collections_dir: Optional[Union[str, Path]] = None,
    config: Optional[Config] = None,
) -> CollectionManager:
    return CollectionManager(collections_dir=collections_dir, config=config)


def load_collection(
    name: str,
    collections_dir: Optional[Union[str, Path]] = None,
) -> Collection:
    return get_collection_manager(collections_dir=collections_dir).load(name)


def save_collection(
    collection: Collection,
    collections_dir: Optional[Union[str, Path]] = None,
) -> Path:
    return get_collection_manager(collections_dir=collections_dir).save(collection)
