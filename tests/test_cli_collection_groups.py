"""Tests for `slurmkit collection groups` CLI behavior."""

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
    def get_submission_groups_summary(self):
        return [
            {
                "submission_group": "g1",
                "slurm_job_count": 3,
                "parent_job_count": 2,
                "first_submitted_at": "2026-02-07T10:00:00",
                "last_submitted_at": "2026-02-07T11:00:00",
            }
        ]


class _FakeManager:
    def __init__(self, collection):
        self.collection = collection

    def exists(self, _name):
        return True

    def load(self, _name):
        return self.collection


def test_collection_groups_cli_args(monkeypatch):
    """CLI should map collections groups arguments."""
    captured = {}

    monkeypatch.setattr(
        cli_module,
        "_collection_groups_impl",
        lambda _ctx, *, name, format_name: captured.update({"name": name, "format_name": format_name}) or 0,
    )

    result = runner.invoke(cli_app, ["collections", "groups", "exp1", "--format", "json"])
    assert result.exit_code == 0
    assert captured == {"name": "exp1", "format_name": "json"}


def test_cmd_collection_groups_json(monkeypatch, capsys):
    """JSON output should render group summary payload."""
    fake_manager = _FakeManager(_FakeCollection())
    monkeypatch.setattr(commands, "get_configured_config", lambda _args: object())
    monkeypatch.setattr(commands, "CollectionManager", lambda config=None: fake_manager)

    args = Namespace(name="exp1", format="json")
    exit_code = commands.cmd_collection_groups(args)
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert exit_code == 0
    assert payload[0]["submission_group"] == "g1"
    assert payload[0]["slurm_job_count"] == 3
