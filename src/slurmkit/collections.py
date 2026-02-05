"""
Job collections for organizing and tracking related SLURM jobs.

A collection is a group of related jobs that are typically generated and
submitted together. Collections track:
- The parameters used to generate jobs
- Job metadata (names, IDs, states, paths)
- Resubmission history
- Cross-cluster information (hostname)

Collections are stored as YAML files for human readability and git tracking.
"""

from __future__ import annotations

import json
import socket
import subprocess
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Union

import yaml

from slurmkit.config import Config, get_config
from slurmkit.slurm import get_sacct_info, get_job_status


# =============================================================================
# Constants
# =============================================================================

DEFAULT_COLLECTION_NAME = "default"

# Job states for filtering
JOB_STATE_PENDING = "pending"
JOB_STATE_RUNNING = "running"
JOB_STATE_COMPLETED = "completed"
JOB_STATE_FAILED = "failed"
JOB_STATE_UNKNOWN = "unknown"


# =============================================================================
# Git Metadata Helpers
# =============================================================================

def _run_git_command(args: List[str]) -> Optional[str]:
    """Run a git command and return stripped stdout, or None on failure."""
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
    """Get current git branch and commit ID for logging."""
    return {
        "git_branch": _run_git_command(["rev-parse", "--abbrev-ref", "HEAD"]),
        "git_commit_id": _run_git_command(["rev-parse", "HEAD"]),
    }


# =============================================================================
# Collection Class
# =============================================================================

