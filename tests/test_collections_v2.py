"""Tests for the v2 attempts-based collection schema."""

from __future__ import annotations

import multiprocessing
import os
import stat

import pytest
import yaml

from slurmkit.collections import Collection, CollectionManager


def _save_collection_many_times(collections_dir: str, worker_index: int, rounds: int) -> None:
    manager = CollectionManager(collections_dir=collections_dir)
    for round_index in range(rounds):
        collection = Collection(
            "exp1",
            description=f"worker {worker_index} round {round_index}",
            parameters={"worker": worker_index, "round": round_index},
        )
        for job_index in range(25):
            collection.add_job(
                f"worker_{worker_index}_job_{job_index}",
                script_path=f"jobs/worker_{worker_index}/job_{job_index}.job",
                job_id=f"{worker_index}{round_index:02d}{job_index:02d}",
                state="RUNNING",
                parameters={
                    "worker": worker_index,
                    "round": round_index,
                    "job": job_index,
                },
            )
        manager.save(collection)


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


def test_collection_manager_save_failure_leaves_existing_file_intact(monkeypatch, tmp_path):
    manager = CollectionManager(collections_dir=tmp_path)
    original = Collection("exp1", description="original")
    original.add_job("job1", script_path="jobs/job1.job", parameters={"lr": 0.1})
    path = manager.save(original)
    original_bytes = path.read_bytes()

    replacement = Collection("exp1", description="replacement")
    replacement.add_job("job2", script_path="jobs/job2.job", parameters={"lr": 0.2})

    def fail_after_partial_write(data, stream, **kwargs):
        stream.write("partial: true\n")
        raise RuntimeError("simulated dump failure")

    monkeypatch.setattr("slurmkit.collections.yaml.dump", fail_after_partial_write)

    with pytest.raises(RuntimeError, match="simulated dump failure"):
        manager.save(replacement)

    assert path.read_bytes() == original_bytes
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["description"] == "original"
    assert path.stat().st_size > 0
    assert list(tmp_path.glob(".exp1.yaml.*.tmp")) == []


def test_collection_manager_save_uses_temp_file_and_default_mode(tmp_path):
    manager = CollectionManager(collections_dir=tmp_path)
    collection = Collection("exp1", description="demo")
    collection.add_job("job1", script_path="jobs/job1.job", parameters={"lr": 0.1})

    path = manager.save(collection)

    assert yaml.safe_load(path.read_text(encoding="utf-8"))["description"] == "demo"
    assert stat.S_IMODE(path.stat().st_mode) == 0o644
    assert list(tmp_path.glob(".exp1.yaml.*.tmp")) == []


def test_collection_manager_save_preserves_existing_file_mode(tmp_path):
    manager = CollectionManager(collections_dir=tmp_path)
    collection = Collection("exp1", description="first")
    path = manager.save(collection)
    os.chmod(path, 0o640)

    collection.description = "second"
    manager.save(collection)

    assert yaml.safe_load(path.read_text(encoding="utf-8"))["description"] == "second"
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_collection_manager_save_creates_nested_collection_lock_path(tmp_path):
    manager = CollectionManager(collections_dir=tmp_path / "collections")
    collection = Collection("group/sub/run", description="nested")

    manager.save(collection)

    assert (tmp_path / "locks" / "collections" / "group" / "sub" / "run.lock").exists()


def test_collection_manager_concurrent_saves_leave_parseable_yaml(tmp_path):
    collections_dir = tmp_path / "collections"
    workers = [
        multiprocessing.Process(
            target=_save_collection_many_times,
            args=(str(collections_dir), worker_index, 8),
        )
        for worker_index in range(4)
    ]

    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=30)

    for worker in workers:
        assert worker.exitcode == 0

    path = collections_dir / "exp1.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["name"] == "exp1"
    restored = CollectionManager(collections_dir=collections_dir).load("exp1")
    assert restored.name == "exp1"
    assert len(restored.jobs) == 25


def test_collection_manager_saves_and_loads_nested_collection_ids(tmp_path):
    manager = CollectionManager(collections_dir=tmp_path)
    collection = Collection(
        "experiment/group/run_20260406",
        description="demo",
        generation={"spec_path": "specs/demo.yaml"},
    )
    collection.add_job("job1", script_path="jobs/job1.job", parameters={"lr": 0.1})

    saved_path = manager.save(collection)
    restored = manager.load("experiment/group/run_20260406")

    assert saved_path == tmp_path / "experiment" / "group" / "run_20260406.yaml"
    assert saved_path.exists()
    assert restored.name == "experiment/group/run_20260406"
    assert manager.list_collections() == ["experiment/group/run_20260406"]


def test_collection_manager_delete_prunes_empty_parent_directories(tmp_path):
    manager = CollectionManager(collections_dir=tmp_path)
    collection = Collection("experiment/group/run_20260406")
    collection.add_job("job1", script_path="jobs/job1.job", parameters={"lr": 0.1})
    manager.save(collection)

    assert manager.delete("experiment/group/run_20260406") is True
    assert not (tmp_path / "experiment" / "group" / "run_20260406.yaml").exists()
    assert not (tmp_path / "experiment" / "group").exists()
    assert not (tmp_path / "experiment").exists()


