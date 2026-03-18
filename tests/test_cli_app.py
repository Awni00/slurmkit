"""Tests for the rewritten Typer CLI surface."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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
