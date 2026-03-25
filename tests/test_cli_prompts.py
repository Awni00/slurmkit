"""Tests for collection prompt ordering helpers."""

from __future__ import annotations

from types import SimpleNamespace

import yaml

from slurmkit.cli import prompts


def _write_collection(tmp_path, name: str, payload: dict[str, object] | str) -> None:
    path = tmp_path / f"{name}.yaml"
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
        return
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_collection_options_sort_newest_first_and_tie_break_by_name(tmp_path):
    _write_collection(tmp_path, "gamma", {"created_at": "2026-03-23T10:00:00"})
    _write_collection(tmp_path, "beta", {"created_at": "2026-03-24T10:00:00"})
    _write_collection(tmp_path, "alpha", {"created_at": "2026-03-24T10:00:00"})
    manager = SimpleNamespace(
        collections_dir=tmp_path,
        list_collections=lambda: ["gamma", "beta", "alpha"],
    )

    options = prompts._collection_options(manager)

    assert [value for value, _label in options] == ["alpha", "beta", "gamma"]


def test_collection_options_place_missing_or_invalid_created_at_last(tmp_path):
    _write_collection(tmp_path, "dated_new", {"created_at": "2026-03-24T12:00:00"})
    _write_collection(tmp_path, "dated_old", {"created_at": "2026-03-22T12:00:00"})
    _write_collection(tmp_path, "missing", {"name": "missing"})
    _write_collection(tmp_path, "invalid", {"created_at": "not-a-date"})
    _write_collection(tmp_path, "corrupt", "name: [\n")
    manager = SimpleNamespace(
        collections_dir=tmp_path,
        list_collections=lambda: ["missing", "dated_old", "corrupt", "dated_new", "invalid"],
    )

    options = prompts._collection_options(manager)

    assert [value for value, _label in options] == [
        "dated_new",
        "dated_old",
        "corrupt",
        "invalid",
        "missing",
    ]


def test_pick_or_create_collection_keeps_create_sentinel_first(monkeypatch, tmp_path):
    _write_collection(tmp_path, "older", {"created_at": "2026-03-21T12:00:00"})
    _write_collection(tmp_path, "newer", {"created_at": "2026-03-24T12:00:00"})
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
