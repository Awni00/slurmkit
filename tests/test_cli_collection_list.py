"""Tests for `slurmkit collection list` CLI wiring."""

from __future__ import annotations

from argparse import Namespace

from slurmkit.cli import commands
from slurmkit.cli.main import create_parser


class _FakeManager:
    def __init__(self):
        self.last_attempt_mode = None

    def list_collections_with_summary(self, attempt_mode="primary"):
        self.last_attempt_mode = attempt_mode
        return [
            {
                "name": "exp1",
                "description": "demo",
                "total": 1,
                "completed": 1,
                "failed": 0,
                "pending": 0,
                "running": 0,
            }
        ]


def test_collection_list_parser_attempt_mode_default_latest():
    """Parser should default collection list attempt mode to latest."""
    parser = create_parser()
    args = parser.parse_args(["collection", "list"])
    assert args.command == "collection"
    assert args.collection_action == "list"
    assert args.attempt_mode == "latest"


def test_collection_list_parser_attempt_mode_primary():
    """Parser should accept explicit primary attempt mode for list."""
    parser = create_parser()
    args = parser.parse_args(["collection", "list", "--attempt-mode", "primary"])
    assert args.attempt_mode == "primary"


def test_cmd_collection_list_passes_attempt_mode(monkeypatch, capsys):
    """List command should pass attempt mode through to manager summary API."""
    fake_manager = _FakeManager()

    monkeypatch.setattr(commands, "get_configured_config", lambda _args: object())
    monkeypatch.setattr(commands, "CollectionManager", lambda config=None: fake_manager)

    args = Namespace(attempt_mode="latest")
    exit_code = commands.cmd_collection_list(args)
    output = capsys.readouterr().out

    assert exit_code == 0
    assert fake_manager.last_attempt_mode == "latest"
    assert "Found 1 collection(s):" in output
