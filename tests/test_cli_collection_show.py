"""Tests for `slurmkit collection show` CLI wiring."""

from __future__ import annotations

import json
from argparse import Namespace

from slurmkit.cli import commands
from slurmkit.cli.main import create_parser


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


def test_collection_show_parser_new_args():
    """Parser should include new show flags and default latest attempt mode."""
    parser = create_parser()
    args = parser.parse_args(["collection", "show", "exp1"])
    assert args.command == "collection"
    assert args.collection_action == "show"
    assert args.attempt_mode == "latest"
    assert args.submission_group is None
    assert args.show_primary is False
    assert args.show_history is False


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
