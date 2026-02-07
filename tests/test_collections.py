"""Tests for slurmkit.collections module."""

import tempfile
from pathlib import Path

import pytest

from slurmkit.collections import (
    Collection,
    CollectionManager,
    DEFAULT_COLLECTION_NAME,
    LEGACY_SUBMISSION_GROUP,
)


class TestCollection:
    """Tests for Collection class."""

    def test_create_collection(self):
        """Test creating a new collection."""
        collection = Collection("test_collection", description="Test description")
        assert collection.name == "test_collection"
        assert collection.description == "Test description"
        assert len(collection) == 0

    def test_add_job(self):
        """Test adding a job to collection."""
        collection = Collection("test")
        job = collection.add_job(
            job_name="train_model",
            script_path="scripts/train.job",
            parameters={"lr": 0.01},
        )

        assert len(collection) == 1
        assert job["job_name"] == "train_model"
        assert job["parameters"] == {"lr": 0.01}
        assert "git_branch" in job
        assert "git_commit_id" in job

    def test_get_job(self):
        """Test getting a job by name."""
        collection = Collection("test")
        collection.add_job(job_name="job1")
        collection.add_job(job_name="job2")

        job = collection.get_job("job1")
        assert job is not None
        assert job["job_name"] == "job1"

        missing = collection.get_job("job3")
        assert missing is None

    def test_get_job_by_id(self):
        """Test getting a job by SLURM job ID."""
        collection = Collection("test")
        collection.add_job(job_name="job1", job_id="12345")
        collection.add_job(job_name="job2", job_id="12346")

        job = collection.get_job_by_id("12345")
        assert job is not None
        assert job["job_name"] == "job1"

    def test_update_job(self):
        """Test updating a job."""
        collection = Collection("test")
        collection.add_job(job_name="job1", state=None)

        result = collection.update_job("job1", job_id="12345", state="RUNNING")
        assert result is True

        job = collection.get_job("job1")
        assert job["job_id"] == "12345"
        assert job["state"] == "RUNNING"

    def test_remove_job(self):
        """Test removing a job."""
        collection = Collection("test")
        collection.add_job(job_name="job1")
        collection.add_job(job_name="job2")

        assert len(collection) == 2

        result = collection.remove_job("job1")
        assert result is True
        assert len(collection) == 1
        assert collection.get_job("job1") is None

    def test_add_resubmission(self):
        """Test adding a resubmission record."""
        collection = Collection("test")
        collection.add_job(job_name="job1", job_id="12345", state="FAILED")

        result = collection.add_resubmission(
            "job1",
            job_id="12346",
            extra_params={"checkpoint": "last.pt"},
        )
        assert result is True

        job = collection.get_job("job1")
        assert len(job["resubmissions"]) == 1
        assert job["resubmissions"][0]["job_id"] == "12346"
        assert job["resubmissions"][0]["extra_params"]["checkpoint"] == "last.pt"
        assert "git_branch" in job["resubmissions"][0]
        assert "git_commit_id" in job["resubmissions"][0]

    def test_add_resubmission_submission_group(self):
        """Test submission group is persisted on resubmission records."""
        collection = Collection("test")
        collection.add_job(job_name="job1", job_id="12345", state="FAILED")

        collection.add_resubmission(
            "job1",
            job_id="12346",
            submission_group="resubmit_20260207_170000",
        )

        job = collection.get_job("job1")
        assert job["resubmissions"][0]["submission_group"] == "resubmit_20260207_170000"

    def test_filter_jobs_by_state(self):
        """Test filtering jobs by state."""
        collection = Collection("test")
        collection.add_job(job_name="job1", job_id="1", state="COMPLETED")
        collection.add_job(job_name="job2", job_id="2", state="FAILED")
        collection.add_job(job_name="job3", job_id="3", state="RUNNING")

        completed = collection.filter_jobs(state="completed")
        assert len(completed) == 1
        assert completed[0]["job_name"] == "job1"

        failed = collection.filter_jobs(state="failed")
        assert len(failed) == 1
        assert failed[0]["job_name"] == "job2"

    def test_filter_jobs_by_submitted(self):
        """Test filtering jobs by submitted status."""
        collection = Collection("test")
        collection.add_job(job_name="job1", job_id="12345")
        collection.add_job(job_name="job2", job_id=None)

        submitted = collection.filter_jobs(submitted=True)
        assert len(submitted) == 1
        assert submitted[0]["job_name"] == "job1"

        unsubmitted = collection.filter_jobs(submitted=False)
        assert len(unsubmitted) == 1
        assert unsubmitted[0]["job_name"] == "job2"

    def test_get_summary(self):
        """Test getting collection summary."""
        collection = Collection("test")
        collection.add_job(job_name="job1", job_id="1", state="COMPLETED")
        collection.add_job(job_name="job2", job_id="2", state="FAILED")
        collection.add_job(job_name="job3", job_id="3", state="RUNNING")
        collection.add_job(job_name="job4", job_id=None)

        summary = collection.get_summary()
        assert summary["total"] == 4
        assert summary["completed"] == 1
        assert summary["failed"] == 1
        assert summary["running"] == 1
        assert summary["not_submitted"] == 1

    def test_get_effective_jobs_latest(self):
        """Latest mode should expose latest resubmission as effective fields."""
        collection = Collection("test")
        collection.add_job(job_name="job1", job_id="1", state="FAILED")
        collection.add_resubmission("job1", job_id="2")
        collection.get_job("job1")["resubmissions"][-1]["state"] = "COMPLETED"

        effective = collection.get_effective_jobs(attempt_mode="latest")
        assert len(effective) == 1
        row = effective[0]
        assert row["effective_job_id"] == "2"
        assert row["effective_state"] == "completed"
        assert row["effective_is_primary"] is False

    def test_get_effective_jobs_submission_group(self):
        """Submission-group mode should include only jobs in group using group-latest state."""
        collection = Collection("test")
        collection.add_job(job_name="job1", job_id="1", state="FAILED")
        collection.add_job(job_name="job2", job_id="3", state="FAILED")
        collection.add_resubmission("job1", job_id="2", submission_group="g1")
        collection.add_resubmission("job2", job_id="4", submission_group="g2")
        collection.get_job("job1")["resubmissions"][-1]["state"] = "COMPLETED"
        collection.get_job("job2")["resubmissions"][-1]["state"] = "FAILED"

        effective = collection.get_effective_jobs(submission_group="g1")
        assert len(effective) == 1
        assert effective[0]["job_name"] == "job1"
        assert effective[0]["effective_submission_group"] == "g1"
        assert effective[0]["effective_state"] == "completed"

    def test_get_submission_groups_summary(self):
        """Group summary should include counts, timestamps, and legacy bucket."""
        collection = Collection("test")
        collection.add_job(job_name="job1", job_id="1", state="FAILED")
        collection.add_resubmission("job1", job_id="2", submission_group="g1")
        collection.add_resubmission("job1", job_id="3")
        collection.get_job("job1")["resubmissions"][0]["submitted_at"] = "2026-02-07T17:00:00"
        collection.get_job("job1")["resubmissions"][1]["submitted_at"] = "2026-02-07T18:00:00"

        groups = collection.get_submission_groups_summary()
        groups_by_name = {entry["submission_group"]: entry for entry in groups}
        assert groups_by_name["g1"]["slurm_job_count"] == 1
        assert groups_by_name["g1"]["parent_job_count"] == 1
        assert groups_by_name[LEGACY_SUBMISSION_GROUP]["slurm_job_count"] == 1

    def test_to_dict_from_dict(self):
        """Test serialization and deserialization."""
        collection = Collection("test", description="Test description")
        collection.add_job(job_name="job1", parameters={"lr": 0.01})
        collection.meta = {"notifications": {"collection_final": {"last_event": "collection_completed"}}}

        data = collection.to_dict()
        restored = Collection.from_dict(data)

        assert restored.name == collection.name
        assert restored.description == collection.description
        assert len(restored) == len(collection)
        assert restored.meta["notifications"]["collection_final"]["last_event"] == "collection_completed"

    def test_analyze_status_by_params_scalar_values(self):
        """Test state aggregation by scalar parameter values."""
        collection = Collection("test")
        collection.add_job(job_name="a", parameters={"algo": "algo_a"}, state="COMPLETED")
        collection.add_job(job_name="b", parameters={"algo": "algo_a"}, state="FAILED")
        collection.add_job(job_name="c", parameters={"algo": "algo_b"}, state="FAILED")

        analysis = collection.analyze_status_by_params(min_support=1)
        algo_block = next(x for x in analysis["parameters"] if x["param"] == "algo")

        assert [v["value"] for v in algo_block["values"]] == ["algo_b", "algo_a"]
        assert algo_block["values"][0]["counts"]["failed"] == 1
        assert algo_block["values"][0]["rates"]["failure_rate"] == 1.0
        assert algo_block["values"][1]["counts"]["failed"] == 1
        assert algo_block["values"][1]["counts"]["completed"] == 1

    def test_analyze_status_by_params_non_scalar_values(self):
        """Test non-scalar parameter values are grouped using stable JSON strings."""
        collection = Collection("test")
        collection.add_job(
            job_name="a",
            parameters={"config": {"b": 2, "a": 1}},
            state="COMPLETED",
        )
        collection.add_job(
            job_name="b",
            parameters={"config": {"a": 1, "b": 2}},
            state="FAILED",
        )

        analysis = collection.analyze_status_by_params(min_support=1)
        config_block = next(x for x in analysis["parameters"] if x["param"] == "config")

        assert len(config_block["values"]) == 1
        assert config_block["values"][0]["value"] == '{"a": 1, "b": 2}'
        assert config_block["values"][0]["n"] == 2

    def test_analyze_status_by_params_attempt_mode_latest(self):
        """Test latest attempt mode uses most recent resubmission state."""
        collection = Collection("test")
        collection.add_job(job_name="a", parameters={"algo": "x"}, state="FAILED")
        collection.add_resubmission("a", job_id="101")
        collection.get_job("a")["resubmissions"][-1]["state"] = "COMPLETED"

        primary = collection.analyze_status_by_params(
            attempt_mode="primary",
            min_support=1,
        )
        latest = collection.analyze_status_by_params(
            attempt_mode="latest",
            min_support=1,
        )

        primary_value = primary["parameters"][0]["values"][0]
        latest_value = latest["parameters"][0]["values"][0]
        assert primary_value["counts"]["failed"] == 1
        assert latest_value["counts"]["completed"] == 1

    def test_analyze_status_by_params_submission_group_uses_group_latest(self):
        """Submission-group analysis should use latest state within selected group."""
        collection = Collection("test")
        collection.add_job(job_name="a", parameters={"algo": "x"}, state="FAILED")
        collection.add_resubmission("a", job_id="101", submission_group="g1")
        collection.get_job("a")["resubmissions"][-1]["state"] = "COMPLETED"

        analysis = collection.analyze_status_by_params(
            attempt_mode="primary",
            submission_group="g1",
            min_support=1,
        )

        value = analysis["parameters"][0]["values"][0]
        assert value["counts"]["completed"] == 1
        assert analysis["metadata"]["attempt_mode"] == "latest"
        assert analysis["metadata"]["submission_group"] == "g1"

    def test_analyze_status_by_params_filter_and_skipped(self):
        """Test selected parameter filtering and skipped param reporting."""
        collection = Collection("test")
        collection.add_job(job_name="a", parameters={"algo": "x"}, state="COMPLETED")

        analysis = collection.analyze_status_by_params(
            selected_params=["algo", "missing"],
            min_support=1,
        )
        assert [p["param"] for p in analysis["parameters"]] == ["algo"]
        assert analysis["metadata"]["skipped_params"] == ["missing"]

    def test_analyze_status_by_params_low_support_and_top_lists(self):
        """Test low-sample flags and top risky/stable sections."""
        collection = Collection("test")
        collection.add_job(job_name="a", parameters={"algo": "x"}, state="FAILED")
        collection.add_job(job_name="b", parameters={"algo": "x"}, state="FAILED")
        collection.add_job(job_name="c", parameters={"algo": "x"}, state="COMPLETED")
        collection.add_job(job_name="d", parameters={"algo": "y"}, state="COMPLETED")

        analysis = collection.analyze_status_by_params(min_support=2, top_k=2)
        algo_block = next(x for x in analysis["parameters"] if x["param"] == "algo")
        y_row = next(x for x in algo_block["values"] if x["value"] == "y")
        assert y_row["low_sample"] is True

        assert len(analysis["top_risky_values"]) >= 1
        assert analysis["top_risky_values"][0]["param"] == "algo"
        assert len(analysis["top_stable_values"]) >= 1
        assert analysis["top_stable_values"][0]["param"] == "algo"

    def test_analyze_status_by_params_empty_collection(self):
        """Test empty collection analysis output structure."""
        collection = Collection("test")
        analysis = collection.analyze_status_by_params()
        assert analysis["summary"]["total_jobs"] == 0
        assert analysis["parameters"] == []
        assert analysis["top_risky_values"] == []
        assert analysis["top_stable_values"] == []


