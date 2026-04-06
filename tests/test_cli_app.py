"""Tests for the rewritten Typer CLI surface."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import yaml
from typer.testing import CliRunner

from slurmkit.cli.app import app as cli_app


runner = CliRunner()


def _write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / ".slurmkit" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump({"jobs_dir": "jobs/"}), encoding="utf-8")
    return config_path


def _write_collection_file(
    tmp_path: Path,
    *,
    name: str,
    updated_at: str | None,
    state: str = "COMPLETED",
    generation: dict | None = None,
) -> None:
    collections_dir = tmp_path / ".slurmkit" / "collections"
    collections_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 2,
        "name": name,
        "description": "",
        "created_at": "2026-03-20T10:00:00",
        "updated_at": updated_at,
        "cluster": "cluster-a",
        "parameters": {},
        "generation": generation or {},
        "notifications": {},
        "jobs": [
            {
                "job_name": f"{name}_job",
                "parameters": {},
                "attempts": [
                    {
                        "kind": "primary",
                        "job_id": "100",
                        "state": state,
                        "hostname": "cluster-a",
                        "submitted_at": "2026-03-20T10:00:00",
                        "started_at": "2026-03-20T10:00:10",
                        "completed_at": "2026-03-20T11:00:00",
                        "script_path": str(tmp_path / ".jobs" / name / "job_scripts" / "job.sh"),
                        "output_path": str(tmp_path / ".jobs" / name / "logs" / "job.100.out"),
                    }
                ],
            }
        ],
    }
    (collections_dir / f"{name}.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )


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


def test_collections_no_args_opens_picker_when_prompting_enabled(monkeypatch):
    from importlib import import_module

    collections_module = import_module("slurmkit.cli.commands_collections")

    monkeypatch.setattr(collections_module, "can_prompt", lambda _state: True)
    monkeypatch.setattr(collections_module, "choose_command", lambda _sections: None)

    result = runner.invoke(cli_app, ["collections"])

    assert result.exit_code == 0
    assert "Canceled." in result.stdout


def test_structured_output_disables_prompt_fallback(tmp_path):
    config_path = tmp_path / ".slurmkit" / "config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(yaml.dump({"jobs_dir": "jobs/"}), encoding="utf-8")

    result = runner.invoke(cli_app, ["--config", str(config_path), "collections", "show", "--json"])

    assert result.exit_code != 0
    assert "Missing collection argument." in (result.stderr or result.stdout)


def test_removed_jobs_namespace_is_not_registered():
    result = runner.invoke(cli_app, ["jobs"])
    assert result.exit_code != 0
    assert "No such command" in (result.stderr or result.stdout)


def test_collections_list_table_renders_expected_columns_and_newest_first(tmp_path):
    config_path = _write_config(tmp_path)
    _write_collection_file(tmp_path, name="older", updated_at="2026-03-20T10:00:00", state="FAILED")
    _write_collection_file(tmp_path, name="newer", updated_at="2026-03-24T10:00:00", state="COMPLETED")

    result = runner.invoke(
        cli_app,
        ["--config", str(config_path), "--ui", "plain", "collections", "list"],
    )

    assert result.exit_code == 0
    assert "Name" in result.stdout
    assert "Total" in result.stdout
    assert "Completed" in result.stdout
    assert "Failed" in result.stdout
    assert "Running" in result.stdout
    assert "Pending" in result.stdout
    assert "Not Submitted" in result.stdout
    assert "Updated" in result.stdout
    assert result.stdout.index("newer") < result.stdout.index("older")


def test_collections_list_json_preserves_schema_and_uses_newest_first_order(tmp_path):
    config_path = _write_config(tmp_path)
    _write_collection_file(tmp_path, name="older", updated_at="2026-03-20T10:00:00")
    _write_collection_file(tmp_path, name="newer", updated_at="2026-03-24T10:00:00")

    result = runner.invoke(
        cli_app,
        ["--config", str(config_path), "collections", "list", "--json"],
    )

    assert result.exit_code == 0
    rows = json.loads(result.stdout)
    assert [row["name"] for row in rows] == ["newer", "older"]
    assert set(rows[0].keys()) == {
        "name",
        "description",
        "cluster",
        "created_at",
        "updated_at",
        "total",
        "completed",
        "failed",
        "running",
        "pending",
        "unknown",
        "not_submitted",
    }


def test_collections_list_empty_state_shows_no_collections_message(tmp_path):
    config_path = _write_config(tmp_path)

    result = runner.invoke(
        cli_app,
        ["--config", str(config_path), "--ui", "plain", "collections", "list"],
    )

    assert result.exit_code == 0
    assert "(no collections)" in result.stdout


def test_status_command_rejects_removed_state_option(tmp_path):
    config_path = _write_config(tmp_path)
    _write_collection_file(tmp_path, name="exp1", updated_at="2026-03-24T10:00:00")

    result = runner.invoke(
        cli_app,
        ["--config", str(config_path), "status", "exp1", "--state", "failed"],
    )

    assert result.exit_code != 0
    assert "No such option: --state" in (result.stderr or result.stdout)


def test_status_text_is_summary_only_and_includes_header_links(tmp_path):
    config_path = _write_config(tmp_path)
    _write_collection_file(
        tmp_path,
        name="exp1",
        updated_at="2026-03-24T10:00:00",
        generation={
            "spec_path": "experiments/exp1/slurmkit/job_spec.yaml",
            "scripts_dir": ".jobs/exp1/job_scripts",
            "logs_dir": ".jobs/exp1/logs",
        },
    )

    result = runner.invoke(
        cli_app,
        ["--config", str(config_path), "--ui", "plain", "status", "exp1"],
    )

    assert result.exit_code == 0
    assert "Summary:" in result.stdout
    assert "Jobs (" not in result.stdout
    assert "Generation Parameters:" not in result.stdout
    assert "Collection Est. Completion" in result.stdout
    assert "N/A (0/0 estimable active jobs)" in result.stdout
    assert "Spec" in result.stdout
    assert "Collection File" in result.stdout
    assert "Scripts Dir" in result.stdout
    assert "Logs Dir" in result.stdout
    assert "experiments/exp1/slurmkit/job_spec.yaml" in result.stdout
    assert ".slurmkit/collections/exp1.yaml" in result.stdout
    assert ".jobs/exp1/job_scripts" in result.stdout
    assert ".jobs/exp1/logs" in result.stdout
    assert str(tmp_path) not in result.stdout


def test_status_json_is_compact_and_omits_jobs(tmp_path):
    config_path = _write_config(tmp_path)
    _write_collection_file(
        tmp_path,
        name="exp1",
        updated_at="2026-03-24T10:00:00",
        generation={
            "spec_path": "experiments/exp1/slurmkit/job_spec.yaml",
            "scripts_dir": ".jobs/exp1/job_scripts",
            "logs_dir": ".jobs/exp1/logs",
        },
    )

    result = runner.invoke(
        cli_app,
        ["--config", str(config_path), "status", "exp1", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert set(payload.keys()) == {"collection", "summary", "links"}
    assert "jobs" not in payload
    assert payload["collection"]["name"] == "exp1"
    assert set(payload["collection"].keys()) == {
        "name",
        "description",
        "created_at",
        "updated_at",
        "cluster",
        "attempt_mode",
        "submission_group",
        "estimated_completion_at",
        "estimated_remaining_seconds",
        "estimable_active_jobs",
        "active_jobs",
    }
    assert payload["summary"]["total"] == 1
    assert set(payload["links"].keys()) == {
        "spec_path",
        "collection_file",
        "scripts_dir",
        "logs_dir",
    }


def test_collections_show_json_includes_eta_fields(monkeypatch, tmp_path):
    config_path = _write_config(tmp_path)
    _write_collection_file(
        tmp_path,
        name="exp_eta",
        updated_at="2026-03-24T10:00:00",
        state="RUNNING",
    )

    monkeypatch.setattr(
        "slurmkit.workflows.collections.get_active_queue_timing",
        lambda job_ids=None: {
            "100": {
                "job_id": "100",
                "state_raw": "RUNNING",
                "estimated_start_at": None,
                "time_limit_seconds": None,
                "time_left_seconds": 1800,
            }
        },
    )

    result = runner.invoke(
        cli_app,
        ["--config", str(config_path), "collections", "show", "exp_eta", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["estimated_completion_at"] is not None
    assert isinstance(payload["estimated_remaining_seconds"], int)
    assert payload["estimable_active_jobs"] == 1
    assert payload["active_jobs"] == 1
    assert len(payload["jobs"]) == 1
    row = payload["jobs"][0]
    assert "effective_eta_start_at" in row
    assert row["effective_eta_completion_at"] is not None
    assert isinstance(row["effective_eta_remaining_seconds"], int)


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
    assert "Specs migrated:" in result.stdout
    assert (root / ".slurmkit" / "config.yaml").exists()
    assert (root / ".slurmkit" / "collections" / "old.yaml").exists()


def test_install_skill_command_success(monkeypatch):
    from importlib import import_module

    maintenance_module = import_module("slurmkit.cli.commands_maintenance")

    monkeypatch.setattr(
        maintenance_module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0),
    )

    result = runner.invoke(cli_app, ["install-skill", "--yes"])

    assert result.exit_code == 0
    assert "Installed slurmkit skill from Awni00/slurmkit." in result.stdout


def test_install_skill_command_missing_npx(monkeypatch):
    from importlib import import_module

    maintenance_module = import_module("slurmkit.cli.commands_maintenance")

    def _raise_not_found(*_args, **_kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(maintenance_module.subprocess, "run", _raise_not_found)

    result = runner.invoke(cli_app, ["install-skill", "--yes"])

    assert result.exit_code == 1
    assert "`npx` not found." in (result.stderr or result.stdout)


def test_install_skill_command_nonzero_exit(monkeypatch):
    from importlib import import_module

    maintenance_module = import_module("slurmkit.cli.commands_maintenance")

    monkeypatch.setattr(
        maintenance_module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=7),
    )

    result = runner.invoke(cli_app, ["install-skill", "--yes"])

    assert result.exit_code == 1
    assert "exited with code 7" in (result.stderr or result.stdout)


def test_install_skill_command_canceled_by_prompt(monkeypatch):
    from importlib import import_module

    maintenance_module = import_module("slurmkit.cli.commands_maintenance")

    monkeypatch.setattr(maintenance_module, "can_prompt", lambda _state: True)
    monkeypatch.setattr(maintenance_module, "prompt_confirm", lambda _message, default=True: False)
    monkeypatch.setattr(
        maintenance_module,
        "_install_slurmkit_skill_via_npx",
        lambda: (_ for _ in ()).throw(RuntimeError("should not run install")),
    )

    result = runner.invoke(cli_app, ["install-skill"])

    assert result.exit_code == 0
    assert "Canceled." in result.stdout


def test_setup_palette_includes_install_skill():
    from importlib import import_module

    cli_module = import_module("slurmkit.cli.app")
    sections = cli_module._command_sections()
    setup_section = next(section for section in sections if section.title == "Setup")
    command_ids = [entry.command_id for entry in setup_section.commands]
    assert "install_skill" in command_ids


def test_home_dispatches_install_skill_from_palette(monkeypatch):
    from importlib import import_module

    cli_module = import_module("slurmkit.cli.app")
    maintenance_module = import_module("slurmkit.cli.commands_maintenance")

    monkeypatch.setattr(cli_module, "choose_command", lambda _sections: "install_skill")
    monkeypatch.setattr(maintenance_module, "_install_slurmkit_skill_via_npx", lambda: (True, "installed"))

    result = runner.invoke(cli_app, ["home"])

    assert result.exit_code == 0
    assert "installed" in result.stdout


def test_spec_template_writes_default_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli_app, ["spec-template"], catch_exceptions=False)

    assert result.exit_code == 0
    output = tmp_path / "job_spec.yaml"
    assert output.exists()
    content = output.read_text(encoding="utf-8")
    assert "mode: grid" in content
    assert "template: template.job.j2" in content


def test_spec_template_writes_custom_output_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        cli_app,
        ["spec-template", "--output", "specs/custom_spec.yaml"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    output = tmp_path / "specs" / "custom_spec.yaml"
    assert output.exists()
    assert "job_subdir:" in output.read_text(encoding="utf-8")


def test_spec_template_errors_when_output_exists_without_force(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "job_spec.yaml"
    output.write_text("existing\n", encoding="utf-8")

    result = runner.invoke(cli_app, ["spec-template"])

    assert result.exit_code != 0
    assert "already exists" in (result.stderr or result.stdout)
    assert output.read_text(encoding="utf-8") == "existing\n"


def test_spec_template_overwrites_when_force_enabled(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "job_spec.yaml"
    output.write_text("existing\n", encoding="utf-8")

    result = runner.invoke(cli_app, ["spec-template", "--force"], catch_exceptions=False)

    assert result.exit_code == 0
    content = output.read_text(encoding="utf-8")
    assert content != "existing\n"
    assert "name: my_experiment" in content
