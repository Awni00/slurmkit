"""
SLURM utilities for interacting with the SLURM job scheduler.

This module provides functions for:
- Querying job status via sacct
- Querying pending/running jobs via squeue
- Finding job output files
- Submitting jobs via sbatch
- Parsing SLURM command outputs

These utilities wrap SLURM CLI commands and parse their outputs into
Python data structures for easy manipulation.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from slurmkit.config import Config, get_config


# =============================================================================
# Constants
# =============================================================================

# Default fields to query from sacct
DEFAULT_SACCT_FIELDS = ["JobID", "State", "Elapsed", "Start", "End", "ExitCode"]

# All available sacct fields for reference (commonly used ones):
# Time: Elapsed, Start, End, Submit, Timelimit, CPUTime, TotalCPU, ElapsedRaw
# Resources: AllocCPUS, AllocNodes, ReqMem, MaxRSS, NCPUS, NNodes, ReqCPUS
# Status: State, ExitCode, DerivedExitCode, Reason
# Identity: JobName, User, Account, Partition, QOS
# Other: NodeList, WorkDir, Comment, Cluster

# Job states that indicate completion
COMPLETED_STATES = {"COMPLETED"}
FAILED_STATES = {"FAILED", "CANCELLED", "TIMEOUT", "NODE_FAIL", "PREEMPTED", "OUT_OF_MEMORY"}
RUNNING_STATES = {"RUNNING", "COMPLETING"}
PENDING_STATES = {"PENDING", "REQUEUED", "SUSPENDED"}


# =============================================================================
# Command Execution
# =============================================================================

def run_command(
    cmd: List[str],
    check: bool = False,
    capture_output: bool = True,
) -> subprocess.CompletedProcess:
    """
    Run a shell command and return the result.

    Args:
        cmd: Command and arguments as a list.
        check: If True, raise CalledProcessError on non-zero exit.
        capture_output: If True, capture stdout and stderr.

    Returns:
        CompletedProcess object with stdout, stderr, and returncode.
    """
    return subprocess.run(
        cmd,
        check=check,
        capture_output=capture_output,
        text=True,
    )


# =============================================================================
# sacct Functions
# =============================================================================

def get_sacct_info(
    job_ids: Union[str, List[str]],
    fields: Optional[List[str]] = None,
) -> Dict[str, Dict[str, str]]:
    """
    Query sacct for job metadata.

    Queries the SLURM accounting database for information about completed
    or running jobs. Results are filtered to exclude job steps (e.g., .batch,
    .extern) and only return the main job entry.

    Args:
        job_ids: Single job ID or list of job IDs to query.
        fields: List of sacct fields to retrieve. Defaults to DEFAULT_SACCT_FIELDS.
            Common fields: State, Elapsed, Start, End, ExitCode, AllocCPUS,
            ReqMem, NodeList, Partition. Run `sacct --helpformat` for full list.

    Returns:
        Dictionary mapping JobID to a dict of field values.
        Returns empty dict if sacct is not available or no jobs found.

    Example:
        >>> info = get_sacct_info(["12345", "12346"])
        >>> info["12345"]["State"]
        'COMPLETED'
        >>> info["12345"]["Elapsed"]
        '01:23:45'
    """
    # Normalize to list
    if isinstance(job_ids, str):
        job_ids = [job_ids]

    if not job_ids:
        return {}

    if fields is None:
        fields = DEFAULT_SACCT_FIELDS.copy()

    # Ensure JobID is always first
    if "JobID" not in fields:
        fields = ["JobID"] + list(fields)

    # Build sacct command
    # --parsable2 gives pipe-delimited output without trailing delimiter
    cmd = [
        "sacct",
        "-j", ",".join(job_ids),
        f"--format={','.join(fields)}",
        "--parsable2",
        "--noheader",
    ]

    try:
        result = run_command(cmd)
        info_map = {}

        for line in result.stdout.splitlines():
            if not line.strip():
                continue

            parts = line.strip().split("|")
            if len(parts) < len(fields):
                continue

            job_id_raw = parts[0]

            # Filter out job steps (e.g., 12345.batch, 12345.extern)
            # We only want the main job entry which has no dots
            # (array jobs use underscore: 12345_1, 12345_2, etc.)
            if "." not in job_id_raw:
                info_map[job_id_raw] = {
                    field: parts[i] for i, field in enumerate(fields)
                }

        return info_map

    except FileNotFoundError:
        print("Error: sacct command not found. Is SLURM installed?", file=sys.stderr)
        return {}


def get_job_status(job_ids: Union[str, List[str]]) -> Dict[str, str]:
    """
    Get the state of one or more jobs.

    Convenience wrapper around get_sacct_info that returns only job states.

    Args:
        job_ids: Single job ID or list of job IDs.

    Returns:
        Dictionary mapping JobID to State string.

    Example:
        >>> get_job_status(["12345", "12346"])
        {'12345': 'COMPLETED', '12346': 'FAILED'}
    """
    info = get_sacct_info(job_ids, fields=["JobID", "State"])
    return {jid: data.get("State", "UNKNOWN") for jid, data in info.items()}


# =============================================================================
# squeue Functions
# =============================================================================

def get_pending_jobs(user: Optional[str] = None) -> List[Dict[str, str]]:
    """
    Query squeue for currently pending or running jobs.

    Args:
        user: Username to filter jobs. If None, uses current user (--me).

    Returns:
        List of dicts with keys: 'job_id', 'job_name', 'state', 'wait_time'.
        wait_time is formatted as human-readable string for pending jobs.

    Example:
        >>> pending = get_pending_jobs()
        >>> pending[0]
        {'job_id': '12345', 'job_name': 'train_model', 'state': 'PENDING', 'wait_time': '2h 30m'}
    """
    # Build squeue command
    # --start shows estimated start time for pending jobs
    # Format: job_id|job_name|state|start_time
    cmd = ["squeue", "--start", "--format=%i|%j|%T|%S", "--noheader"]

    if user:
        cmd.extend(["-u", user])
    else:
        cmd.append("--me")

    try:
        result = run_command(cmd)
        pending_jobs = []
        now = datetime.now()

        for line in result.stdout.splitlines():
            if not line.strip():
                continue

            parts = line.strip().split("|")
            if len(parts) < 4:
                continue

            job_id, job_name, state, start_time_str = parts[:4]

            job_info = {
                "job_id": job_id,
                "job_name": job_name,
                "state": state,
            }

            # Calculate wait time for pending jobs
            if state == "PENDING" and start_time_str not in ("N/A", "Unknown"):
                wait_time = _parse_wait_time(start_time_str, now)
                job_info["wait_time"] = wait_time
            elif state == "PENDING":
                job_info["wait_time"] = "N/A"

            pending_jobs.append(job_info)

        return pending_jobs

    except FileNotFoundError:
        print("Error: squeue command not found. Is SLURM installed?", file=sys.stderr)
        return []


def _parse_wait_time(start_time_str: str, now: datetime) -> str:
    """
    Parse estimated start time and format as wait time string.

    Args:
        start_time_str: ISO format timestamp from squeue (YYYY-MM-DDTHH:MM:SS).
        now: Current datetime for calculating wait duration.

    Returns:
        Human-readable wait time string (e.g., "2d 5h 30m").
    """
    try:
        start_time = datetime.strptime(start_time_str, "%Y-%m-%dT%H:%M:%S")
        wait_delta = start_time - now
        total_seconds = int(wait_delta.total_seconds())

        if total_seconds < 0:
            return "Starting soon"

        days, remainder = divmod(total_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, _ = divmod(remainder, 60)

        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0 or not parts:
            parts.append(f"{minutes}m")

        return " ".join(parts)

    except ValueError:
        return "Unknown"


# =============================================================================
# scontrol Functions
# =============================================================================

def get_job_script_path(job_id: str) -> Optional[Path]:
    """
    Get the script path for a job using scontrol.

    This only works for jobs that are still in SLURM's active job table
    (typically running or recently completed jobs).

    Args:
        job_id: SLURM job ID.

    Returns:
        Path to the job script, or None if not found.
    """
    cmd = ["scontrol", "show", "job", job_id]

    try:
        result = run_command(cmd)
        if result.returncode != 0 or not result.stdout.strip():
            return None

        # Parse key=value output
        for token in result.stdout.split():
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            if key in ("Command", "BatchScript"):
                if value and value not in ("(null)", "Unknown"):
                    return Path(value)

        return None

    except FileNotFoundError:
        return None


# =============================================================================
# Job Output File Functions
# =============================================================================

def find_job_output(
    job_id: str,
    jobs_dir: Optional[Path] = None,
    config: Optional[Config] = None,
) -> List[Path]:
    """
    Find job output files matching a job ID.

    Searches for .out files containing the job ID in their filename,
    using configured output patterns to match files.

    Args:
        job_id: SLURM job ID to search for.
        jobs_dir: Directory to search in. If None, uses config's jobs_dir.
        config: Configuration object. If None, uses global config.

    Returns:
        List of matching file paths, sorted by modification time (newest first).

    Example:
        >>> outputs = find_job_output("12345")
        >>> outputs[0]
        PosixPath('jobs/exp1/logs/train_model.12345.out')
    """
    if config is None:
        config = get_config()

    if jobs_dir is None:
        jobs_dir = config.get_path("jobs_dir")

    if jobs_dir is None or not jobs_dir.exists():
        return []

    # Search for files containing the job ID
    # Use glob pattern that matches the ID anywhere in the filename
    pattern = f"**/*{job_id}*.out"
    matches = list(jobs_dir.glob(pattern))

    # Sort by modification time (newest first)
    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    return matches


def match_output_pattern(
    filename: str,
    patterns: Optional[List[str]] = None,
    config: Optional[Config] = None,
) -> Optional[Tuple[str, str]]:
    """
    Match a filename against configured output patterns.

    Attempts to extract job_name and job_id from a filename using the
    configured output patterns in priority order.

    Args:
        filename: Filename to match (not full path).
        patterns: List of patterns to try. If None, uses config's output_patterns.
        config: Configuration object. If None, uses global config.

    Returns:
        Tuple of (job_name, job_id) if matched, None otherwise.

    Example:
        >>> match_output_pattern("train_model.12345.out")
        ('train_model', '12345')
        >>> match_output_pattern("slurm-12345.out")
        ('slurm', '12345')
    """
    if config is None:
        config = get_config()

    if patterns is None:
        patterns = config.get_output_patterns()

    for pattern in patterns:
        result = _try_match_pattern(filename, pattern)
        if result:
            return result

    return None


def _try_match_pattern(filename: str, pattern: str) -> Optional[Tuple[str, str]]:
    """
    Try to match a filename against a single pattern.

    Patterns support {job_name}, {job_id}, and * wildcards.

    Args:
        filename: Filename to match.
        pattern: Pattern string (e.g., "{job_name}.{job_id}.out").

    Returns:
        Tuple of (job_name, job_id) if matched, None otherwise.
    """
    # Convert pattern to regex
    # Escape dots, replace placeholders with capture groups
    regex_pattern = pattern
    regex_pattern = regex_pattern.replace(".", r"\.")
    regex_pattern = regex_pattern.replace("*", r"[^.]*")
    regex_pattern = regex_pattern.replace("{job_name}", r"(?P<job_name>.+?)")
    regex_pattern = regex_pattern.replace("{job_id}", r"(?P<job_id>\d+(?:_\d+)?)")

    # Anchor the pattern
    regex_pattern = f"^{regex_pattern}$"

    match = re.match(regex_pattern, filename)
    if match:
        groups = match.groupdict()
        job_name = groups.get("job_name", "unknown")
        job_id = groups.get("job_id", "")
        if job_id:
            return (job_name, job_id)

    return None


def infer_job_name_from_output(
    output_path: Path,
    config: Optional[Config] = None,
) -> Optional[str]:
    """
    Infer the job name from an output file path.

    Args:
        output_path: Path to the output file.
        config: Configuration object. If None, uses global config.

    Returns:
        Job name if pattern matched, None otherwise.
    """
    result = match_output_pattern(output_path.name, config=config)
    if result:
        return result[0]
    return None


def infer_job_id_from_output(
    output_path: Path,
    config: Optional[Config] = None,
) -> Optional[str]:
    """
    Infer the job ID from an output file path.

    Args:
        output_path: Path to the output file.
        config: Configuration object. If None, uses global config.

    Returns:
        Job ID if pattern matched, None otherwise.
    """
    result = match_output_pattern(output_path.name, config=config)
    if result:
        return result[1]
    return None


# =============================================================================
# Job Script Functions
# =============================================================================

def infer_script_path(
    job_id: str,
    jobs_dir: Optional[Path] = None,
    config: Optional[Config] = None,
) -> Optional[Path]:
    """
    Infer the job script path for a given job ID.

    Tries multiple strategies in order:
    1. scontrol show job (for active jobs)
    2. sacct Command field (for completed jobs)
    3. Infer from output file location and naming convention

    Args:
        job_id: SLURM job ID.
        jobs_dir: Root jobs directory for file-based inference.
        config: Configuration object. If None, uses global config.

    Returns:
        Path to the job script if found, None otherwise.
    """
    if config is None:
        config = get_config()

    if jobs_dir is None:
        jobs_dir = config.get_path("jobs_dir")

    # Strategy 1: scontrol (for active jobs)
    script_path = get_job_script_path(job_id)
    if script_path and script_path.exists():
        return script_path

    # Strategy 2: sacct Command field
    info = get_sacct_info([job_id], fields=["JobID", "Command"])
    if job_id in info:
        command = info[job_id].get("Command", "")
        if command and command not in ("(null)", "Unknown", ""):
            path = Path(command)
            if path.exists():
                return path

    # Strategy 3: Infer from output file
    return _infer_script_from_output(job_id, jobs_dir, config)


def _infer_script_from_output(
    job_id: str,
    jobs_dir: Optional[Path],
    config: Config,
) -> Optional[Path]:
    """
    Infer script path from output file location.

    Assumes directory structure:
        experiment_dir/
        ├── logs/           <- output files
        └── job_scripts/    <- job scripts

    Args:
        job_id: SLURM job ID.
        jobs_dir: Root jobs directory.
        config: Configuration object.

    Returns:
        Path to inferred script, or None.
    """
    if jobs_dir is None or not jobs_dir.exists():
        return None

    # Find output file
    outputs = find_job_output(job_id, jobs_dir, config)
    if len(outputs) != 1:
        return None

    output_path = outputs[0]

    # Extract job name from output filename
    job_name = infer_job_name_from_output(output_path, config)
    if not job_name:
        return None

    # Get configured subdirectory names
    logs_subdir = config.get("job_structure.logs_subdir", "logs/").rstrip("/")
    scripts_subdir = config.get("job_structure.scripts_subdir", "job_scripts/").rstrip("/")

    # Check if output is in a logs directory
    logs_dir = output_path.parent
    if logs_dir.name == logs_subdir.split("/")[-1]:
        # Look for script in sibling job_scripts directory
        experiment_dir = logs_dir.parent
        candidate = experiment_dir / scripts_subdir / f"{job_name}.job"
        if candidate.exists():
            return candidate

    # Fallback: search for matching .job file
    matches = list(jobs_dir.rglob(f"{job_name}.job"))
    if len(matches) == 1:
        return matches[0]

    return None


# =============================================================================
# Job Submission
# =============================================================================

def submit_job(
    script_path: Union[str, Path],
    dry_run: bool = False,
    extra_args: Optional[List[str]] = None,
) -> Tuple[bool, Optional[str], str]:
    """
    Submit a job script using sbatch.

    Args:
        script_path: Path to the job script.
        dry_run: If True, print command without executing.
        extra_args: Additional arguments to pass to sbatch.

    Returns:
        Tuple of (success, job_id, message).
        - success: True if submission succeeded.
        - job_id: The submitted job ID (None if failed or dry_run).
        - message: Output message from sbatch or error message.

    Example:
        >>> success, job_id, msg = submit_job("jobs/train.job")
        >>> print(f"Submitted job {job_id}")
        Submitted job 12345
    """
    script_path = Path(script_path)

    if not script_path.exists():
        return False, None, f"Script not found: {script_path}"

    cmd = ["sbatch"]
    if extra_args:
        cmd.extend(extra_args)
    cmd.append(str(script_path))

    if dry_run:
        return True, None, f"[dry-run] {' '.join(cmd)}"

    try:
        result = run_command(cmd)

        if result.returncode == 0:
            # Parse job ID from sbatch output
            # Typical output: "Submitted batch job 12345"
            output = result.stdout.strip()
            job_id = None

            match = re.search(r"Submitted batch job (\d+)", output)
            if match:
                job_id = match.group(1)

            return True, job_id, output

        else:
            error_msg = result.stderr.strip() or result.stdout.strip()
            return False, None, f"sbatch failed: {error_msg}"

    except FileNotFoundError:
        return False, None, "sbatch command not found. Is SLURM installed?"


# =============================================================================
# Time Parsing Utilities
# =============================================================================

def parse_elapsed_to_seconds(elapsed: str) -> int:
    """
    Parse an elapsed time string from sacct into total seconds.

    Supports formats:
    - "MM:SS"
    - "HH:MM:SS"
    - "D-HH:MM:SS"

    Args:
        elapsed: Elapsed time string from sacct.

    Returns:
        Total seconds, or -1 if parsing fails.

    Example:
        >>> parse_elapsed_to_seconds("01:23:45")
        5025
        >>> parse_elapsed_to_seconds("1-12:30:00")
        131400
    """
    if not elapsed or elapsed in ("N/A", "UNKNOWN", "Unknown"):
        return -1

    try:
        days = 0
        if "-" in elapsed:
            day_part, time_part = elapsed.split("-", 1)
            days = int(day_part)
        else:
            time_part = elapsed

        parts = time_part.split(":")
        if len(parts) == 3:
            hours, minutes, seconds = int(parts[0]), int(parts[1]), int(parts[2])
        elif len(parts) == 2:
            hours = 0
            minutes, seconds = int(parts[0]), int(parts[1])
        else:
            return -1

        return days * 86400 + hours * 3600 + minutes * 60 + seconds

    except (ValueError, IndexError):
        return -1


def parse_timestamp(timestamp_str: str) -> Optional[datetime]:
    """
    Parse a timestamp string from sacct/squeue into a datetime.

    Args:
        timestamp_str: Timestamp string (e.g., "2025-01-15T14:30:00").

    Returns:
        Parsed datetime, or None if parsing fails.
    """
    if not timestamp_str or timestamp_str in ("N/A", "UNKNOWN", "Unknown"):
        return None

    try:
        return datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None


# =============================================================================
# Job Data Aggregation
# =============================================================================

def get_jobs_data(
    target_dir: Path,
    include_sacct_info: bool = True,
    sacct_fields: Optional[List[str]] = None,
    include_pending: bool = True,
    config: Optional[Config] = None,
) -> List[Dict[str, Any]]:
    """
    Scan a directory for job output files and return aggregated job data.

    Combines information from:
    - Output file names (job_name, job_id, file path)
    - sacct (state, elapsed time, etc.)
    - squeue (pending jobs with wait times)

    Args:
        target_dir: Directory to scan for .out files.
        include_sacct_info: Whether to query sacct for job metadata.
        sacct_fields: List of sacct fields to retrieve.
        include_pending: Whether to include pending/running jobs from squeue.
        config: Configuration object. If None, uses global config.

    Returns:
        List of job data dictionaries with keys:
        - job_name: Inferred job name
        - job_id: SLURM job ID
        - output_file: Path to output file
        - state: Job state (from sacct or squeue)
        - Additional fields from sacct_fields

    Example:
        >>> jobs = get_jobs_data(Path("jobs/exp1"))
        >>> jobs[0]
        {'job_name': 'train', 'job_id': '12345', 'state': 'COMPLETED', ...}
    """
    if config is None:
        config = get_config()

    target_dir = Path(target_dir)

    if not target_dir.exists():
        return []

    # Scan for .out files
    out_files = sorted(target_dir.rglob("*.out"))
    if not out_files:
        return []

    jobs_data = []
    job_ids_to_query = set()

    # Parse output files
    for f in out_files:
        result = match_output_pattern(f.name, config=config)
        if result:
            job_name, job_id = result
            jobs_data.append({
                "job_name": job_name,
                "job_id": job_id,
                "output_file": f,
            })
            job_ids_to_query.add(job_id)

    # Get pending/running jobs
    if include_pending:
        pending_list = get_pending_jobs()
        pending_map = {job["job_id"]: job for job in pending_list}

        # Add pending jobs not already in our list
        for job in pending_list:
            if job["job_id"] not in job_ids_to_query:
                jobs_data.append({
                    "job_name": job["job_name"],
                    "job_id": job["job_id"],
                    "output_file": None,
                    "state": job["state"],
                    "wait_time": job.get("wait_time"),
                })
                job_ids_to_query.add(job["job_id"])
    else:
        pending_map = {}

    # Query sacct for additional info
    if include_sacct_info and job_ids_to_query:
        fields = sacct_fields or DEFAULT_SACCT_FIELDS.copy()
        info_map = get_sacct_info(list(job_ids_to_query), fields=fields)

        for job in jobs_data:
            job_id = job["job_id"]

            if job_id in info_map:
                # Add sacct fields
                for field, value in info_map[job_id].items():
                    if field != "JobID":
                        job[field.lower()] = value

            elif job_id in pending_map:
                # Use squeue info for pending jobs
                job["state"] = pending_map[job_id]["state"]
                if "wait_time" in pending_map[job_id]:
                    job["wait_time"] = pending_map[job_id]["wait_time"]

            else:
                # Mark as unknown
                job["state"] = "UNKNOWN"

    return jobs_data
