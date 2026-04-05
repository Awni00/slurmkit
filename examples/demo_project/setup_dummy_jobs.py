#!/usr/bin/env python3
"""Create deterministic dummy jobs/collections for demo and local testing."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path
import random
import sys
from typing import List

# Allow running directly from source checkout without prior installation.
REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

try:
    from slurmkit.collections import CollectionManager
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


def _write_demo_script(path: Path, *, job_name: str, command: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "#!/bin/bash",
                f"#SBATCH --job-name={job_name}",
                f"#SBATCH --output=.jobs/dummy_demo/logs/{job_name}.%j.out",
                "",
                "set -e",
                command,
                "",
            ]
        ),
        encoding="utf-8",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create dummy collections and logs for local slurmkit demos.",
    )
    parser.add_argument(
        "--prefix",
        default="demo",
        help="Collection name prefix (default: demo).",
    )
    parser.add_argument(
        "--include-non-terminal",
        action="store_true",
        help="Deprecated no-op kept for compatibility; mixed collection always includes running/pending jobs.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    project_root = Path.cwd()
    config = Config(project_root=project_root)
    manager = CollectionManager(config=config)

    base_id = 990000
    mixed_collection_name = f"{args.prefix}_mixed_30"
    sweep_spec_rel = "experiments/hyperparameter_sweep/slurmkit/job_spec.yaml"

    demo_logs_dir = project_root / ".jobs" / "dummy_demo" / "logs"
    demo_scripts_dir = project_root / ".jobs" / "dummy_demo" / "job_scripts"
    collection = manager.create(
        mixed_collection_name,
        description="Deterministic mixed-state collection with 30 jobs",
        parameters={"source": "setup_dummy_jobs.py"},
        overwrite=True,
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

    for index, state in enumerate(state_plan, start=1):
        state_suffix = state.lower()
        job_name = f"{args.prefix}_{state_suffix}_{index:02d}"
        job_id = str(base_id + index)
        script_path = demo_scripts_dir / f"{job_name}.job"
        output_path = (
            None
            if state == "PENDING"
            else demo_logs_dir / f"{job_name}.{job_id}.out"
        )

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

        _write_demo_script(
            script_path,
            job_name=job_name,
            command=command,
        )
        if output_path is not None:
            _write_demo_log(output_path, log_lines)

        now = datetime.now()
        if state in {"COMPLETED", "FAILED"}:
            runtime_seconds = rng.randint(45, 3 * 3600)
            completed_ago_seconds = rng.randint(60, 6 * 3600)
            completed_dt = now - timedelta(seconds=completed_ago_seconds)
            started_dt = completed_dt - timedelta(seconds=runtime_seconds)
            submitted_dt = started_dt - timedelta(seconds=rng.randint(10, 180))
            submitted_at = _to_iso(submitted_dt)
            started_at = _to_iso(started_dt)
            completed_at = _to_iso(completed_dt)
        elif state == "RUNNING":
            running_seconds = rng.randint(60, 4 * 3600)
            started_dt = now - timedelta(seconds=running_seconds)
            submitted_dt = started_dt - timedelta(seconds=rng.randint(10, 120))
            submitted_at = _to_iso(submitted_dt)
            started_at = _to_iso(started_dt)
            completed_at = None
        else:
            submitted_at = _to_iso(now - timedelta(seconds=rng.randint(30, 3 * 3600)))
            started_at = None
            completed_at = None

        collection.add_job(
            job_name=job_name,
            job_id=job_id,
            state=state,
            script_path=script_path,
            output_path=output_path,
            parameters={
                "algorithm": algorithms[(index - 1) % len(algorithms)],
                "dataset": datasets[(index - 1) % len(datasets)],
                "trial": index,
            },
            submitted_at=submitted_at,
            started_at=started_at,
            completed_at=completed_at,
        )

    collection.generation = {
        "spec_path": sweep_spec_rel,
        "scripts_dir": str(demo_scripts_dir),
        "logs_dir": str(demo_logs_dir),
    }
    manager.save(collection)

    failed_job_id = str(base_id + 13)
    completed_job_id = str(base_id + 1)
    running_job_id = str(base_id + 21)

    print("Prepared dummy collections:")
    print(f"  - {mixed_collection_name}")
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
        f"--collection {mixed_collection_name} --job-id {completed_job_id} --exit-code 0 --on always --dry-run"
    )
    print(
        "  slurmkit notify collection-final "
        f"--collection {mixed_collection_name} --job-id {running_job_id} --no-refresh --dry-run"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
