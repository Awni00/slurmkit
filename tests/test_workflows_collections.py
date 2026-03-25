"""Tests for collection workflows."""

from __future__ import annotations

from types import SimpleNamespace

from slurmkit.workflows.collections import list_collection_summaries


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
