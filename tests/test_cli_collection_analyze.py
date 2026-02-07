"""Tests for `slurmkit collection analyze` CLI wiring and handler behavior."""

import json
from argparse import Namespace

from slurmkit.cli.main import create_parser
from slurmkit.cli import commands


class _FakeCollection:
    def __init__(self):
        self.refreshed = False
        self.name = "my_collection"

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


class _FakeCollectionWithAnalysis(_FakeCollection):
    def __init__(self, analysis_payload):
        super().__init__()
        self.analysis_payload = analysis_payload

    def analyze_status_by_params(
        self,
        attempt_mode="primary",
        min_support=3,
        selected_params=None,
        top_k=10,
    ):
        return self.analysis_payload


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


def _analysis_payload_mixed_params():
    return {
        "summary": {
            "total_jobs": 4,
            "counts": {
                "completed": 2,
                "failed": 2,
                "running": 0,
                "pending": 0,
                "unknown": 0,
            },
            "rates": {
                "completed": 0.5,
                "failed": 0.5,
                "running": 0.0,
                "pending": 0.0,
                "unknown": 0.0,
            },
        },
        "parameters": [
            {
                "param": "algo",
                "values": [
                    {
                        "value": "a",
                        "n": 2,
                        "counts": {
                            "completed": 0,
                            "failed": 2,
                            "running": 0,
                            "pending": 0,
                            "unknown": 0,
                        },
                        "rates": {"failure_rate": 1.0, "completion_rate": 0.0},
                        "low_sample": False,
                    },
                    {
                        "value": "b",
                        "n": 2,
                        "counts": {
                            "completed": 2,
                            "failed": 0,
                            "running": 0,
                            "pending": 0,
                            "unknown": 0,
                        },
                        "rates": {"failure_rate": 0.0, "completion_rate": 1.0},
                        "low_sample": False,
                    },
                ],
            },
            {
                "param": "batch",
                "values": [
                    {
                        "value": "32",
                        "n": 4,
                        "counts": {
                            "completed": 2,
                            "failed": 2,
                            "running": 0,
                            "pending": 0,
                            "unknown": 0,
                        },
                        "rates": {"failure_rate": 0.5, "completion_rate": 0.5},
                        "low_sample": False,
                    }
                ],
            },
        ],
        "top_risky_values": [
            {
                "param": "algo",
                "value": "a",
                "n": 2,
                "rates": {"failure_rate": 1.0, "completion_rate": 0.0},
                "counts": {"failed": 2, "completed": 0},
            },
            {
                "param": "batch",
                "value": "32",
                "n": 4,
                "rates": {"failure_rate": 0.5, "completion_rate": 0.5},
                "counts": {"failed": 2, "completed": 2},
            },
        ],
        "top_stable_values": [
            {
                "param": "algo",
                "value": "b",
                "n": 2,
                "rates": {"failure_rate": 0.0, "completion_rate": 1.0},
                "counts": {"failed": 0, "completed": 2},
            },
            {
                "param": "batch",
                "value": "32",
                "n": 4,
                "rates": {"failure_rate": 0.5, "completion_rate": 0.5},
                "counts": {"failed": 2, "completed": 2},
            },
        ],
        "metadata": {
            "min_support": 1,
            "attempt_mode": "primary",
            "selected_params": [],
            "skipped_params": [],
        },
    }


def _analysis_payload_all_single_value():
    return {
        "summary": {
            "total_jobs": 2,
            "counts": {
                "completed": 1,
                "failed": 1,
                "running": 0,
                "pending": 0,
                "unknown": 0,
            },
            "rates": {
                "completed": 0.5,
                "failed": 0.5,
                "running": 0.0,
                "pending": 0.0,
                "unknown": 0.0,
            },
        },
        "parameters": [
            {
                "param": "algo",
                "values": [
                    {
                        "value": "only_one",
                        "n": 2,
                        "counts": {
                            "completed": 1,
                            "failed": 1,
                            "running": 0,
                            "pending": 0,
                            "unknown": 0,
                        },
                        "rates": {"failure_rate": 0.5, "completion_rate": 0.5},
                        "low_sample": False,
                    }
                ],
            }
        ],
        "top_risky_values": [
            {
                "param": "algo",
                "value": "only_one",
                "n": 2,
                "rates": {"failure_rate": 0.5, "completion_rate": 0.5},
                "counts": {"failed": 1, "completed": 1},
            }
        ],
        "top_stable_values": [
            {
                "param": "algo",
                "value": "only_one",
                "n": 2,
                "rates": {"failure_rate": 0.5, "completion_rate": 0.5},
                "counts": {"failed": 1, "completed": 1},
            }
        ],
        "metadata": {
            "min_support": 1,
            "attempt_mode": "primary",
            "selected_params": ["algo", "missing"],
            "skipped_params": ["missing"],
        },
    }


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


def test_cmd_collection_analyze_table_filters_single_value_params(monkeypatch, capsys):
    """Table mode only displays parameter breakdowns for params with 2+ distinct values."""
    fake_collection = _FakeCollectionWithAnalysis(_analysis_payload_mixed_params())
    fake_manager = _FakeManager(fake_collection)

    monkeypatch.setattr(commands, "get_configured_config", lambda _args: object())
    monkeypatch.setattr(commands, "CollectionManager", lambda config=None: fake_manager)

    args = Namespace(
        name="my_collection",
        format="table",
        no_refresh=True,
        min_support=1,
        param=None,
        attempt_mode="primary",
        top_k=10,
    )
    exit_code = commands.cmd_collection_analyze(args)
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Parameter: algo" in output
    assert "Parameter: batch" not in output
    assert "Top risky values:" in output
    assert "Top stable values:" in output
    assert "batch" not in output


def test_cmd_collection_analyze_table_all_single_value_params(monkeypatch, capsys):
    """Table mode prints a clear message when all analyzable params are single-valued."""
    fake_collection = _FakeCollectionWithAnalysis(_analysis_payload_all_single_value())
    fake_manager = _FakeManager(fake_collection)

    monkeypatch.setattr(commands, "get_configured_config", lambda _args: object())
    monkeypatch.setattr(commands, "CollectionManager", lambda config=None: fake_manager)

    args = Namespace(
        name="my_collection",
        format="table",
        no_refresh=True,
        min_support=1,
        param=["algo", "missing"],
        attempt_mode="primary",
        top_k=10,
    )
    exit_code = commands.cmd_collection_analyze(args)
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "all analyzed parameters have only one distinct value" in output
    assert "Skipped requested params: missing" in output
    assert "Parameter:" not in output
    assert "Top risky values:" not in output


def test_cmd_collection_analyze_json_keeps_single_value_params(monkeypatch, capsys):
    """JSON mode keeps single-value parameter blocks unchanged."""
    fake_collection = _FakeCollectionWithAnalysis(_analysis_payload_mixed_params())
    fake_manager = _FakeManager(fake_collection)

    monkeypatch.setattr(commands, "get_configured_config", lambda _args: object())
    monkeypatch.setattr(commands, "CollectionManager", lambda config=None: fake_manager)

    args = Namespace(
        name="my_collection",
        format="json",
        no_refresh=True,
        min_support=1,
        param=None,
        attempt_mode="primary",
        top_k=10,
    )
    exit_code = commands.cmd_collection_analyze(args)
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert exit_code == 0
    params = {block["param"]: block for block in payload["parameters"]}
    assert "batch" in params
    assert len(params["batch"]["values"]) == 1


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
