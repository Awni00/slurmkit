"""Tests for explicit local-state migration."""

from __future__ import annotations

from pathlib import Path

import yaml

from slurmkit.workflows.migration import run_migration


def test_run_migration_converts_old_collection_and_creates_backup(tmp_path):
    project_root = tmp_path
    config_path = project_root / ".slurm-kit" / "config.yaml"
    collections_dir = project_root / ".job-collections"
    config_path.parent.mkdir(parents=True)
    collections_dir.mkdir(parents=True)
    config_path.write_text("jobs_dir: jobs/\n", encoding="utf-8")
    old_collection_path = collections_dir / "exp1.yaml"
    old_collection_path.write_text(
        yaml.dump(
            {
                "name": "exp1",
                "description": "demo",
                "meta": {"generation": {"spec_path": "specs/exp1.yaml"}},
                "jobs": [
                    {
                        "job_name": "job1",
                        "job_id": "100",
                        "state": "FAILED",
                        "parameters": {"lr": 0.1},
                        "resubmissions": [{"job_id": "101", "state": "COMPLETED", "submission_group": "g1"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = run_migration(project_root=project_root, config_path=config_path, collections_dir=collections_dir)

    migrated = yaml.safe_load(old_collection_path.read_text(encoding="utf-8"))
    assert result.migrated_collections == 1
    assert migrated["version"] == 2
    assert migrated["generation"]["spec_path"] == "specs/exp1.yaml"
    assert len(migrated["jobs"][0]["attempts"]) == 2
    assert result.backup_dir.exists()


def test_run_migration_is_idempotent_for_v2_collection(tmp_path):
    project_root = tmp_path
    config_path = project_root / ".slurm-kit" / "config.yaml"
    collections_dir = project_root / ".job-collections"
    config_path.parent.mkdir(parents=True)
    collections_dir.mkdir(parents=True)
    config_path.write_text("jobs_dir: jobs/\n", encoding="utf-8")
    collection_path = collections_dir / "exp1.yaml"
    collection_path.write_text(
        yaml.dump(
            {
                "version": 2,
                "name": "exp1",
                "jobs": [{"job_name": "job1", "parameters": {}, "attempts": [{"kind": "primary"}]}],
            }
        ),
        encoding="utf-8",
    )

    result = run_migration(project_root=project_root, config_path=config_path, collections_dir=collections_dir)

    assert result.migrated_collections == 0
    assert result.skipped_collections == 1

