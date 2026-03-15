"""Tests for interactive generate defaults."""

from __future__ import annotations

from datetime import datetime
from importlib import import_module
from pathlib import Path

from slurmkit.cli import prompts as prompt_module

cli_module = import_module("slurmkit.cli.app")


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 3, 15)


class _FakeManager:
    def list_collections(self):
        return ["existing-a", "existing-b"]


def test_default_collection_name_for_spec_prefers_spec_name(monkeypatch):
    monkeypatch.setattr(cli_module, "datetime", _FixedDatetime)

    default_name = cli_module._default_collection_name_for_spec(
        Path("experiments/train_job.yaml"),
        {"name": "my_experiment"},
    )

    assert default_name == "my_experiment_20260315"


def test_pick_or_create_collection_does_not_prefill_create_sentinel(monkeypatch):
    captured = {}

    def _fake_prompt_choice(_message, _options, *, default_value=None, fuzzy=False):
        captured["default_value"] = default_value
        captured["fuzzy"] = fuzzy
        return prompt_module._CREATE_NEW_SENTINEL

    monkeypatch.setattr(prompt_module, "prompt_choice", _fake_prompt_choice)
    monkeypatch.setattr(prompt_module, "prompt_text", lambda _message, *, default="": default)

    selected = prompt_module.pick_or_create_collection(
        state=None,
        manager=_FakeManager(),
        default_name="my_experiment_20260315",
        title="Select or create a collection",
    )

    assert captured == {"default_value": None, "fuzzy": True}
    assert selected == "my_experiment_20260315"
