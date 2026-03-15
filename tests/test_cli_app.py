"""Tests for the rewritten Typer CLI surface."""

from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from slurmkit.cli.app import app as cli_app


runner = CliRunner()


def test_root_no_args_prints_help_when_not_interactive():
    result = runner.invoke(cli_app, [])
    assert result.exit_code == 0
    assert "Usage:" in result.stdout


def test_root_no_args_opens_picker_when_prompting_enabled(monkeypatch):
    from importlib import import_module

    cli_module = import_module("slurmkit.cli.app")

    monkeypatch.setattr(cli_module, "can_prompt", lambda _state: True)
    monkeypatch.setattr(cli_module, "choose_command", lambda _sections: None)

    result = runner.invoke(cli_app, [])

    assert result.exit_code == 0
    assert "Canceled." in result.stdout


def test_structured_output_disables_prompt_fallback(tmp_path):
    config_path = tmp_path / ".slurm-kit" / "config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(yaml.dump({"jobs_dir": "jobs/"}), encoding="utf-8")

    result = runner.invoke(cli_app, ["--config", str(config_path), "collections", "show", "--json"])

    assert result.exit_code != 0
    assert "Missing collection argument." in (result.stderr or result.stdout)


def test_removed_jobs_namespace_is_not_registered():
    result = runner.invoke(cli_app, ["jobs"])
    assert result.exit_code != 0
    assert "No such command" in (result.stderr or result.stdout)


def test_migrate_command_runs(tmp_path):
    root = tmp_path
    config_path = root / ".slurm-kit" / "config.yaml"
    collections_dir = root / ".job-collections"
    config_path.parent.mkdir(parents=True)
    collections_dir.mkdir(parents=True)
    config_path.write_text("jobs_dir: jobs/\n", encoding="utf-8")
    (collections_dir / "old.yaml").write_text(
        yaml.dump(
            {
                "name": "old",
                "jobs": [
                    {
                        "job_name": "job1",
                        "job_id": "1",
                        "state": "FAILED",
                        "parameters": {"lr": 0.1},
                        "resubmissions": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(cli_app, ["--config", str(config_path), "migrate"], catch_exceptions=False)

    assert result.exit_code == 0
    assert "Collections migrated: 1" in result.stdout
