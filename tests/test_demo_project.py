from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from slurmkit.collections import CollectionManager
from slurmkit.config import Config


REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_PROJECT_DIR = REPO_ROOT / "examples" / "demo_project"
SETUP_DUMMY_JOBS = DEMO_PROJECT_DIR / "setup_dummy_jobs.py"
QUICKSTART = DEMO_PROJECT_DIR / "quickstart.sh"


def test_setup_dummy_jobs_creates_hierarchical_demo_collections(tmp_path):
    demo_root = tmp_path / "demo_project"
    shutil.copytree(DEMO_PROJECT_DIR, demo_root)

    subprocess.run(
        [sys.executable, str(SETUP_DUMMY_JOBS), "--prefix", "demo", "--include-non-terminal"],
        cwd=demo_root,
        check=True,
        capture_output=True,
        text=True,
    )

    manager = CollectionManager(config=Config(project_root=demo_root))
    assert manager.list_collections() == [
        "demo/fixtures/mixed_30",
        "demo/notifications/in_progress",
        "demo/notifications/terminal_completed",
        "demo/notifications/terminal_failed",
    ]

    assert (demo_root / ".slurmkit" / "collections" / "demo" / "fixtures" / "mixed_30.yaml").exists()
    assert (demo_root / ".slurmkit" / "collections" / "demo" / "notifications" / "terminal_failed.yaml").exists()
    assert (demo_root / ".slurmkit" / "collections" / "demo" / "notifications" / "terminal_completed.yaml").exists()
    assert (demo_root / ".slurmkit" / "collections" / "demo" / "notifications" / "in_progress.yaml").exists()

    failed = manager.load("demo/notifications/terminal_failed")
    completed = manager.load("demo/notifications/terminal_completed")

    assert failed.generation["spec_path"] == "experiments/hyperparameter_sweep/slurmkit/job_spec.yaml"
    assert completed.generation["spec_path"] == "experiments/model_comparison/slurmkit/job_spec.yaml"


def test_demo_quickstart_uses_hierarchical_collection_ids():
    content = QUICKSTART.read_text(encoding="utf-8")

    assert 'DUMMY_COLLECTION_NAME="demo/fixtures/mixed_30"' in content
    assert 'NOTIFY_FAILED_COLLECTION="demo/notifications/terminal_failed"' in content
    assert 'NOTIFY_COMPLETED_COLLECTION="demo/notifications/terminal_completed"' in content
    assert 'NOTIFY_IN_PROGRESS_COLLECTION="demo/notifications/in_progress"' in content
    assert 'COLLECTION="demo/generated/hyperparameter_sweep"' in content
    assert 'COLLECTION="demo/generated/model_comparison"' in content