class TestCollectionManager:
    """Tests for CollectionManager class."""

    def test_create_collection(self):
        """Test creating a collection through manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = CollectionManager(collections_dir=tmpdir)
            collection = manager.create("test", description="Test")

            assert manager.exists("test")
            assert collection.name == "test"

    def test_load_collection(self):
        """Test loading a collection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = CollectionManager(collections_dir=tmpdir)
            manager.create("test", description="Test")

            loaded = manager.load("test")
            assert loaded.name == "test"
            assert loaded.description == "Test"

    def test_load_nonexistent_raises(self):
        """Test loading a nonexistent collection raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = CollectionManager(collections_dir=tmpdir)
            with pytest.raises(FileNotFoundError):
                manager.load("nonexistent")

    def test_save_collection(self):
        """Test saving a collection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = CollectionManager(collections_dir=tmpdir)
            collection = Collection("test")
            collection.add_job(job_name="job1")

            path = manager.save(collection)
            assert path.exists()

            # Reload and verify
            loaded = manager.load("test")
            assert len(loaded) == 1

    def test_delete_collection(self):
        """Test deleting a collection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = CollectionManager(collections_dir=tmpdir)
            manager.create("test")

            assert manager.exists("test")
            manager.delete("test")
            assert not manager.exists("test")

    def test_list_collections(self):
        """Test listing all collections."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = CollectionManager(collections_dir=tmpdir)
            manager.create("test1")
            manager.create("test2")
            manager.create("test3")

            names = manager.list_collections()
            assert sorted(names) == ["test1", "test2", "test3"]

    def test_get_or_create_existing(self):
        """Test get_or_create returns existing collection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = CollectionManager(collections_dir=tmpdir)
            manager.create("test", description="Original")

            collection = manager.get_or_create("test", description="New")
            assert collection.description == "Original"

    def test_get_or_create_new(self):
        """Test get_or_create creates new collection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = CollectionManager(collections_dir=tmpdir)

            collection = manager.get_or_create("test", description="New")
            assert collection.description == "New"
            assert manager.exists("test")

    def test_create_raises_if_exists(self):
        """Test create raises if collection exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = CollectionManager(collections_dir=tmpdir)
            manager.create("test")

            with pytest.raises(FileExistsError):
                manager.create("test")

    def test_create_overwrite(self):
        """Test create with overwrite."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = CollectionManager(collections_dir=tmpdir)
            manager.create("test", description="Original")
            manager.create("test", description="New", overwrite=True)

            collection = manager.load("test")
            assert collection.description == "New"
