"""Tests for slurmkit.collections module."""

import tempfile
from pathlib import Path

import pytest

from slurmkit.collections import (
    Collection,
    CollectionManager,
    DEFAULT_COLLECTION_NAME,
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

    def test_to_dict_from_dict(self):
        """Test serialization and deserialization."""
        collection = Collection("test", description="Test description")
        collection.add_job(job_name="job1", parameters={"lr": 0.01})

        data = collection.to_dict()
        restored = Collection.from_dict(data)

        assert restored.name == collection.name
        assert restored.description == collection.description
        assert len(restored) == len(collection)


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
