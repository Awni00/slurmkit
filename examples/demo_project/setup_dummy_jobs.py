#!/usr/bin/env python3
"""Create deterministic dummy jobs/collections for demo and local testing."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path
import random
import sys
from typing import Any, List

# Allow running directly from source checkout without prior installation.
REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

try:
    from slurmkit.collections import Collection, CollectionManager, normalize_collection_id
    from slurmkit.config import Config
except ModuleNotFoundError as exc:  # pragma: no cover - startup guard
    missing = exc.name or "dependency"
    print(f"Missing dependency/module: {missing}")
    print("Install project dependencies first, for example:")
    print("  pip install -e ../..")
    raise SystemExit(1)


def _to_iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _write_demo_log(path: Path, lines: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_demo_script(path: Path, *, job_name: str, command: str, logs_dir: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "#!/bin/bash",
                f"#SBATCH --job-name={job_name}",
                f"#SBATCH --output={logs_dir.as_posix()}/{job_name}.%j.out",
                "",
                "set -e",
                command,
                "",
            ]
        ),
        encoding="utf-8",
    )


def _validate_prefix_segment(raw_prefix: str) -> str:
    if not raw_prefix:
        return ""
    normalized = normalize_collection_id(raw_prefix)
    if "/" in normalized:
        raise ValueError("--prefix must be a single safe segment, not a hierarchical path.")
    return normalized


def _collection_id(prefix: str, *segments: str) -> str:
    return normalize_collection_id("/".join(part for part in (prefix, *segments) if part))


def _job_dirs(project_root: Path, *segments: str) -> tuple[Path, Path]:
    root = project_root / ".jobs" / "dummy_demo" / Path(*segments)
    return root / "job_scripts", root / "logs"


def _set_generation(
    collection: Collection,
    *,
    spec_path: str,
    scripts_dir: Path,
    logs_dir: Path,
) -> None:
    collection.generation = {
        "spec_path": spec_path,
        "scripts_dir": str(scripts_dir),
        "logs_dir": str(logs_dir),
    }


def _create_collection(
    manager: CollectionManager,
    *,
    name: str,
    description: str,
    parameters: dict[str, Any],
) -> Collection:
    return manager.create(
        name,
        description=description,
        parameters=parameters,
        overwrite=True,
    )


def _terminal_timestamps(
    *,
    now: datetime,
    runtime_seconds: int,
    completed_ago_seconds: int,
    submit_delay_seconds: int,
) -> tuple[str, str, str]:
    completed_dt = now - timedelta(seconds=completed_ago_seconds)
    started_dt = completed_dt - timedelta(seconds=runtime_seconds)
    submitted_dt = started_dt - timedelta(seconds=submit_delay_seconds)
    return _to_iso(submitted_dt), _to_iso(started_dt), _to_iso(completed_dt)


def _running_timestamps(
    *,
    now: datetime,
    running_seconds: int,
    submit_delay_seconds: int,
) -> tuple[str, str]:
    started_dt = now - timedelta(seconds=running_seconds)
    submitted_dt = started_dt - timedelta(seconds=submit_delay_seconds)
    return _to_iso(submitted_dt), _to_iso(started_dt)


def _add_demo_job(
    collection: Collection,
    *,
    job_name: str,
    job_id: str,
    state: str,
    scripts_dir: Path,
    logs_dir: Path,
    command: str,
    log_lines: List[str],
    parameters: dict[str, Any],
    submitted_at: str,
    started_at: str | None,
    completed_at: str | None,
) -> None:
    script_path = scripts_dir / f"{job_name}.job"
    output_path = None if state == "PENDING" else logs_dir / f"{job_name}.{job_id}.out"

    _write_demo_script(
        script_path,
        job_name=job_name,
        command=command,
        logs_dir=logs_dir,
    )
    if output_path is not None:
        _write_demo_log(output_path, log_lines)

    collection.add_job(
        job_name=job_name,
        job_id=job_id,
        state=state,
        script_path=script_path,
        output_path=output_path,
        parameters=parameters,
        submitted_at=submitted_at,
        started_at=started_at,
        completed_at=completed_at,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create dummy collections and logs for local slurmkit demos.",
    )
    parser.add_argument(
        "--prefix",
        default="",
        help="Optional top-level collection namespace segment.",
    )
    parser.add_argument(
        "--include-non-terminal",
        action="store_true",
        help="Deprecated no-op kept for compatibility; mixed collection always includes running/pending jobs.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        prefix = _validate_prefix_segment(args.prefix)
    except ValueError as exc:
        parser.error(str(exc))

    project_root = Path.cwd()
    config = Config(project_root=project_root)
    manager = CollectionManager(config=config)

    base_id = 990000
    sweep_spec_rel = "experiments/hyperparameter_sweep/slurmkit/job_spec.yaml"
    model_spec_rel = "experiments/model_comparison/slurmkit/job_spec.yaml"
    mixed_collection_name = _collection_id(prefix, "fixtures", "mixed_30")
    terminal_failed_collection_name = _collection_id(prefix, "notifications", "terminal_failed")
    terminal_completed_collection_name = _collection_id(prefix, "notifications", "terminal_completed")
    in_progress_collection_name = _collection_id(prefix, "notifications", "in_progress")

    mixed_scripts_dir, mixed_logs_dir = _job_dirs(project_root, "fixtures", "mixed_30")
    mixed_collection = _create_collection(
        manager,
        name=mixed_collection_name,
        description="Deterministic mixed-state collection with 30 jobs",
        parameters={"source": "setup_dummy_jobs.py", "demo_type": "mixed_fixture"},
    )

    # Fixed distribution for deterministic mixed-state demos.
    # 12 completed, 8 failed, 6 running, 4 pending = 30 total jobs.
    state_plan = (
        ["COMPLETED"] * 12
        + ["FAILED"] * 8
        + ["RUNNING"] * 6
        + ["PENDING"] * 4
    )
    rng = random.Random(42)
    algorithms = ("algo_a", "algo_b", "algo_c")
    datasets = ("small", "medium", "large")

    now = datetime.now()
    for index, state in enumerate(state_plan, start=1):
        state_suffix = state.lower()
        job_name = f"{prefix}_{state_suffix}_{index:02d}"
        job_id = str(base_id + index)

        if state == "FAILED":
            command = (
                'python -c "import sys; print(\'failing dummy run\'); '
                "print('OOM while allocating tensor'); sys.exit(1)\""
            )
            log_lines = [
                "train step 118",
                "train step 119",
                "OOM while allocating tensor",
                "job exiting with status 1",
            ]
        elif state == "COMPLETED":
            command = 'python -c "print(\'completed dummy run\')"'
            log_lines = [
                "train step 199",
                "validation complete",
                "job finished successfully",
            ]
        elif state == "RUNNING":
            command = 'python -c "print(\'running dummy run\')"'
            log_lines = [
                "train step 42",
                "still running...",
            ]
        else:
            command = 'python -c "print(\'pending dummy run\')"'
            log_lines = []

        if state in {"COMPLETED", "FAILED"}:
            runtime_seconds = rng.randint(45, 3 * 3600)
            completed_ago_seconds = rng.randint(60, 6 * 3600)
            submitted_at, started_at, completed_at = _terminal_timestamps(
                now=now,
                runtime_seconds=runtime_seconds,
                completed_ago_seconds=completed_ago_seconds,
                submit_delay_seconds=rng.randint(10, 180),
            )
        elif state == "RUNNING":
            running_seconds = rng.randint(60, 4 * 3600)
            submitted_at, started_at = _running_timestamps(
                now=now,
                running_seconds=running_seconds,
                submit_delay_seconds=rng.randint(10, 120),
            )
            completed_at = None
        else:
            submitted_at = _to_iso(now - timedelta(seconds=rng.randint(30, 3 * 3600)))
            started_at = None
            completed_at = None

        _add_demo_job(
            mixed_collection,
            job_name=job_name,
            job_id=job_id,
            state=state,
            scripts_dir=mixed_scripts_dir,
            logs_dir=mixed_logs_dir,
            command=command,
            log_lines=log_lines,
            parameters={
                "algorithm": algorithms[(index - 1) % len(algorithms)],
                "dataset": datasets[(index - 1) % len(datasets)],
                "trial": index,
            },
            submitted_at=submitted_at,
            started_at=started_at,
            completed_at=completed_at,
        )

    _set_generation(
        mixed_collection,
        spec_path=sweep_spec_rel,
        scripts_dir=mixed_scripts_dir,
        logs_dir=mixed_logs_dir,
    )
    manager.save(mixed_collection)

    failed_scripts_dir, failed_logs_dir = _job_dirs(project_root, "notifications", "terminal_failed")
    terminal_failed_collection = _create_collection(
        manager,
        name=terminal_failed_collection_name,
        description="Terminal failed collection linked to the hyperparameter sweep spec override demo",
        parameters={"source": "setup_dummy_jobs.py", "demo_type": "terminal_failed"},
    )
    submitted_at, started_at, completed_at = _terminal_timestamps(
        now=now,
        runtime_seconds=420,
        completed_ago_seconds=900,
        submit_delay_seconds=30,
    )
    _add_demo_job(
        terminal_failed_collection,
        job_name=f"{prefix}_terminal_failed_main",
        job_id="991002",
        state="FAILED",
        scripts_dir=failed_scripts_dir,
        logs_dir=failed_logs_dir,
        command=(
            'python -c "import sys; print(\'terminal failed demo\'); '
            "print('OOM while allocating tensor'); sys.exit(1)\""
        ),
        log_lines=[
            "train step 88",
            "train step 89",
            "OOM while allocating tensor",
            "job exiting with status 1",
        ],
        parameters={"algorithm": "algo_a", "dataset": "large", "profile": "failed_demo"},
        submitted_at=submitted_at,
        started_at=started_at,
        completed_at=completed_at,
    )
    _set_generation(
        terminal_failed_collection,
        spec_path=sweep_spec_rel,
        scripts_dir=failed_scripts_dir,
        logs_dir=failed_logs_dir,
    )
    manager.save(terminal_failed_collection)

    completed_scripts_dir, completed_logs_dir = _job_dirs(project_root, "notifications", "terminal_completed")
    terminal_completed_collection = _create_collection(
        manager,
        name=terminal_completed_collection_name,
        description="Terminal completed collection linked to the model comparison global fallback demo",
        parameters={"source": "setup_dummy_jobs.py", "demo_type": "terminal_completed"},
    )
    submitted_at, started_at, completed_at = _terminal_timestamps(
        now=now,
        runtime_seconds=180,
        completed_ago_seconds=600,
        submit_delay_seconds=20,
    )
    _add_demo_job(
        terminal_completed_collection,
        job_name=f"{prefix}_terminal_completed_main",
        job_id="992011",
        state="COMPLETED",
        scripts_dir=completed_scripts_dir,
        logs_dir=completed_logs_dir,
        command='python -c "print(\'terminal completed demo\')"',
        log_lines=[
            "evaluate batch 9",
            "metrics aggregated",
            "job finished successfully",
        ],
        parameters={"algorithm": "baseline", "dataset": "tiny", "profile": "completed_demo"},
        submitted_at=submitted_at,
        started_at=started_at,
        completed_at=completed_at,
    )
    _set_generation(
        terminal_completed_collection,
        spec_path=model_spec_rel,
        scripts_dir=completed_scripts_dir,
        logs_dir=completed_logs_dir,
    )
    manager.save(terminal_completed_collection)

    in_progress_scripts_dir, in_progress_logs_dir = _job_dirs(project_root, "notifications", "in_progress")
    in_progress_collection = _create_collection(
        manager,
        name=in_progress_collection_name,
        description="Non-terminal collection for collection-final skip demos",
        parameters={"source": "setup_dummy_jobs.py", "demo_type": "in_progress"},
    )
    submitted_at, started_at = _running_timestamps(
        now=now,
        running_seconds=900,
        submit_delay_seconds=45,
    )
    _add_demo_job(
        in_progress_collection,
        job_name=f"{prefix}_in_progress_running",
        job_id="993020",
        state="RUNNING",
        scripts_dir=in_progress_scripts_dir,
        logs_dir=in_progress_logs_dir,
        command='python -c "print(\'non-terminal running demo\')"',
        log_lines=[
            "train step 17",
            "still running...",
        ],
        parameters={"algorithm": "algo_b", "dataset": "medium", "profile": "running_demo"},
        submitted_at=submitted_at,
        started_at=started_at,
        completed_at=None,
    )
    pending_submitted_at = _to_iso(now - timedelta(seconds=300))
    _add_demo_job(
        in_progress_collection,
        job_name=f"{prefix}_in_progress_pending",
        job_id="993021",
        state="PENDING",
        scripts_dir=in_progress_scripts_dir,
        logs_dir=in_progress_logs_dir,
        command='python -c "print(\'non-terminal pending demo\')"',
        log_lines=[],
        parameters={"algorithm": "algo_c", "dataset": "small", "profile": "pending_demo"},
        submitted_at=pending_submitted_at,
        started_at=None,
        completed_at=None,
    )
    _set_generation(
        in_progress_collection,
        spec_path=sweep_spec_rel,
        scripts_dir=in_progress_scripts_dir,
        logs_dir=in_progress_logs_dir,
    )
    manager.save(in_progress_collection)

    failed_job_id = str(base_id + 13)
    print("Prepared dummy collections:")
    print(f"  - {mixed_collection_name}")
    print(f"  - {terminal_failed_collection_name}")
    print(f"  - {terminal_completed_collection_name}")
    print(f"  - {in_progress_collection_name}")
    print("")
    print("Example commands:")
    print("  slurmkit collections list")
    print(f"  slurmkit status {mixed_collection_name}")
    print(f"  slurmkit collections show {mixed_collection_name}")
    print(f"  slurmkit collections analyze {mixed_collection_name}")
    print(
        "  slurmkit notify job "
        f"--collection {mixed_collection_name} --job-id {failed_job_id} --exit-code 1 --dry-run"
    )
    print(
        "  slurmkit notify job "
        f"--collection {terminal_failed_collection_name} --job-id 991002 --exit-code 1 --dry-run"
    )
    print(
        "  slurmkit notify job "
        f"--collection {terminal_completed_collection_name} --job-id 992011 --exit-code 0 --on always --dry-run"
    )
    print(
        "  slurmkit notify collection-final "
        f"--collection {in_progress_collection_name} --job-id 993020 --no-refresh --dry-run"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
