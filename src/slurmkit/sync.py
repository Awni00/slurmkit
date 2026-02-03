"""
Cross-cluster job state synchronization.

This module provides utilities for syncing job states across multiple
compute clusters. It works by:
1. Refreshing job states from SLURM on the current cluster
2. Writing state information to a human-readable YAML file
3. The sync file can be committed and pushed to git for sharing

Sync files are organized by hostname, so each cluster writes its own
file that can be merged in the shared repository.
"""

from __future__ import annotations

import socket
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml

from slurmkit.config import Config, get_config
from slurmkit.collections import Collection, CollectionManager


# =============================================================================
# Sync File Management
# =============================================================================

class SyncManager:
    """
    Manager for cross-cluster job state synchronization.

    Handles writing sync files and optionally committing/pushing them
    to git for sharing across clusters.

    Attributes:
        sync_dir: Directory where sync files are stored.
        hostname: Current machine's hostname.

    Example:
        >>> sync_mgr = SyncManager()
        >>> sync_mgr.sync_all()  # Refresh and write sync file
        >>> sync_mgr.push()      # Git commit and push
    """

    def __init__(
        self,
        sync_dir: Optional[Union[str, Path]] = None,
        config: Optional[Config] = None,
    ):
        """
        Initialize the sync manager.

        Args:
            sync_dir: Directory for sync files. If None, uses config.
            config: Configuration object. If None, uses global config.
        """
        if config is None:
            config = get_config()

        self.config = config
        self.hostname = socket.gethostname()

        if sync_dir is not None:
            self.sync_dir = Path(sync_dir)
        else:
            self.sync_dir = config.get_path("sync_dir")
            if self.sync_dir is None:
                self.sync_dir = Path(".slurm-kit/sync")

        self._collection_manager = CollectionManager(config=config)

    def _ensure_dir(self) -> None:
        """Ensure the sync directory exists."""
        self.sync_dir.mkdir(parents=True, exist_ok=True)

    def get_sync_file_path(self, hostname: Optional[str] = None) -> Path:
        """
        Get the path to a sync file for a hostname.

        Args:
            hostname: Hostname for the sync file. Defaults to current host.

        Returns:
            Path to the sync file.
        """
        hostname = hostname or self.hostname
        return self.sync_dir / f"{hostname}.yaml"

    def sync_collection(self, name: str) -> Dict[str, Any]:
        """
        Sync a single collection's job states.

        Refreshes job states from SLURM and returns the updated data.

        Args:
            name: Collection name.

        Returns:
            Collection sync data dictionary.
        """
        collection = self._collection_manager.load(name)

        # Refresh states from SLURM
        updated_count = collection.refresh_states()

        # Save updated collection
        self._collection_manager.save(collection)

        # Build sync data
        summary = collection.get_summary()

        jobs_data = []
        for job in collection.jobs:
            job_data = {
                "job_name": job["job_name"],
                "job_id": job.get("job_id"),
                "state": job.get("state"),
                "hostname": job.get("hostname"),
            }

            # Include resubmission info if any
            if job.get("resubmissions"):
                job_data["resubmissions"] = [
                    {
                        "job_id": r.get("job_id"),
                        "state": r.get("state"),
                        "hostname": r.get("hostname"),
                    }
                    for r in job["resubmissions"]
                ]

            jobs_data.append(job_data)

        return {
            "name": name,
            "description": collection.description,
            "updated_jobs": updated_count,
            **summary,
            "jobs": jobs_data,
        }

    def sync_all(
        self,
        collection_names: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Sync all collections and write sync file.

        Args:
            collection_names: List of collection names to sync.
                If None, syncs all collections.

        Returns:
            Complete sync data dictionary.
        """
        if collection_names is None:
            collection_names = self._collection_manager.list_collections()

        collections_data = {}
        total_updated = 0

        for name in collection_names:
            try:
                data = self.sync_collection(name)
                collections_data[name] = data
                total_updated += data.get("updated_jobs", 0)
            except FileNotFoundError:
                # Skip collections that don't exist
                continue
            except Exception as e:
                # Log error but continue with other collections
                print(f"Warning: Error syncing collection '{name}': {e}")
                continue

        # Build sync file data
        sync_data = {
            "cluster": self.hostname,
            "synced_at": datetime.now().isoformat(timespec="seconds"),
            "total_collections": len(collections_data),
            "total_jobs_updated": total_updated,
            "collections": collections_data,
        }

        # Write sync file
        self._ensure_dir()
        sync_path = self.get_sync_file_path()

        with open(sync_path, "w") as f:
            yaml.dump(
                sync_data,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )

        return sync_data

    def read_sync_file(self, hostname: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Read a sync file.

        Args:
            hostname: Hostname of the sync file to read.

        Returns:
            Sync data dictionary, or None if file doesn't exist.
        """
        path = self.get_sync_file_path(hostname)

        if not path.exists():
            return None

        with open(path, "r") as f:
            return yaml.safe_load(f)

    def list_sync_files(self) -> List[str]:
        """
        List all available sync files.

        Returns:
            List of hostnames with sync files.
        """
        if not self.sync_dir.exists():
            return []

        return [p.stem for p in self.sync_dir.glob("*.yaml")]

    def get_all_sync_data(self) -> Dict[str, Dict[str, Any]]:
        """
        Read all sync files.

        Returns:
            Dictionary mapping hostname to sync data.
        """
        result = {}
        for hostname in self.list_sync_files():
            data = self.read_sync_file(hostname)
            if data:
                result[hostname] = data
        return result

    def push(self, message: Optional[str] = None) -> bool:
        """
        Git commit and push sync files.

        Args:
            message: Commit message. If None, uses a default message.

        Returns:
            True if successful, False otherwise.
        """
        sync_path = self.get_sync_file_path()

        if not sync_path.exists():
            print("No sync file to push. Run sync first.")
            return False

        if message is None:
            message = f"slurmkit sync: {self.hostname} at {datetime.now().isoformat(timespec='seconds')}"

        try:
            # Git add
            result = subprocess.run(
                ["git", "add", str(sync_path)],
                capture_output=True,
                text=True,
                cwd=self.sync_dir.parent,
            )
            if result.returncode != 0:
                print(f"git add failed: {result.stderr}")
                return False

            # Git commit
            result = subprocess.run(
                ["git", "commit", "-m", message],
                capture_output=True,
                text=True,
                cwd=self.sync_dir.parent,
            )
            if result.returncode != 0:
                if "nothing to commit" in result.stdout:
                    print("No changes to commit.")
                    return True
                print(f"git commit failed: {result.stderr}")
                return False

            # Git push
            result = subprocess.run(
                ["git", "push"],
                capture_output=True,
                text=True,
                cwd=self.sync_dir.parent,
            )
            if result.returncode != 0:
                print(f"git push failed: {result.stderr}")
                return False

            print(f"Successfully pushed sync file: {sync_path.name}")
            return True

        except FileNotFoundError:
            print("git command not found.")
            return False

    def get_combined_status(
        self,
        collection_name: str,
    ) -> Dict[str, Any]:
        """
        Get combined job status across all clusters.

        Merges job information from all sync files to provide a
        unified view of job states across clusters.

        Args:
            collection_name: Name of the collection.

        Returns:
            Dictionary with combined job status information.
        """
        all_sync = self.get_all_sync_data()

        combined_jobs = {}
        clusters = []

        for hostname, sync_data in all_sync.items():
            clusters.append(hostname)
            collection_data = sync_data.get("collections", {}).get(collection_name)

            if not collection_data:
                continue

            for job in collection_data.get("jobs", []):
                job_name = job["job_name"]

                if job_name not in combined_jobs:
                    combined_jobs[job_name] = {
                        "job_name": job_name,
                        "submissions": [],
                    }

                # Add this cluster's submission info
                submission = {
                    "cluster": hostname,
                    "job_id": job.get("job_id"),
                    "state": job.get("state"),
                }

                combined_jobs[job_name]["submissions"].append(submission)

                # Add resubmissions
                for resub in job.get("resubmissions", []):
                    resubmission = {
                        "cluster": resub.get("hostname", hostname),
                        "job_id": resub.get("job_id"),
                        "state": resub.get("state"),
                        "is_resubmission": True,
                    }
                    combined_jobs[job_name]["submissions"].append(resubmission)

        # Compute overall state for each job
        for job_name, job_data in combined_jobs.items():
            states = [s["state"] for s in job_data["submissions"] if s["state"]]
            if "COMPLETED" in states:
                job_data["overall_state"] = "COMPLETED"
            elif "RUNNING" in states:
                job_data["overall_state"] = "RUNNING"
            elif "PENDING" in states:
                job_data["overall_state"] = "PENDING"
            elif any(s in ("FAILED", "CANCELLED", "TIMEOUT") for s in states):
                job_data["overall_state"] = "FAILED"
            else:
                job_data["overall_state"] = "UNKNOWN"

        return {
            "collection": collection_name,
            "clusters": clusters,
            "jobs": list(combined_jobs.values()),
        }


# =============================================================================
# Convenience Functions
# =============================================================================

def sync_jobs(
    collection_names: Optional[List[str]] = None,
    push: bool = False,
) -> Dict[str, Any]:
    """
    Sync job states and optionally push to git.

    Args:
        collection_names: Collections to sync. If None, syncs all.
        push: If True, commit and push sync file to git.

    Returns:
        Sync data dictionary.
    """
    manager = SyncManager()
    result = manager.sync_all(collection_names)

    if push:
        manager.push()

    return result


def get_cross_cluster_status(collection_name: str) -> Dict[str, Any]:
    """
    Get job status across all clusters.

    Args:
        collection_name: Collection to get status for.

    Returns:
        Combined status dictionary.
    """
    manager = SyncManager()
    return manager.get_combined_status(collection_name)
