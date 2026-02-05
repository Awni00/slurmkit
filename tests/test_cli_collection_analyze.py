"""Tests for `slurmkit collection analyze` CLI wiring and handler behavior."""

import json
from argparse import Namespace

from slurmkit.cli.main import create_parser
from slurmkit.cli import commands


class _FakeCollection:
    def __init__(self):
        self.refreshed = False

    def refresh_states(self):
        self.refreshed = True
        return 0

    def analyze_status_by_params(
        self,
        attempt_mode="primary",
        min_support=3,
        selected_params=None,
        top_k=10,
    ):
        return {
            "summary": {
                "total_jobs": 1,
                "counts": {
                    "completed": 1,
                    "failed": 0,
                    "running": 0,
                    "pending": 0,
                    "unknown": 0,
                },
                "rates": {
                    "completed": 1.0,
                    "failed": 0.0,
                    "running": 0.0,
                    "pending": 0.0,
                    "unknown": 0.0,
                },
            },
            "parameters": [],
            "top_risky_values": [],
            "top_stable_values": [],
            "metadata": {
                "min_support": min_support,
                "attempt_mode": attempt_mode,
                "selected_params": selected_params or [],
                "skipped_params": [],
            },
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


def test_collection_analyze_parser_args():
    """Parser accepts and maps collection analyze arguments."""
    parser = create_parser()
    args = parser.parse_args(
        [
            "collection",
            "analyze",
            "my_collection",
            "--format",
            "json",
            "--no-refresh",
            "--min-support",
            "5",
            "--param",
            "algo",
            "--param",
            "lr",
            "--attempt-mode",
            "latest",
            "--top-k",
            "7",
        ]
    )
    assert args.command == "collection"
    assert args.collection_action == "analyze"
    assert args.name == "my_collection"
    assert args.format == "json"
    assert args.no_refresh is True
    assert args.min_support == 5
    assert args.param == ["algo", "lr"]
    assert args.attempt_mode == "latest"
    assert args.top_k == 7


def test_cmd_collection_analyze_json_no_refresh(monkeypatch, capsys):
    """JSON mode returns analysis payload and does not refresh when requested."""
    fake_collection = _FakeCollection()
    fake_manager = _FakeManager(fake_collection)

    monkeypatch.setattr(commands, "get_configured_config", lambda _args: object())
    monkeypatch.setattr(commands, "CollectionManager", lambda config=None: fake_manager)

    args = Namespace(
        name="my_collection",
        format="json",
        no_refresh=True,
        min_support=3,
        param=None,
        attempt_mode="primary",
        top_k=10,
    )
    exit_code = commands.cmd_collection_analyze(args)
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert exit_code == 0
    assert fake_collection.refreshed is False
    assert fake_manager.saved is False
    assert payload["summary"]["total_jobs"] == 1


def test_cmd_collection_analyze_rejects_invalid_min_support(monkeypatch, capsys):
    """Invalid min support is rejected before collection operations."""
    monkeypatch.setattr(commands, "get_configured_config", lambda _args: object())
    monkeypatch.setattr(commands, "CollectionManager", lambda config=None: object())

    args = Namespace(
        name="my_collection",
        format="table",
        no_refresh=True,
        min_support=0,
        param=None,
        attempt_mode="primary",
        top_k=10,
    )
    exit_code = commands.cmd_collection_analyze(args)
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "--min-support" in output
