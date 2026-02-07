"""Tests for `slurmkit resubmit` CLI behavior."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from slurmkit.cli import commands
from slurmkit.cli.main import create_parser
from slurmkit.collections import Collection


class _FakeConfig:
    def __init__(self, jobs_dir: Path):
        self.jobs_dir = jobs_dir

    def get_path(self, _key, _default=None):
        return self.jobs_dir


class _FakeManager:
    def __init__(self, collection: Collection):
        self.collection = collection
        self.saved = False

    def exists(self, _name):
        return True

    def load(self, _name):
        return self.collection

    def save(self, _collection):
        self.saved = True


def test_resubmit_parser_new_arguments():
    """Parser accepts new callback + submission-group options."""
    parser = create_parser()
    args = parser.parse_args(
        [
            "resubmit",
            "--collection",
            "exp1",
            "--submission-group",
            "sg1",
            "--extra-params-file",
            "callbacks.py",
            "--extra-params-function",
            "my_extra",
            "--select-file",
            "callbacks.py",
            "--select-function",
            "my_select",
            "--extra-params",
            "checkpoint=last.pt",
            "--dry-run",
        ]
    )

    assert args.command == "resubmit"
    assert args.collection == "exp1"
    assert args.submission_group == "sg1"
    assert args.extra_params_file == "callbacks.py"
    assert args.extra_params_function == "my_extra"
    assert args.select_file == "callbacks.py"
    assert args.select_function == "my_select"
    assert args.extra_params == "checkpoint=last.pt"
    assert args.dry_run is True


def test_cmd_resubmit_callbacks_and_merge(monkeypatch, tmp_path):
    """Selection and extra-params callbacks should be applied per job."""
    cb_file = tmp_path / "callbacks.py"
    cb_file.write_text(
        "\n".join(
            [
                "def should_resubmit(context):",
                "    if context['job_name'] == 'skip_job':",
                "        return (False, 'manually excluded')",
                "    return True",
                "",
                "def get_extra_params(context):",
                "    return {'source': 'callback', 'override': 'from_callback'}",
            ]
        ),
        encoding="utf-8",
    )

    script_a = tmp_path / "run_a.job"
    script_b = tmp_path / "run_b.job"
    script_a.write_text("#!/bin/bash\necho a\n", encoding="utf-8")
    script_b.write_text("#!/bin/bash\necho b\n", encoding="utf-8")

    collection = Collection("exp1")
    collection.add_job(job_name="run_job", script_path=str(script_a), job_id=None, state="FAILED")
    collection.add_job(job_name="skip_job", script_path=str(script_b), job_id=None, state="FAILED")
    collection.refresh_states = lambda: 0  # type: ignore[method-assign]
    manager = _FakeManager(collection)

    monkeypatch.setattr(commands, "get_configured_config", lambda _args: _FakeConfig(tmp_path))
    monkeypatch.setattr(commands, "CollectionManager", lambda config=None: manager)
    monkeypatch.setattr(commands, "prompt_yes_no", lambda _msg: True)
    monkeypatch.setattr(commands, "submit_job", lambda _path, dry_run=False: (True, "9001", "Submitted batch job 9001"))

    args = Namespace(
        collection="exp1",
        filter="all",
        job_ids=[],
        template=None,
        extra_params="override=from_cli,checkpoint=last.pt",
        extra_params_file=str(cb_file),
        extra_params_function="get_extra_params",
        select_file=str(cb_file),
        select_function="should_resubmit",
        submission_group="group_alpha",
        jobs_dir=None,
        dry_run=False,
        yes=True,
    )

    exit_code = commands.cmd_resubmit(args)

    assert exit_code == 0
    assert manager.saved is True
    run_job = collection.get_job("run_job")
    assert len(run_job["resubmissions"]) == 1
    resub = run_job["resubmissions"][0]
    assert resub["submission_group"] == "group_alpha"
    assert resub["extra_params"]["source"] == "callback"
    assert resub["extra_params"]["override"] == "from_cli"
    assert resub["extra_params"]["checkpoint"] == "last.pt"
    skip_job = collection.get_job("skip_job")
    assert len(skip_job["resubmissions"]) == 0


def test_cmd_resubmit_auto_submission_group_dry_run(monkeypatch, tmp_path, capsys):
    """Missing --submission-group should generate a timestamped group name."""
    script = tmp_path / "run.job"
    script.write_text("#!/bin/bash\necho hi\n", encoding="utf-8")

    collection = Collection("exp1")
    collection.add_job(job_name="run_job", script_path=str(script), job_id=None, state="FAILED")
    collection.refresh_states = lambda: 0  # type: ignore[method-assign]
    manager = _FakeManager(collection)

    monkeypatch.setattr(commands, "get_configured_config", lambda _args: _FakeConfig(tmp_path))
    monkeypatch.setattr(commands, "CollectionManager", lambda config=None: manager)

    args = Namespace(
        collection="exp1",
        filter="all",
        job_ids=[],
        template=None,
        extra_params=None,
        extra_params_file=None,
        extra_params_function="get_extra_params",
        select_file=None,
        select_function="should_resubmit",
        submission_group=None,
        jobs_dir=None,
        dry_run=True,
        yes=True,
    )

    exit_code = commands.cmd_resubmit(args)
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Submission group: resubmit_" in output
    assert len(collection.get_job("run_job")["resubmissions"]) == 0
