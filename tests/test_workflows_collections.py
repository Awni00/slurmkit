"""Tests for collection workflows."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from slurmkit.collections import Collection, CollectionManager
from slurmkit.config import get_config
from slurmkit.workflows.collections import list_collection_summaries
from slurmkit.workflows.collections import show_collection


def test_list_collection_summaries_sorts_by_updated_desc_then_name():
    manager = SimpleNamespace(
        list_collections_with_summary=lambda attempt_mode="latest": [
            {"name": "gamma", "updated_at": "2026-03-20T09:00:00"},
            {"name": "alpha", "updated_at": "2026-03-24T10:00:00"},
            {"name": "beta", "updated_at": "2026-03-24T10:00:00"},
        ]
    )

    rows = list_collection_summaries(manager=manager, attempt_mode="latest")

    assert [row["name"] for row in rows] == ["alpha", "beta", "gamma"]


def test_list_collection_summaries_places_invalid_or_missing_updated_last():
    manager = SimpleNamespace(
        list_collections_with_summary=lambda attempt_mode="latest": [
            {"name": "valid_new", "updated_at": "2026-03-24T10:00:00"},
            {"name": "missing", "updated_at": None},
            {"name": "invalid", "updated_at": "not-a-date"},
            {"name": "valid_old", "updated_at": "2026-03-20T09:00:00"},
        ]
    )

    rows = list_collection_summaries(manager=manager, attempt_mode="latest")

    assert [row["name"] for row in rows] == ["valid_new", "valid_old", "invalid", "missing"]


def test_show_collection_enriches_eta_fields_and_collection_aggregate(monkeypatch, tmp_path):
    config = get_config(project_root=tmp_path, reload=True)
    manager = CollectionManager(config=config)
    collection = Collection("eta_exp")
    collection.add_job("job_pending", job_id="100", state="PENDING")
    collection.add_job("job_running", job_id="101", state="RUNNING")
    manager.save(collection)

    now = datetime.now().replace(microsecond=0)
    pending_start = now + timedelta(hours=1)
    monkeypatch.setattr(
        "slurmkit.workflows.collections.get_active_queue_timing",
        lambda job_ids=None: {
            "100": {
                "job_id": "100",
                "state_raw": "PENDING",
                "estimated_start_at": pending_start.isoformat(timespec="seconds"),
                "time_limit_seconds": 7200,
                "time_left_seconds": None,
            },
            "101": {
                "job_id": "101",
                "state_raw": "RUNNING",
                "estimated_start_at": None,
                "time_limit_seconds": None,
                "time_left_seconds": 1800,
            },
        },
    )

    rendered = show_collection(
        config=config,
        manager=manager,
        name="eta_exp",
        refresh=False,
        state_filter="all",
        json_mode=True,
        attempt_mode="latest",
        include_jobs_table=True,
        include_jobs_in_payload=True,
    )
    payload = rendered.payload
    assert payload is not None
    assert payload["active_jobs"] == 2
    assert payload["estimable_active_jobs"] == 2
    assert payload["estimated_completion_at"] is not None
    assert isinstance(payload["estimated_remaining_seconds"], int)

    by_name = {row["job_name"]: row for row in payload["jobs"]}
    pending = by_name["job_pending"]
    running = by_name["job_running"]
    assert pending["effective_eta_start_at"].startswith(pending_start.isoformat(timespec="seconds"))
    assert pending["effective_eta_completion_at"].startswith(
        (pending_start + timedelta(hours=2)).isoformat(timespec="seconds")
    )
    assert pending["effective_eta_remaining_seconds"] is not None

    assert running["effective_eta_completion_at"] is not None
    assert isinstance(running["effective_eta_remaining_seconds"], int)
    assert 0 <= running["effective_eta_remaining_seconds"] <= 1800


def test_show_collection_collection_eta_unknown_reports_coverage(monkeypatch, tmp_path):
    config = get_config(project_root=tmp_path, reload=True)
    manager = CollectionManager(config=config)
    collection = Collection("eta_unknown")
    collection.add_job("job_pending", job_id="200", state="PENDING")
    manager.save(collection)

    monkeypatch.setattr(
        "slurmkit.workflows.collections.get_active_queue_timing",
        lambda job_ids=None: {
            "200": {
                "job_id": "200",
                "state_raw": "PENDING",
                "estimated_start_at": None,
                "time_limit_seconds": None,
                "time_left_seconds": None,
            }
        },
    )

    rendered = show_collection(
        config=config,
        manager=manager,
        name="eta_unknown",
        refresh=False,
        state_filter="all",
        json_mode=False,
        attempt_mode="latest",
        include_jobs_table=False,
        include_jobs_in_payload=False,
    )

    metadata = dict(rendered.report.metadata)
    assert metadata["Collection Est. Completion"] == "N/A (0/1 estimable active jobs)"
