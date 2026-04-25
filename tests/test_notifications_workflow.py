"""Tests for notification workflows on the rewritten collection schema."""

from __future__ import annotations

import yaml

from slurmkit.collections import Collection, CollectionManager
from slurmkit.config import get_config
from slurmkit.notifications import NotificationService
from slurmkit.workflows.notifications import run_collection_final_notification, run_job_notification


def _write_config(tmp_path):
    config_path = tmp_path / ".slurmkit" / "config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        yaml.dump(
            {
                "notifications": {
                    "routes": [
                        {
                            "name": "team",
                            "type": "webhook",
                            "url": "https://example.invalid/hook",
                            "events": ["job_failed", "collection_failed", "collection_completed"],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    return config_path


def test_job_notification_skips_success_when_failed_only(tmp_path):
    config_path = _write_config(tmp_path)
    config = get_config(config_path=config_path, project_root=tmp_path, reload=True)
    service = NotificationService(config=config)

    result = run_job_notification(
        service=service,
        job_id="100",
        collection_name=None,
        exit_code=0,
        on="failed",
        routes=None,
        tail_lines=None,
        strict=False,
        dry_run=True,
    )

    assert result.exit_code == 0
    assert "Skipping notification" in result.messages[0]


def test_collection_final_notification_uses_attempts_schema(tmp_path):
    config_path = _write_config(tmp_path)
    config = get_config(config_path=config_path, project_root=tmp_path, reload=True)
    manager = CollectionManager(config=config)
    collection = Collection("exp1")
    collection.add_job("job1", job_id="100", state="FAILED", parameters={"lr": 0.1})
    collection.add_resubmission("job1", job_id="101", submission_group="g1")
    collection.jobs[0]["attempts"][-1]["state"] = "COMPLETED"
    manager.save(collection)
    service = NotificationService(config=config, collection_manager=manager)

    result = run_collection_final_notification(
        service=service,
        job_id="101",
        trigger_exit_code=0,
        collection_name="exp1",
        routes=None,
        strict=False,
        dry_run=True,
        force=True,
        no_refresh=True,
    )

    assert result.exit_code == 0
    assert result.payload["collection"]["name"] == "exp1"
    assert result.payload["collection_report"]["summary"]["counts"]["completed"] == 1
    assert (tmp_path / ".slurmkit" / "locks" / "collections" / "exp1.lock").exists()
    assert not (tmp_path / ".slurmkit" / "collections" / "exp1.yaml.lock").exists()


def test_collection_final_notification_locks_nested_collection_path(tmp_path):
    config_path = _write_config(tmp_path)
    config = get_config(config_path=config_path, project_root=tmp_path, reload=True)
    manager = CollectionManager(config=config)
    collection = Collection("group/sub/run")
    collection.add_job("job1", job_id="101", state="COMPLETED")
    manager.save(collection)
    service = NotificationService(config=config, collection_manager=manager)

    result = run_collection_final_notification(
        service=service,
        job_id="101",
        trigger_exit_code=0,
        collection_name="group/sub/run",
        routes=None,
        strict=False,
        dry_run=True,
        force=True,
        no_refresh=True,
    )

    assert result.exit_code == 0
    assert result.payload["collection"]["name"] == "group/sub/run"
    assert (
        tmp_path / ".slurmkit" / "locks" / "collections" / "group" / "sub" / "run.lock"
    ).exists()
