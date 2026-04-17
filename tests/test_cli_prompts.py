"""Tests for collection prompt ordering helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import yaml

from slurmkit.cli import prompts


def _write_collection(tmp_path, name: str, payload: dict[str, object] | str) -> None:
    path = tmp_path / f"{name}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
        return
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_collection_options_sort_newest_first_and_tie_break_by_name(tmp_path):
    _write_collection(tmp_path, "gamma", {"updated_at": "2026-03-23T10:00:00"})
    _write_collection(tmp_path, "beta", {"updated_at": "2026-03-24T10:00:00"})
    _write_collection(tmp_path, "alpha", {"updated_at": "2026-03-24T10:00:00"})
    manager = SimpleNamespace(
        collections_dir=tmp_path,
        list_collections=lambda: ["gamma", "beta", "alpha"],
    )

    options = prompts._collection_options(
        manager,
        now=datetime(2026, 3, 24, 12, 0, tzinfo=timezone.utc),
    )

    assert [value for value, _label in options] == ["alpha", "beta", "gamma"]
    assert [label for _value, label in options] == [
        "alpha (2h ago)",
        "beta (2h ago)",
        "gamma (1d ago)",
    ]


def test_collection_options_place_missing_or_invalid_updated_at_last(tmp_path):
    _write_collection(tmp_path, "dated_new", {"updated_at": "2026-03-24T12:00:00"})
    _write_collection(tmp_path, "dated_old", {"updated_at": "2026-03-22T12:00:00"})
    _write_collection(tmp_path, "missing", {"name": "missing"})
    _write_collection(tmp_path, "invalid", {"updated_at": "not-a-date"})
    _write_collection(tmp_path, "corrupt", "name: [\n")
    manager = SimpleNamespace(
        collections_dir=tmp_path,
        list_collections=lambda: ["missing", "dated_old", "corrupt", "dated_new", "invalid"],
    )

    options = prompts._collection_options(
        manager,
        now=datetime(2026, 3, 24, 12, 0, tzinfo=timezone.utc),
    )

    assert [value for value, _label in options] == [
        "dated_new",
        "dated_old",
        "corrupt",
        "invalid",
        "missing",
    ]
    assert [label for _value, label in options] == [
        "dated_new (0m ago)",
        "dated_old (2d ago)",
        "corrupt (unknown)",
        "invalid (unknown)",
        "missing (unknown)",
    ]


def test_collection_options_clamp_future_timestamps_to_zero_minutes(tmp_path):
    _write_collection(tmp_path, "future", {"updated_at": "2026-03-24T12:05:00"})
    manager = SimpleNamespace(
        collections_dir=tmp_path,
        list_collections=lambda: ["future"],
    )

    options = prompts._collection_options(
        manager,
        now=datetime(2026, 3, 24, 12, 0, tzinfo=timezone.utc),
    )

    assert options == [("future", "future (0m ago)")]


def test_pick_or_create_collection_keeps_create_sentinel_first(monkeypatch, tmp_path):
    _write_collection(tmp_path, "older", {"updated_at": "2026-03-21T12:00:00"})
    _write_collection(tmp_path, "newer", {"updated_at": "2026-03-24T12:00:00"})
    manager = SimpleNamespace(
        collections_dir=tmp_path,
        list_collections=lambda: ["older", "newer"],
    )
    captured: dict[str, list[tuple[str, str]]] = {}

    def _fake_prompt_choice(_message, options, **_kwargs):
        captured["options"] = options
        return "newer"

    monkeypatch.setattr(prompts, "prompt_choice", _fake_prompt_choice)

    selected = prompts.pick_or_create_collection(
        state=None,
        manager=manager,
        default_name="my_default_collection",
    )

    assert selected == "newer"
    assert captured["options"][0][0] == prompts._CREATE_NEW_SENTINEL
    assert [value for value, _label in captured["options"][1:]] == ["newer", "older"]


def test_read_updated_at_timestamp_fast_path_skips_full_parse(monkeypatch, tmp_path):
    _write_collection(tmp_path, "fast", {"updated_at": "2026-03-24T12:00:00"})
    manager = SimpleNamespace(collections_dir=tmp_path)

    def _unexpected_full_parse(_path):
        raise AssertionError("full parse should not be called for fast-path metadata")

    monkeypatch.setattr(prompts, "_read_updated_at_timestamp_full", _unexpected_full_parse)

    timestamp = prompts._read_updated_at_timestamp(manager, "fast")

    assert timestamp == prompts._parse_created_at("2026-03-24T12:00:00")


def test_read_updated_at_timestamp_falls_back_when_jobs_section_seen(monkeypatch, tmp_path):
    _write_collection(
        tmp_path,
        "reordered",
        "name: reordered\njobs: []\nupdated_at: 2026-03-24T12:00:00\n",
    )
    manager = SimpleNamespace(collections_dir=tmp_path)
    original = prompts._read_updated_at_timestamp_full
    seen: list[str] = []

    def _spy_full_parse(path):
        seen.append(path.name)
        return original(path)

    monkeypatch.setattr(prompts, "_read_updated_at_timestamp_full", _spy_full_parse)

    timestamp = prompts._read_updated_at_timestamp(manager, "reordered")

    assert seen == ["reordered.yaml"]
    assert timestamp == prompts._parse_created_at("2026-03-24T12:00:00")


def test_read_updated_at_timestamp_falls_back_when_scan_limit_exceeded(monkeypatch, tmp_path):
    _write_collection(
        tmp_path,
        "limited",
        "name: limited\ndescription: x\nupdated_at: 2026-03-24T12:00:00\n",
    )
    manager = SimpleNamespace(collections_dir=tmp_path)
    original = prompts._read_updated_at_timestamp_full
    seen: list[str] = []

    def _spy_full_parse(path):
        seen.append(path.name)
        return original(path)

    monkeypatch.setattr(prompts, "_HEADER_SCAN_MAX_LINES", 2)
    monkeypatch.setattr(prompts, "_read_updated_at_timestamp_full", _spy_full_parse)

    timestamp = prompts._read_updated_at_timestamp(manager, "limited")

    assert seen == ["limited.yaml"]
    assert timestamp == prompts._parse_created_at("2026-03-24T12:00:00")


def test_read_updated_at_timestamp_handles_non_utf8_without_crashing(tmp_path):
    path = tmp_path / "binary.yaml"
    path.write_bytes(b"\xff\xfe\x00\x81")
    manager = SimpleNamespace(collections_dir=tmp_path)

    timestamp = prompts._read_updated_at_timestamp(manager, "binary")

    assert timestamp is None
