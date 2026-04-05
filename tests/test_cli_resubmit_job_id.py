"""CLI tests for `slurmkit resubmit --job-id`."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from slurmkit.cli.app import app as cli_app
from slurmkit.collections import Collection, CollectionManager
from slurmkit.config import get_config


runner = CliRunner()


def _write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / ".slurmkit" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("jobs_dir: .jobs/\n", encoding="utf-8")
    return config_path


def _manager_from_config(config_path: Path) -> CollectionManager:
    config = get_config(
        config_path=config_path,
        project_root=config_path.parent.parent,
        reload=True,
    )
    return CollectionManager(config=config)


def _add_collection_with_job(
    *,
    manager: CollectionManager,
    project_root: Path,
    name: str,
    job_name: str,
    job_id: str,
    state: str = "FAILED",
) -> None:
    script_path = project_root / f"{name}_{job_name}.job"
    script_path.write_text("#!/bin/bash\n", encoding="utf-8")
    collection = Collection(name)
    collection.add_job(job_name, script_path=script_path, job_id=job_id, state=state, parameters={"x": 1})
    manager.save(collection)


def test_resubmit_job_id_succeeds_for_unique_match(monkeypatch, tmp_path):
    config_path = _write_config(tmp_path)
    manager = _manager_from_config(config_path)
    _add_collection_with_job(manager=manager, project_root=tmp_path, name="exp1", job_name="job1", job_id="100")

    monkeypatch.setattr("slurmkit.collections.get_canonical_sacct_states", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        "slurmkit.workflows.jobs.submit_job",
        lambda _path, dry_run=False: (True, "101", "Submitted batch job 101"),
    )

    result = runner.invoke(
        cli_app,
        ["--config", str(config_path), "resubmit", "--job-id", "100", "--no-regenerate", "-y"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert "Resubmitted 1/1 job(s)." in result.stdout
    updated = manager.load("exp1")
    assert len(updated.jobs[0]["attempts"]) == 2
    assert updated.jobs[0]["attempts"][-1]["job_id"] == "101"


def test_resubmit_job_id_errors_on_ambiguous_match(tmp_path):
    config_path = _write_config(tmp_path)
    manager = _manager_from_config(config_path)
    _add_collection_with_job(manager=manager, project_root=tmp_path, name="exp1", job_name="job1", job_id="100")
    _add_collection_with_job(manager=manager, project_root=tmp_path, name="exp2", job_name="job2", job_id="100")

    result = runner.invoke(
        cli_app,
        ["--config", str(config_path), "resubmit", "--job-id", "100", "--no-regenerate", "-y"],
    )

    output = result.stderr or result.stdout
    assert result.exit_code != 0
    assert "matched multiple collections" in output
    assert "exp1" in output
    assert "exp2" in output


def test_resubmit_job_id_errors_when_missing(tmp_path):
    config_path = _write_config(tmp_path)
    manager = _manager_from_config(config_path)
    _add_collection_with_job(manager=manager, project_root=tmp_path, name="exp1", job_name="job1", job_id="100")

    result = runner.invoke(
        cli_app,
        ["--config", str(config_path), "resubmit", "--job-id", "999", "--no-regenerate", "-y"],
    )

    output = result.stderr or result.stdout
    assert result.exit_code != 0
    assert "No collection found for job ID '999'" in output


def test_resubmit_job_id_with_collection_scope_disambiguates(monkeypatch, tmp_path):
    config_path = _write_config(tmp_path)
    manager = _manager_from_config(config_path)
    _add_collection_with_job(manager=manager, project_root=tmp_path, name="exp1", job_name="job1", job_id="100")
    _add_collection_with_job(manager=manager, project_root=tmp_path, name="exp2", job_name="job2", job_id="100")

    monkeypatch.setattr("slurmkit.collections.get_canonical_sacct_states", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        "slurmkit.workflows.jobs.submit_job",
        lambda _path, dry_run=False: (True, "101", "Submitted batch job 101"),
    )

    result = runner.invoke(
        cli_app,
        ["--config", str(config_path), "resubmit", "exp1", "--job-id", "100", "--no-regenerate", "-y"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    updated_exp1 = manager.load("exp1")
    updated_exp2 = manager.load("exp2")
    assert len(updated_exp1.jobs[0]["attempts"]) == 2
    assert len(updated_exp2.jobs[0]["attempts"]) == 1


def test_resubmit_job_id_rejects_filter_all(tmp_path):
    config_path = _write_config(tmp_path)

    result = runner.invoke(
        cli_app,
        ["--config", str(config_path), "resubmit", "--job-id", "100", "--filter", "all"],
    )

    output = result.stderr or result.stdout
    assert result.exit_code != 0
    assert "--filter" in output
    assert "cannot be used with" in output


def test_resubmit_job_id_rejects_select_file(tmp_path):
    config_path = _write_config(tmp_path)
    selector = tmp_path / "selector.py"
    selector.write_text("def should_resubmit(context):\n    return True\n", encoding="utf-8")

    result = runner.invoke(
        cli_app,
        ["--config", str(config_path), "resubmit", "--job-id", "100", "--select-file", str(selector)],
    )

    output = result.stderr or result.stdout
    assert result.exit_code != 0
    assert "--select-file" in output
    assert "cannot be used with" in output


def test_resubmit_job_id_rejects_non_default_select_function(tmp_path):
    config_path = _write_config(tmp_path)

    result = runner.invoke(
        cli_app,
        ["--config", str(config_path), "resubmit", "--job-id", "100", "--select-function", "custom_selector"],
    )

    output = result.stderr or result.stdout
    assert result.exit_code != 0
    assert "--select-function" in output
    assert "cannot be used with" in output
