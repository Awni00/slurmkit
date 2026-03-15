"""Tests for `slurmkit collection show` CLI wiring."""

from __future__ import annotations

import json
from argparse import Namespace
from importlib import import_module

from slurmkit.cli import commands
from slurmkit.cli.app import app as cli_app
from typer.testing import CliRunner

runner = CliRunner()
cli_module = import_module("slurmkit.cli.app")


class _FakeCollection:
    def __init__(self):
        self.name = "exp1"
        self.description = "demo"
        self.created_at = "2026-02-07T10:00:00"
        self.updated_at = "2026-02-07T11:00:00"
        self.cluster = "cluster-a"
        self.parameters = {}
        self.refreshed = False

    def refresh_states(self):
        self.refreshed = True
        return 0

    def get_effective_jobs(self, attempt_mode="latest", submission_group=None, state=None):
        rows = [
            {
                "job_name": "job_a",
                "job": {"job_name": "job_a", "job_id": "100", "state": "FAILED", "resubmissions": []},
                "effective_job_id": "101",
                "effective_state_raw": "COMPLETED",
                "effective_state": "completed",
                "effective_hostname": "cluster-a",
                "effective_attempt_label": "resubmission #1",
                "effective_attempt_index": 1,
                "effective_submission_group": "g1",
                "resubmissions_count": 1,
                "primary_job_id": "100",
                "primary_state_raw": "FAILED",
                "attempt_history": ["100(FAILED)", "101(COMPLETED)"],
            }
        ]
        if state and state != "completed":
            return []
        return rows

    def get_effective_summary(self, attempt_mode="latest", submission_group=None):
        return {
            "total": 1,
            "completed": 1,
            "failed": 0,
            "running": 0,
            "pending": 0,
            "unknown": 0,
            "not_submitted": 0,
        }

    def to_dict(self):
        return {
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "cluster": self.cluster,
            "parameters": self.parameters,
            "jobs": [],
            "meta": {},
        }


class _FakeManager:
    def __init__(self, collection):
        self.collection = collection
        self.saved = False

    def exists(self, _name):
        return True

    def load(self, _name):
        return self.collection

    def save(self, _collection):
        self.saved = True


def test_collection_show_cli_new_args(monkeypatch):
    """CLI should include new show flags and default latest attempt mode."""
    captured = {}

    def _fake_impl(
        _ctx,
        *,
        name,
        format_name,
        state_filter,
        attempt_mode,
        submission_group,
        show_primary,
        show_history,
        no_refresh,
    ):
        captured.update(
            {
                "name": name,
                "format_name": format_name,
                "state_filter": state_filter,
                "attempt_mode": attempt_mode,
                "submission_group": submission_group,
                "show_primary": show_primary,
                "show_history": show_history,
                "no_refresh": no_refresh,
            }
        )
        return 0

    monkeypatch.setattr(cli_module, "_collection_show_impl", _fake_impl)

    result = runner.invoke(
        cli_app,
        ["collections", "show", "exp1", "--show-primary", "--show-history"],
    )
    assert result.exit_code == 0
    assert captured["name"] == "exp1"
    assert captured["attempt_mode"] == "latest"
    assert captured["submission_group"] is None
    assert captured["show_primary"] is True
    assert captured["show_history"] is True


def test_cmd_collection_show_json_includes_effective_fields(monkeypatch, capsys):
    """JSON output should include effective metadata and summary."""
    fake_collection = _FakeCollection()
    fake_manager = _FakeManager(fake_collection)

    monkeypatch.setattr(commands, "get_configured_config", lambda _args: object())
    monkeypatch.setattr(commands, "CollectionManager", lambda config=None: fake_manager)

    args = Namespace(
        name="exp1",
        format="json",
        state="all",
        attempt_mode="latest",
        submission_group="g1",
        show_primary=False,
        show_history=True,
        no_refresh=True,
    )

    exit_code = commands.cmd_collection_show(args)
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["effective_attempt_mode"] == "latest"
    assert payload["effective_submission_group"] == "g1"
    assert payload["effective_summary"]["completed"] == 1
    assert payload["jobs"][0]["effective_job_id"] == "101"
    assert payload["jobs"][0]["effective_state"] == "COMPLETED"
    assert payload["jobs"][0]["effective_attempt_history"] == ["100(FAILED)", "101(COMPLETED)"]