class Collection:
    """
    A collection of related SLURM jobs.

    Collections track jobs that are generated and submitted together,
    including their parameters, states, and resubmission history.

    Attributes:
        name: Collection name (also used as filename).
        description: Human-readable description.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
        cluster: Hostname where collection was created.
        parameters: Generation parameters (grid/list specification).
        jobs: List of job entries.

    Example:
        >>> collection = Collection("my_experiment")
        >>> collection.add_job(
        ...     job_name="train_lr0.01",
        ...     script_path="jobs/exp/train_lr0.01.job",
        ...     parameters={"learning_rate": 0.01}
        ... )
        >>> collection.save()
    """

    def __init__(
        self,
        name: str,
        description: str = "",
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None,
        cluster: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        jobs: Optional[List[Dict[str, Any]]] = None,
    ):
        """
        Initialize a collection.

        Args:
            name: Collection name.
            description: Human-readable description.
            created_at: Creation timestamp (ISO format).
            updated_at: Last update timestamp (ISO format).
            cluster: Hostname where collection was created.
            parameters: Generation parameters specification.
            jobs: List of job entries.
        """
        self.name = name
        self.description = description
        self.cluster = cluster or socket.gethostname()

        now = datetime.now().isoformat(timespec="seconds")
        self.created_at = created_at or now
        self.updated_at = updated_at or now

        self.parameters = parameters or {}
        self._jobs: List[Dict[str, Any]] = jobs or []

    @property
    def jobs(self) -> List[Dict[str, Any]]:
        """List of job entries in this collection."""
        return self._jobs

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
        """
        Add a job to the collection.

        Args:
            job_name: Name of the job.
            script_path: Path to the job script.
            output_path: Path to the output file.
            job_id: SLURM job ID (if submitted).
            state: Current job state.
            parameters: Job-specific parameters.
            hostname: Hostname where job was submitted.
            submitted_at: Submission timestamp.
            started_at: Start timestamp.
            completed_at: Completion timestamp.

        Returns:
            The created job entry dictionary.
        """
        git_metadata = _get_git_metadata()
        job_entry = {
            "job_name": job_name,
            "job_id": job_id,
            "script_path": str(script_path) if script_path else None,
            "output_path": str(output_path) if output_path else None,
            "state": state,
            "hostname": hostname or socket.gethostname(),
            "parameters": parameters or {},
            "submitted_at": submitted_at,
            "started_at": started_at,
            "completed_at": completed_at,
            "resubmissions": [],
            "git_branch": git_metadata["git_branch"],
            "git_commit_id": git_metadata["git_commit_id"],
        }

        self._jobs.append(job_entry)
        self._touch()

        return job_entry

    def get_job(self, job_name: str) -> Optional[Dict[str, Any]]:
        """
        Get a job entry by name.

        Args:
            job_name: Name of the job to find.

        Returns:
            Job entry dictionary, or None if not found.
        """
        for job in self._jobs:
            if job["job_name"] == job_name:
                return job
        return None

    def get_job_by_id(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a job entry by SLURM job ID.

        Args:
            job_id: SLURM job ID to find.

        Returns:
            Job entry dictionary, or None if not found.
        """
        for job in self._jobs:
            if job.get("job_id") == job_id:
                return job
            # Also check resubmissions
            for resub in job.get("resubmissions", []):
                if resub.get("job_id") == job_id:
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
        """
        Update an existing job entry.

        Args:
            job_name: Name of the job to update.
            job_id: New SLURM job ID.
            state: New state.
            output_path: New output path.
            submitted_at: Submission timestamp.
            started_at: Start timestamp.
            completed_at: Completion timestamp.
            **kwargs: Additional fields to update.

        Returns:
            True if job was found and updated, False otherwise.
        """
        job = self.get_job(job_name)
        if job is None:
            return False

        if job_id is not None:
            job["job_id"] = job_id
        if state is not None:
            job["state"] = state
        if output_path is not None:
            job["output_path"] = str(output_path)
        if submitted_at is not None:
            job["submitted_at"] = submitted_at
        if started_at is not None:
            job["started_at"] = started_at
        if completed_at is not None:
            job["completed_at"] = completed_at

        for key, value in kwargs.items():
            job[key] = value

        self._touch()
        return True

    def add_resubmission(
        self,
        job_name: str,
        job_id: str,
        extra_params: Optional[Dict[str, Any]] = None,
        hostname: Optional[str] = None,
    ) -> bool:
        """
        Record a job resubmission.

        Args:
            job_name: Name of the original job.
            job_id: New SLURM job ID from resubmission.
            extra_params: Additional parameters used for resubmission.
            hostname: Hostname where resubmission occurred.

        Returns:
            True if job was found and resubmission recorded, False otherwise.
        """
        job = self.get_job(job_name)
        if job is None:
            return False

        git_metadata = _get_git_metadata()
        resubmission = {
            "job_id": job_id,
            "state": None,
            "hostname": hostname or socket.gethostname(),
            "submitted_at": datetime.now().isoformat(timespec="seconds"),
            "extra_params": extra_params or {},
            "git_branch": git_metadata["git_branch"],
            "git_commit_id": git_metadata["git_commit_id"],
        }

        if "resubmissions" not in job:
            job["resubmissions"] = []

        job["resubmissions"].append(resubmission)
        self._touch()

        return True

    def remove_job(self, job_name: str) -> bool:
        """
        Remove a job from the collection.

        Args:
            job_name: Name of the job to remove.

        Returns:
            True if job was found and removed, False otherwise.
        """
        for i, job in enumerate(self._jobs):
            if job["job_name"] == job_name:
                del self._jobs[i]
                self._touch()
                return True
        return False

    def filter_jobs(
        self,
        state: Optional[str] = None,
        hostname: Optional[str] = None,
        submitted: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """
        Filter jobs by criteria.

        Args:
            state: Filter by normalized state (pending, running, completed, failed).
            hostname: Filter by hostname.
            submitted: If True, only submitted jobs. If False, only unsubmitted.

        Returns:
            List of matching job entries.
        """
        result = []

        for job in self._jobs:
            # Check submitted filter
            if submitted is not None:
                is_submitted = job.get("job_id") is not None
                if submitted != is_submitted:
                    continue

            # Check hostname filter
            if hostname is not None and job.get("hostname") != hostname:
                continue

            # Check state filter
            if state is not None:
                job_state = self._normalize_state(job.get("state"))
                if job_state != state:
                    continue

            result.append(job)

        return result

    def _normalize_state(self, state: Optional[str]) -> str:
        """
        Normalize a SLURM state to a simple category.

        Args:
            state: Raw SLURM state string.

        Returns:
            Normalized state: pending, running, completed, failed, or unknown.
        """
        if state is None:
            return JOB_STATE_UNKNOWN

        state_upper = state.upper()

        if state_upper in ("PENDING", "REQUEUED", "SUSPENDED"):
            return JOB_STATE_PENDING
        elif state_upper in ("RUNNING", "COMPLETING"):
            return JOB_STATE_RUNNING
        elif state_upper == "COMPLETED":
            return JOB_STATE_COMPLETED
        elif state_upper in ("FAILED", "CANCELLED", "TIMEOUT", "NODE_FAIL",
                             "PREEMPTED", "OUT_OF_MEMORY"):
            return JOB_STATE_FAILED
        else:
            return JOB_STATE_UNKNOWN

    def get_summary(self) -> Dict[str, int]:
        """
        Get a summary of job states in the collection.

        Returns:
            Dictionary with counts for each state category.
        """
        summary = {
            "total": len(self._jobs),
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "unknown": 0,
            "not_submitted": 0,
        }

        for job in self._jobs:
            if job.get("job_id") is None:
                summary["not_submitted"] += 1
                continue

            state = self._normalize_state(job.get("state"))
            summary[state] += 1

        return summary

    def _get_analysis_rows(self, attempt_mode: str = "primary") -> List[Dict[str, Any]]:
        """Build canonical rows for status analysis."""
        rows = []

        for job in self._jobs:
            state = job.get("state")
            if attempt_mode == "latest":
                resubmissions = job.get("resubmissions", [])
                if resubmissions:
                    latest_state = resubmissions[-1].get("state")
                    if latest_state:
                        state = latest_state

            rows.append({
                "job_name": job.get("job_name"),
                "state": self._normalize_state(state),
                "parameters": job.get("parameters", {}) or {},
            })

        return rows

    def _format_param_value(self, value: Any) -> str:
        """Serialize a parameter value to a stable, display-safe string key."""
        if isinstance(value, (dict, list, tuple)):
            return json.dumps(value, sort_keys=True)
        return str(value)

    def analyze_status_by_params(
        self,
        attempt_mode: str = "primary",
        min_support: int = 3,
        selected_params: Optional[List[str]] = None,
        top_k: int = 10,
    ) -> Dict[str, Any]:
        """
        Analyze job state distributions by parameter value.

        Args:
            attempt_mode: Either "primary" or "latest".
            min_support: Minimum group size for high-confidence highlights.
            selected_params: Optional list of specific parameter keys to analyze.
            top_k: Max number of entries in risky/stable summaries.

        Returns:
            Analysis payload suitable for table rendering or JSON output.
        """
        if attempt_mode not in ("primary", "latest"):
            raise ValueError("attempt_mode must be 'primary' or 'latest'")
        if min_support < 1:
            raise ValueError("min_support must be >= 1")
        if top_k < 1:
            raise ValueError("top_k must be >= 1")

        rows = self._get_analysis_rows(attempt_mode=attempt_mode)

        summary_counts = {
            JOB_STATE_COMPLETED: 0,
            JOB_STATE_FAILED: 0,
            JOB_STATE_RUNNING: 0,
            JOB_STATE_PENDING: 0,
            JOB_STATE_UNKNOWN: 0,
        }
        for row in rows:
            state = row["state"]
            summary_counts[state] = summary_counts.get(state, 0) + 1

        total_jobs = len(rows)
        summary_rates = {}
        for state, count in summary_counts.items():
            summary_rates[state] = (count / total_jobs) if total_jobs > 0 else 0.0

        available_params = sorted({
            key
            for row in rows
            for key in row.get("parameters", {}).keys()
        })

        if selected_params:
            params_to_analyze = list(dict.fromkeys(selected_params))
            skipped_params = [p for p in params_to_analyze if p not in available_params]
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
                n = data["n"]
                failure_rate = data["counts"][JOB_STATE_FAILED] / n
                completion_rate = data["counts"][JOB_STATE_COMPLETED] / n

                entry = {
                    "value": value_key,
                    "n": n,
                    "counts": data["counts"],
                    "rates": {
                        "failure_rate": failure_rate,
                        "completion_rate": completion_rate,
                    },
                    "low_sample": n < min_support,
                }
                values.append(entry)
                all_value_entries.append({
                    "param": param,
                    **entry,
                })

            values.sort(
                key=lambda x: (
                    -x["rates"]["failure_rate"],
                    -x["n"],
                    x["value"],
                )
            )
            parameter_results.append({
                "param": param,
                "values": values,
            })

        eligible = [e for e in all_value_entries if e["n"] >= min_support]
        top_risky = sorted(
            eligible,
            key=lambda x: (
                -x["rates"]["failure_rate"],
                -x["n"],
                x["param"],
                x["value"],
            ),
        )[:top_k]
        top_stable = sorted(
            eligible,
            key=lambda x: (
                -x["rates"]["completion_rate"],
                -x["n"],
                x["param"],
                x["value"],
            ),
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
                "attempt_mode": attempt_mode,
                "selected_params": selected_params or [],
                "skipped_params": skipped_params,
            },
        }

    def refresh_states(self, update_resubmissions: bool = True) -> int:
        """
        Refresh job states from SLURM.

        Queries sacct for current state of all submitted jobs and updates
        the collection.

        Args:
            update_resubmissions: Also update states of resubmitted jobs.

        Returns:
            Number of jobs updated.
        """
        # Collect all job IDs to query
        job_ids = []
        for job in self._jobs:
            if job.get("job_id"):
                job_ids.append(job["job_id"])
            if update_resubmissions:
                for resub in job.get("resubmissions", []):
                    if resub.get("job_id"):
                        job_ids.append(resub["job_id"])

        if not job_ids:
            return 0

        # Query sacct
        info_map = get_sacct_info(
            job_ids,
            fields=["JobID", "State", "Start", "End"],
        )

        # Update jobs
        updated = 0
        for job in self._jobs:
            job_id = job.get("job_id")
            if job_id and job_id in info_map:
                info = info_map[job_id]
                old_state = job.get("state")
                new_state = info.get("State")

                if old_state != new_state:
                    job["state"] = new_state
                    updated += 1

                # Update timestamps
                if info.get("Start") and info["Start"] != "Unknown":
                    job["started_at"] = info["Start"]
                if info.get("End") and info["End"] != "Unknown":
                    job["completed_at"] = info["End"]

            # Update resubmissions
            if update_resubmissions:
                for resub in job.get("resubmissions", []):
                    resub_id = resub.get("job_id")
                    if resub_id and resub_id in info_map:
                        info = info_map[resub_id]
                        old_state = resub.get("state")
                        new_state = info.get("State")

                        if old_state != new_state:
                            resub["state"] = new_state
                            updated += 1

        if updated > 0:
            self._touch()

        return updated

    def _touch(self) -> None:
        """Update the updated_at timestamp."""
        self.updated_at = datetime.now().isoformat(timespec="seconds")

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert collection to a dictionary.

        Returns:
            Dictionary representation of the collection.
        """
        return {
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "cluster": self.cluster,
            "parameters": self.parameters,
            "jobs": self._jobs,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Collection":
        """
        Create a collection from a dictionary.

        Args:
            data: Dictionary with collection data.

        Returns:
            New Collection instance.
        """
        return cls(
            name=data.get("name", "unnamed"),
            description=data.get("description", ""),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            cluster=data.get("cluster"),
            parameters=data.get("parameters"),
            jobs=data.get("jobs"),
        )

    def __len__(self) -> int:
        return len(self._jobs)

    def __iter__(self) -> Iterator[Dict[str, Any]]:
        return iter(self._jobs)

    def __repr__(self) -> str:
        return f"Collection(name={self.name!r}, jobs={len(self._jobs)})"


# =============================================================================
# Collection Manager
# =============================================================================

class CollectionManager:
    """
    Manager for loading, saving, and organizing collections.

    The manager handles persistence of collections to YAML files in a
    configurable directory.

    Attributes:
        collections_dir: Directory where collection files are stored.

    Example:
        >>> manager = CollectionManager()
        >>> collection = manager.get_or_create("my_experiment")
        >>> collection.add_job(...)
        >>> manager.save(collection)
    """

    def __init__(
        self,
        collections_dir: Optional[Union[str, Path]] = None,
        config: Optional[Config] = None,
    ):
        """
        Initialize the collection manager.

        Args:
            collections_dir: Directory for collection files. If None, uses config.
            config: Configuration object. If None, uses global config.
        """
        if config is None:
            config = get_config()

        if collections_dir is not None:
            self.collections_dir = Path(collections_dir)
        else:
            self.collections_dir = config.get_path("collections_dir")
            if self.collections_dir is None:
                self.collections_dir = Path(".job-collections")

    def _ensure_dir(self) -> None:
        """Ensure the collections directory exists."""
        self.collections_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, name: str) -> Path:
        """Get the file path for a collection."""
        return self.collections_dir / f"{name}.yaml"

    def exists(self, name: str) -> bool:
        """
        Check if a collection exists.

        Args:
            name: Collection name.

        Returns:
            True if collection file exists.
        """
        return self._get_path(name).exists()

    def load(self, name: str) -> Collection:
        """
        Load a collection from disk.

        Args:
            name: Collection name.

        Returns:
            Loaded Collection object.

        Raises:
            FileNotFoundError: If collection file doesn't exist.
        """
        path = self._get_path(name)

        if not path.exists():
            raise FileNotFoundError(f"Collection not found: {name}")

        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}

        return Collection.from_dict(data)

    def save(self, collection: Collection) -> Path:
        """
        Save a collection to disk.

        Args:
            collection: Collection to save.

        Returns:
            Path where collection was saved.
        """
        self._ensure_dir()
        path = self._get_path(collection.name)

        with open(path, "w") as f:
            yaml.dump(
                collection.to_dict(),
                f,
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
        """
        Create a new collection.

        Args:
            name: Collection name.
            description: Human-readable description.
            parameters: Generation parameters specification.
            overwrite: If True, overwrite existing collection.

        Returns:
            New Collection object.

        Raises:
            FileExistsError: If collection exists and overwrite=False.
        """
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
        """
        Get an existing collection or create a new one.

        Args:
            name: Collection name.
            description: Description (used only if creating).
            parameters: Parameters (used only if creating).

        Returns:
            Existing or newly created Collection.
        """
        if self.exists(name):
            return self.load(name)
        else:
            return self.create(name, description, parameters)

    def delete(self, name: str) -> bool:
        """
        Delete a collection.

        Args:
            name: Collection name.

        Returns:
            True if collection was deleted, False if it didn't exist.
        """
        path = self._get_path(name)

        if path.exists():
            path.unlink()
            return True
        return False

    def list_collections(self) -> List[str]:
        """
        List all collection names.

        Returns:
            List of collection names (without .yaml extension).
        """
        if not self.collections_dir.exists():
            return []

        names = []
        for path in self.collections_dir.glob("*.yaml"):
            names.append(path.stem)

        return sorted(names)

    def list_collections_with_summary(self) -> List[Dict[str, Any]]:
        """
        List all collections with summary information.

        Returns:
            List of dicts with name, description, job counts, etc.
        """
        summaries = []

        for name in self.list_collections():
            try:
                collection = self.load(name)
                summary = collection.get_summary()
                summaries.append({
                    "name": name,
                    "description": collection.description,
                    "cluster": collection.cluster,
                    "created_at": collection.created_at,
                    "updated_at": collection.updated_at,
                    **summary,
                })
            except Exception:
                # Skip collections that fail to load
                continue

        return summaries

    def __repr__(self) -> str:
        return f"CollectionManager(collections_dir={self.collections_dir})"


# =============================================================================
# Convenience Functions
# =============================================================================

def get_collection_manager(
    collections_dir: Optional[Union[str, Path]] = None,
    config: Optional[Config] = None,
) -> CollectionManager:
    """
    Get a collection manager instance.

    Args:
        collections_dir: Override collections directory.
        config: Configuration object.

    Returns:
        CollectionManager instance.
    """
    return CollectionManager(collections_dir=collections_dir, config=config)


def load_collection(
    name: str,
    collections_dir: Optional[Union[str, Path]] = None,
) -> Collection:
    """
    Load a collection by name.

    Args:
        name: Collection name.
        collections_dir: Override collections directory.

    Returns:
        Loaded Collection object.
    """
    manager = get_collection_manager(collections_dir=collections_dir)
    return manager.load(name)


def save_collection(
    collection: Collection,
    collections_dir: Optional[Union[str, Path]] = None,
) -> Path:
    """
    Save a collection.

    Args:
        collection: Collection to save.
        collections_dir: Override collections directory.

    Returns:
        Path where collection was saved.
    """
    manager = get_collection_manager(collections_dir=collections_dir)
    return manager.save(collection)