@pytest.mark.parametrize(
    "name",
    [
        "Train Exp 2026",
        "../escape_collection",
        "/absolute/path",
        "exp//run",
        "exp\\run",
        "exp/./run",
        "exp/../run",
        " exp1",
        "exp1 ",
    ],
)
def test_collection_manager_rejects_invalid_collection_ids(name, tmp_path):
    manager = CollectionManager(collections_dir=tmp_path)

    with pytest.raises(ValueError, match="Invalid collection ID"):
        manager.get_collection_path(name)

    assert list(tmp_path.rglob("*")) == []


def test_collection_manager_resolve_job_id_matches_old_attempts(tmp_path):
    manager = CollectionManager(collections_dir=tmp_path)
    collection = Collection("exp1")
    collection.add_job("job1", script_path="jobs/job1.job", job_id="100", state="FAILED")
    collection.add_resubmission("job1", job_id="101", submission_group="g1")
    manager.save(collection)

    primary_resolution = manager.resolve_job_id("100")
    latest_resolution = manager.resolve_job_id("101")

    assert len(primary_resolution.matches) == 1
    assert primary_resolution.matches[0].collection_name == "exp1"
    assert primary_resolution.matches[0].job["job_name"] == "job1"
    assert len(latest_resolution.matches) == 1
    assert latest_resolution.matches[0].job["job_name"] == "job1"


def test_collection_manager_resolve_job_id_can_be_ambiguous(tmp_path):
    manager = CollectionManager(collections_dir=tmp_path)
    first = Collection("exp1")
    first.add_job("job1", script_path="jobs/job1.job", job_id="100", state="FAILED")
    second = Collection("exp2")
    second.add_job("job2", script_path="jobs/job2.job", job_id="100", state="FAILED")
    manager.save(first)
    manager.save(second)

    resolution = manager.resolve_job_id("100")

    assert len(resolution.matches) == 2
    assert sorted(match.collection_name for match in resolution.matches) == ["exp1", "exp2"]


def test_collection_refresh_states_uses_canonical_state_and_persists_raw_state(monkeypatch, tmp_path):
    manager = CollectionManager(collections_dir=tmp_path)
    collection = Collection("exp1")
    collection.add_job("job1", script_path="jobs/job1.job", job_id="100", state="PREEMPTED")
    manager.save(collection)

    monkeypatch.setattr(
        "slurmkit.collections.get_canonical_sacct_states",
        lambda *_args, **_kwargs: {
            "100": {
                "state": "COMPLETED",
                "start": "2026-04-05T10:00:00",
                "end": "2026-04-05T10:05:00",
                "raw_state": {
                    "rows": {
                        "parent": {
                            "job_id": "100",
                            "state_raw": "PREEMPTED",
                            "state_base": "PREEMPTED",
                            "exit_code": "0:0",
                            "derived_exit_code": "0:0",
                            "reason": "preempted",
                            "start": "2026-04-05T10:00:00",
                            "end": "2026-04-05T10:05:00",
                        },
                        "batch": {
                            "job_id": "100.batch",
                            "state_raw": "COMPLETED",
                            "state_base": "COMPLETED",
                            "exit_code": "0:0",
                            "derived_exit_code": "0:0",
                            "reason": "",
                            "start": "2026-04-05T10:00:00",
                            "end": "2026-04-05T10:05:00",
                        },
                        "extern": None,
                        "others": [],
                    },
                    "all_rows": [],
                    "resolution": {
                        "canonical_state": "COMPLETED",
                        "rule": "batch_completed_exit_zero",
                        "used_row": "batch",
                        "live_rows": [],
                        "queue_rows": [],
                    },
                },
            }
        },
    )

    updated = collection.refresh_states()
    assert updated == 1
    attempt = collection.jobs[0]["attempts"][0]
    assert attempt["state"] == "COMPLETED"
    assert attempt["raw_state"]["resolution"]["canonical_state"] == "COMPLETED"
    assert attempt["started_at"] == "2026-04-05T10:00:00"
    assert attempt["completed_at"] == "2026-04-05T10:05:00"

    manager.save(collection)
    restored = manager.load("exp1")
    restored_attempt = restored.jobs[0]["attempts"][0]
    assert restored_attempt["raw_state"]["resolution"]["rule"] == "batch_completed_exit_zero"


def test_collection_refresh_states_keeps_attempt_when_no_canonical_row(monkeypatch):
    collection = Collection("exp1")
    collection.add_job("job1", script_path="jobs/job1.job", job_id="100", state="FAILED")

    monkeypatch.setattr("slurmkit.collections.get_canonical_sacct_states", lambda *_args, **_kwargs: {})

    updated = collection.refresh_states()
    assert updated == 0
    attempt = collection.jobs[0]["attempts"][0]
    assert attempt["state"] == "FAILED"
    assert attempt["raw_state"] is None
