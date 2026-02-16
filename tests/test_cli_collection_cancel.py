"""Tests for `slurmkit collection cancel` CLI behavior."""

from __future__ import annotations

from argparse import Namespace

from slurmkit.collections import Collection
from slurmkit.cli import commands
from slurmkit.cli.main import create_parser


class _FakeManager:
    def __init__(self, collection: Collection):
        self.collection = collection
        self.save_count = 0

    def exists(self, _name: str) -> bool:
        return True

    def load(self, _name: str) -> Collection:
        return self.collection

    def save(self, _collection: Collection) -> None:
        self.save_count += 1


def _build_collection() -> Collection:
    collection = Collection("exp1")
    collection.add_job(job_name="job_a", job_id="100", state="RUNNING")
    collection.add_job(job_name="job_b", job_id="200", state="COMPLETED")
    collection.add_resubmission("job_b", job_id="201")
    collection.get_job("job_b")["resubmissions"][-1]["state"] = "PENDING"
    return collection


def test_collection_cancel_parser_args():
    """Parser should map collection cancel arguments."""
    parser = create_parser()
    args = parser.parse_args(["collection", "cancel", "exp1", "--dry-run", "--no-refresh", "-y"])
    assert args.command == "collection"
    assert args.collection_action == "cancel"
    assert args.name == "exp1"
    assert args.dry_run is True
    assert args.no_refresh is True
    assert args.yes is True


def test_cmd_collection_cancel_dry_run(monkeypatch, capsys):
    """Dry-run mode should list active attempts and avoid calling scancel."""
    collection = _build_collection()
    manager = _FakeManager(collection)

    monkeypatch.setattr(commands, "get_configured_config", lambda _args: object())
    monkeypatch.setattr(commands, "CollectionManager", lambda config=None: manager)
    monkeypatch.setattr(
        commands,
        "cancel_job",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("cancel_job should not be called")),
    )

    args = Namespace(name="exp1", dry_run=True, no_refresh=True, yes=False)
    exit_code = commands.cmd_collection_cancel(args)
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Will cancel 2 job(s)" in output
    assert "job_a [primary] (ID: 100, State: RUNNING)" in output
    assert "job_b [resubmission #1] (ID: 201, State: PENDING)" in output
    assert "[DRY RUN] No jobs were cancelled." in output
    assert manager.save_count == 0


def test_cmd_collection_cancel_partial_failure_updates_successful_entries(monkeypatch, capsys):
    """Partial cancellation failures should return 1 and persist successful CANCELLED states."""
    collection = _build_collection()
    manager = _FakeManager(collection)
    called_ids = []

    def _fake_cancel_job(job_id: str, dry_run: bool = False):
        called_ids.append(job_id)
        if job_id == "100":
            return True, "ok"
        return False, "permission denied"

    monkeypatch.setattr(commands, "get_configured_config", lambda _args: object())
    monkeypatch.setattr(commands, "CollectionManager", lambda config=None: manager)
    monkeypatch.setattr(commands, "cancel_job", _fake_cancel_job)

    args = Namespace(name="exp1", dry_run=False, no_refresh=True, yes=True)
    exit_code = commands.cmd_collection_cancel(args)
    output = capsys.readouterr()

    assert exit_code == 1
    assert called_ids == ["100", "201"]
    assert collection.get_job("job_a")["state"] == "CANCELLED"
    assert collection.get_job("job_b")["resubmissions"][-1]["state"] == "PENDING"
    assert "Cancelled 1/2 job(s)." in output.out
    assert "Error cancelling 201" in output.err
    assert manager.save_count == 1
