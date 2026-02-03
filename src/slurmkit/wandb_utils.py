"""
Weights & Biases (W&B) utilities for job management.

This module provides utilities for:
- Querying W&B runs and their states
- Cleaning up failed/crashed runs with short runtimes
- Extracting run information

Note: This module requires the `wandb` package to be installed.
If wandb is not installed, importing this module will raise ImportError.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

import wandb

from slurmkit.config import Config, get_config


# =============================================================================
# Run Information Extraction
# =============================================================================

def get_run_info(run: Any) -> Dict[str, Any]:
    """
    Extract relevant information from a wandb Run object.

    Args:
        run: A wandb Run object from the API.

    Returns:
        Dictionary with run information including:
        - id: Run ID
        - name: Run name
        - state: Run state (running, finished, failed, crashed, killed)
        - group: Run group (if any)
        - created_at: Creation timestamp
        - started_at: Start timestamp (formatted)
        - runtime: Runtime as string
        - runtime_seconds: Runtime in seconds
        - config: Run configuration dict
        - summary: Run summary metrics dict
        - url: URL to the run
    """
    # Get timestamps
    created_at = run.created_at if hasattr(run, 'created_at') else None
    started_at = None

    # Try to get started_at from run metadata
    if hasattr(run, 'metadata') and run.metadata:
        started_at = run.metadata.get('startedAt')

    # Format started_at
    if started_at:
        try:
            # Parse ISO format and convert to friendly format
            dt = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
            started_at_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, AttributeError):
            started_at_str = str(started_at)
    elif created_at:
        started_at_str = created_at
    else:
        started_at_str = "Unknown"

    # Get runtime
    runtime = None
    runtime_seconds = -1

    if hasattr(run, 'summary') and run.summary:
        # Try _runtime (actual runtime)
        if '_runtime' in run.summary:
            runtime_seconds = int(run.summary['_runtime'])
            runtime = _format_runtime(runtime_seconds)
        # Try _wandb.runtime as fallback
        elif '_wandb' in run.summary and 'runtime' in run.summary['_wandb']:
            runtime_seconds = int(run.summary['_wandb']['runtime'])
            runtime = _format_runtime(runtime_seconds)

    return {
        "id": run.id,
        "name": run.name,
        "state": run.state,
        "group": run.group if hasattr(run, 'group') else None,
        "created_at": created_at,
        "started_at": started_at_str,
        "runtime": runtime or "N/A",
        "runtime_seconds": runtime_seconds,
        "config": dict(run.config) if hasattr(run, 'config') else {},
        "summary": dict(run.summary) if hasattr(run, 'summary') else {},
        "url": run.url if hasattr(run, 'url') else None,
    }


def _format_runtime(seconds: int) -> str:
    """
    Format runtime in seconds to human-readable string.

    Args:
        seconds: Runtime in seconds.

    Returns:
        Formatted string like "1d 2h 30m 15s" or "2h 30m 15s".
    """
    if seconds < 0:
        return "N/A"

    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0 or not parts:
        parts.append(f"{secs}s")

    return " ".join(parts)


def parse_runtime_to_seconds(runtime_str: str) -> int:
    """
    Parse a runtime string into total seconds.

    Supports formats:
    - Numeric seconds (e.g., "3600")
    - "H:MM:SS" or "H:MM:SS.microseconds"
    - "X days, H:MM:SS"

    Args:
        runtime_str: Runtime string to parse.

    Returns:
        Total seconds, or -1 if parsing fails.
    """
    if not runtime_str or runtime_str == "N/A":
        return -1

    # Try parsing as a number (seconds)
    try:
        return int(float(runtime_str))
    except (ValueError, TypeError):
        pass

    # Try parsing timedelta string format
    try:
        days = 0
        time_part = runtime_str

        if "day" in runtime_str:
            day_part, time_part = runtime_str.split(", ", 1)
            days = int(day_part.split()[0])

        parts = time_part.split(":")
        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
            return int(days * 86400 + hours * 3600 + minutes * 60 + seconds)

    except (ValueError, IndexError):
        pass

    return -1


# =============================================================================
# W&B Run Queries
# =============================================================================

def get_runs(
    project: str,
    entity: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
    config: Optional[Config] = None,
) -> List[Any]:
    """
    Query runs from a W&B project.

    Args:
        project: W&B project name.
        entity: W&B entity (username or team). If None, uses config default.
        filters: Optional filters dict for the query.
        config: Configuration object.

    Returns:
        List of wandb Run objects.
    """
    if config is None:
        config = get_config()

    if entity is None:
        entity = config.get("wandb.entity")

    # Build project path
    if entity:
        project_path = f"{entity}/{project}"
    else:
        project_path = project

    api = wandb.Api()
    runs = api.runs(project_path, filters=filters)

    return list(runs)


def get_failed_runs(
    project: str,
    entity: Optional[str] = None,
    threshold_seconds: int = 300,
    min_age_days: int = 3,
    config: Optional[Config] = None,
) -> List[Dict[str, Any]]:
    """
    Get failed/crashed runs with short runtimes.

    Args:
        project: W&B project name.
        entity: W&B entity.
        threshold_seconds: Maximum runtime in seconds for runs to include.
        min_age_days: Minimum age in days for runs to include.
        config: Configuration object.

    Returns:
        List of run info dictionaries for matching runs.
    """
    if config is None:
        config = get_config()

    # Query for failed/crashed/killed runs
    runs = get_runs(
        project=project,
        entity=entity,
        filters={"state": {"$in": ["failed", "crashed", "killed"]}},
        config=config,
    )

    age_cutoff = datetime.utcnow() - timedelta(days=min_age_days)
    failed_runs = []

    for run in runs:
        try:
            run_info = get_run_info(run)

            # Check age
            started_at_str = run_info["started_at"]
            if started_at_str != "Unknown":
                try:
                    started_at = datetime.strptime(started_at_str, "%Y-%m-%d %H:%M:%S")
                    if started_at > age_cutoff:
                        continue  # Skip recent runs
                except ValueError:
                    continue

            # Check runtime
            runtime_seconds = run_info["runtime_seconds"]
            if runtime_seconds < 0:
                continue  # Skip if we couldn't determine runtime

            if runtime_seconds <= threshold_seconds:
                # Keep reference to run object for deletion
                run_info["_run_obj"] = run
                failed_runs.append(run_info)

        except Exception as e:
            print(f"Warning: Error processing run {run.id}: {e}", file=sys.stderr)
            continue

    return failed_runs


# =============================================================================
# Cleanup Functions
# =============================================================================

def clean_failed_runs(
    projects: List[str],
    entity: Optional[str] = None,
    threshold_seconds: int = 300,
    min_age_days: int = 3,
    dry_run: bool = False,
    confirm_callback: Optional[Callable[[List[Dict]], bool]] = None,
    config: Optional[Config] = None,
) -> Dict[str, Any]:
    """
    Clean up failed W&B runs with short runtimes.

    Args:
        projects: List of W&B project names to clean.
        entity: W&B entity.
        threshold_seconds: Maximum runtime in seconds for runs to delete.
        min_age_days: Minimum age in days for runs to consider.
        dry_run: If True, don't actually delete runs.
        confirm_callback: Optional callback for confirmation. Takes list of runs,
            returns True to proceed with deletion.
        config: Configuration object.

    Returns:
        Dictionary with cleanup results:
        - projects_scanned: Number of projects scanned
        - runs_found: Total runs matching criteria
        - runs_deleted: Number of runs deleted
        - errors: List of error messages
    """
    if config is None:
        config = get_config()

    if entity is None:
        entity = config.get("wandb.entity")

    all_failed_runs = []
    errors = []

    # Collect failed runs from all projects
    for project in projects:
        try:
            failed_runs = get_failed_runs(
                project=project,
                entity=entity,
                threshold_seconds=threshold_seconds,
                min_age_days=min_age_days,
                config=config,
            )
            # Add project info to each run
            for run_info in failed_runs:
                run_info["project"] = project
            all_failed_runs.extend(failed_runs)
        except Exception as e:
            errors.append(f"Error accessing project '{project}': {e}")

    if not all_failed_runs:
        return {
            "projects_scanned": len(projects),
            "runs_found": 0,
            "runs_deleted": 0,
            "errors": errors,
        }

    # Confirm deletion if callback provided
    if confirm_callback is not None:
        if not confirm_callback(all_failed_runs):
            return {
                "projects_scanned": len(projects),
                "runs_found": len(all_failed_runs),
                "runs_deleted": 0,
                "errors": errors,
                "aborted": True,
            }

    if dry_run:
        return {
            "projects_scanned": len(projects),
            "runs_found": len(all_failed_runs),
            "runs_deleted": 0,
            "dry_run": True,
            "errors": errors,
        }

    # Delete runs
    deleted_count = 0
    for run_info in all_failed_runs:
        try:
            run_obj = run_info["_run_obj"]
            run_obj.delete()
            deleted_count += 1
        except Exception as e:
            errors.append(f"Error deleting run '{run_info.get('name', 'unknown')}': {e}")

    return {
        "projects_scanned": len(projects),
        "runs_found": len(all_failed_runs),
        "runs_deleted": deleted_count,
        "errors": errors,
    }


def format_runs_table(runs: List[Dict[str, Any]]) -> str:
    """
    Format a list of runs as a table string.

    Args:
        runs: List of run info dictionaries.

    Returns:
        Formatted table string.
    """
    if not runs:
        return "No runs found."

    # Column headers and widths
    headers = ["Project", "Name", "Group", "State", "Runtime"]
    widths = [35, 40, 25, 10, 15]

    # Build header row
    header_row = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    separator = "-" * len(header_row)

    lines = [separator, header_row, separator]

    for run in runs:
        project = str(run.get("project", "N/A"))[:33]
        name = str(run.get("name", "N/A"))[:38]
        group = str(run.get("group", "N/A"))[:23]
        state = str(run.get("state", "N/A"))[:8]
        runtime = str(run.get("runtime", "N/A"))[:13]

        row = "  ".join([
            project.ljust(widths[0]),
            name.ljust(widths[1]),
            group.ljust(widths[2]),
            state.ljust(widths[3]),
            runtime.ljust(widths[4]),
        ])
        lines.append(row)

    lines.append(separator)
    return "\n".join(lines)
