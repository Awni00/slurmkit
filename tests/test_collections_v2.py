"""Tests for the v2 attempts-based collection schema."""

from __future__ import annotations

from slurmkit.collections import Collection, CollectionManager


def test_collection_add_job_and_resubmission_uses_attempts(tmp_path):
    collection = Collection("exp1")
    collection.add_job("job1", script_path="jobs/job1.job", job_id="100", state="FAILED", parameters={"lr": 0.1})
    collection.add_resubmission("job1", job_id="101", submission_group="g1", extra_params={"checkpoint": "last.pt"})

    job = collection.get_job("job1")
    assert len(job["attempts"]) == 2
    assert job["attempts"][0]["kind"] == "primary"
    assert job["attempts"][1]["kind"] == "resubmission"
    assert job["attempts"][1]["extra_params"]["checkpoint"] == "last.pt"


def test_collection_effective_jobs_latest_uses_last_attempt():
    collection = Collection("exp1")
    collection.add_job("job1", script_path="jobs/job1.job", job_id="100", state="FAILED", parameters={"lr": 0.1})
    collection.add_resubmission("job1", job_id="101", submission_group="g1")
    collection.get_job("job1")["attempts"][-1]["state"] = "COMPLETED"

    rows = collection.get_effective_jobs(attempt_mode="latest")

    assert rows[0]["effective_job_id"] == "101"
    assert rows[0]["effective_state"] == "completed"
    assert rows[0]["effective_submission_group"] == "g1"


def test_collection_manager_saves_and_loads_v2_schema(tmp_path):
    manager = CollectionManager(collections_dir=tmp_path)
    collection = Collection("exp1", description="demo", generation={"spec_path": "specs/demo.yaml"})
    collection.add_job("job1", script_path="jobs/job1.job", parameters={"lr": 0.1})
    manager.save(collection)

    restored = manager.load("exp1")

    assert restored.to_dict()["version"] == 2
    assert restored.generation["spec_path"] == "specs/demo.yaml"
    assert restored.jobs[0]["attempts"][0]["script_path"] == "jobs/job1.job"

