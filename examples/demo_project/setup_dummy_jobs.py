#!/usr/bin/env python3
"""Create deterministic dummy jobs/collections for demo and local testing."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
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


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _write_demo_log(path: Path, lines: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
        help="Also create a collection with running/pending jobs.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    project_root = Path.cwd()
    config = Config(project_root=project_root)
    manager = CollectionManager(config=config)

    base_id = "990"
    failed_collection_name = f"{args.prefix}_terminal_failed"
    completed_collection_name = f"{args.prefix}_terminal_completed"
    in_progress_collection_name = f"{args.prefix}_in_progress"

    demo_logs_dir = project_root / "jobs" / "dummy_demo" / "logs"
    failed_log = demo_logs_dir / f"{args.prefix}_failed.{base_id}002.out"
    complete_log = demo_logs_dir / f"{args.prefix}_complete.{base_id}001.out"
    complete2_log = demo_logs_dir / f"{args.prefix}_complete2.{base_id}011.out"
    running_log = demo_logs_dir / f"{args.prefix}_running.{base_id}020.out"

    _write_demo_log(
        failed_log,
        [
            "train step 118",
            "train step 119",
            "OOM while allocating tensor",
            "job exiting with status 1",
        ],
    )
    _write_demo_log(
        complete_log,
        [
            "train step 199",
            "validation complete",
            "job finished successfully",
        ],
    )
    _write_demo_log(
        complete2_log,
        [
            "train step 149",
            "evaluation complete",
            "job finished successfully",
        ],
    )
    _write_demo_log(
        running_log,
        [
            "train step 42",
            "still running...",
        ],
    )

    failed_collection = manager.create(
        failed_collection_name,
        description="Dummy collection with terminal failed outcome",
        parameters={"source": "setup_dummy_jobs.py"},
        overwrite=True,
    )
    failed_collection.add_job(
        job_name=f"{args.prefix}_complete",
        job_id=f"{base_id}001",
        state="COMPLETED",
        output_path=complete_log,
        parameters={"algorithm": "algo_a", "dataset": "small"},
        submitted_at=_now_iso(),
        started_at=_now_iso(),
        completed_at=_now_iso(),
    )
    failed_collection.add_job(
        job_name=f"{args.prefix}_failed",
        job_id=f"{base_id}002",
        state="FAILED",
        output_path=failed_log,
        parameters={"algorithm": "algo_b", "dataset": "large"},
        submitted_at=_now_iso(),
        started_at=_now_iso(),
        completed_at=_now_iso(),
    )
    manager.save(failed_collection)

    completed_collection = manager.create(
        completed_collection_name,
        description="Dummy collection with terminal completed outcome",
        parameters={"source": "setup_dummy_jobs.py"},
        overwrite=True,
    )
    completed_collection.add_job(
        job_name=f"{args.prefix}_complete_a",
        job_id=f"{base_id}010",
        state="COMPLETED",
        output_path=complete_log,
        parameters={"algorithm": "algo_a", "dataset": "small"},
        submitted_at=_now_iso(),
        started_at=_now_iso(),
        completed_at=_now_iso(),
    )
    completed_collection.add_job(
        job_name=f"{args.prefix}_complete_b",
        job_id=f"{base_id}011",
        state="COMPLETED",
        output_path=complete2_log,
        parameters={"algorithm": "algo_b", "dataset": "small"},
        submitted_at=_now_iso(),
        started_at=_now_iso(),
        completed_at=_now_iso(),
    )
    manager.save(completed_collection)

    created = [failed_collection_name, completed_collection_name]
    if args.include_non_terminal:
        in_progress_collection = manager.create(
            in_progress_collection_name,
            description="Dummy collection with non-terminal running/pending jobs",
            parameters={"source": "setup_dummy_jobs.py"},
            overwrite=True,
        )
        in_progress_collection.add_job(
            job_name=f"{args.prefix}_running",
            job_id=f"{base_id}020",
            state="RUNNING",
            output_path=running_log,
            parameters={"algorithm": "algo_a", "dataset": "medium"},
            submitted_at=_now_iso(),
            started_at=_now_iso(),
        )
        in_progress_collection.add_job(
            job_name=f"{args.prefix}_pending",
            job_id=f"{base_id}021",
            state="PENDING",
            parameters={"algorithm": "algo_c", "dataset": "large"},
            submitted_at=_now_iso(),
        )
        manager.save(in_progress_collection)
        created.append(in_progress_collection_name)

    print("Prepared dummy collections:")
    for name in created:
        print(f"  - {name}")
    print("")
    print("Example commands:")
    print(f"  slurmkit collection list")
    print(f"  slurmkit collection show {failed_collection_name}")
    print(f"  slurmkit collection analyze {failed_collection_name} --attempt-mode latest")
    print(
        "  slurmkit notify collection-final "
        f"--collection {failed_collection_name} --job-id {base_id}002 --no-refresh --dry-run"
    )
    print(
        "  slurmkit notify collection-final "
        f"--collection {completed_collection_name} --job-id {base_id}011 --no-refresh --dry-run"
    )
    if args.include_non_terminal:
        print(
            "  slurmkit notify collection-final "
            f"--collection {in_progress_collection_name} --job-id {base_id}020 --no-refresh --dry-run"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
