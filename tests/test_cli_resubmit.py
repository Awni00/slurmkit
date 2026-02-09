"""Tests for `slurmkit resubmit` CLI behavior."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import yaml

from slurmkit.cli import commands
from slurmkit.cli.main import create_parser
from slurmkit.collections import Collection


class _FakeConfig:
    def __init__(self, jobs_dir: Path):
        self.jobs_dir = jobs_dir

    def get_path(self, _key, _default=None):
        return self.jobs_dir

    def get_slurm_defaults(self):
        return {"partition": "cpu", "time": "00:10:00"}


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

    def get_or_create(self, _name, description=""):
        self.collection.description = description
        return self.collection


def _build_resubmit_args(**overrides):
    base = {
        "collection": "exp1",
        "filter": "all",
        "job_ids": [],
        "template": None,
        "extra_params": None,
        "extra_params_file": None,
        "extra_params_function": "get_extra_params",
        "select_file": None,
        "select_function": "should_resubmit",
        "submission_group": "group_alpha",
        "jobs_dir": None,
        "regenerate": None,
        "dry_run": False,
        "yes": True,
    }
    base.update(overrides)
    return Namespace(**base)


def test_resubmit_parser_new_arguments():
    """Parser accepts callback + submission-group + regenerate options."""
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
    assert args.regenerate is None
    assert args.dry_run is True


def test_resubmit_parser_regenerate_flags():
    """Parser exposes tri-state regenerate toggle."""
    parser = create_parser()

    args_yes = parser.parse_args(["resubmit", "--collection", "exp1", "--regenerate"])
    assert args_yes.regenerate is True

    args_no = parser.parse_args(["resubmit", "--collection", "exp1", "--no-regenerate"])
    assert args_no.regenerate is False


def test_cmd_resubmit_callbacks_and_merge_no_regenerate(monkeypatch, tmp_path):
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

    submitted_paths = []

    monkeypatch.setattr(commands, "get_configured_config", lambda _args: _FakeConfig(tmp_path))
    monkeypatch.setattr(commands, "CollectionManager", lambda config=None: manager)
    monkeypatch.setattr(commands, "prompt_yes_no", lambda _msg: True)
    monkeypatch.setattr(
        commands,
        "submit_job",
        lambda path, dry_run=False: (
            submitted_paths.append(Path(path)),
            (True, "9001", "Submitted batch job 9001"),
        )[1],
    )

    args = _build_resubmit_args(
        extra_params="override=from_cli,checkpoint=last.pt",
        extra_params_file=str(cb_file),
        extra_params_function="get_extra_params",
        select_file=str(cb_file),
        select_function="should_resubmit",
        regenerate=False,
    )

    exit_code = commands.cmd_resubmit(args)

    assert exit_code == 0
    assert manager.saved is True
    assert submitted_paths == [script_a]
    run_job = collection.get_job("run_job")
    assert len(run_job["resubmissions"]) == 1
    resub = run_job["resubmissions"][0]
    assert resub["submission_group"] == "group_alpha"
    assert resub["extra_params"]["source"] == "callback"
    assert resub["extra_params"]["override"] == "from_cli"
    assert resub["extra_params"]["checkpoint"] == "last.pt"
    assert resub["regenerated"] is False
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

    args = _build_resubmit_args(
        submission_group=None,
        dry_run=True,
        regenerate=False,
    )

    exit_code = commands.cmd_resubmit(args)
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Submission group: resubmit_" in output
    assert len(collection.get_job("run_job")["resubmissions"]) == 0


def test_cmd_resubmit_collection_default_regenerates(monkeypatch, tmp_path):
    """Collection mode defaults to regeneration and applies extra params in script rendering."""
    template = tmp_path / "train.job.j2"
    template.write_text(
        "#!/bin/bash\n"
        "#SBATCH --job-name={{ job_name }}\n"
        "echo checkpoint={{ checkpoint }}\n",
        encoding="utf-8",
    )
    old_script = tmp_path / "old.job"
    old_script.write_text("#!/bin/bash\necho old\n", encoding="utf-8")
    output_dir = tmp_path / "job_scripts"

    collection = Collection("exp1")
    collection.meta["generation"] = {
        "template_path": str(template),
        "output_dir": str(output_dir),
        "job_name_pattern": None,
        "logs_dir": None,
        "slurm_defaults": {"partition": "cpu", "time": "00:10:00"},
        "slurm_logic_file": None,
        "slurm_logic_function": "get_slurm_args",
    }
    collection.add_job(
        job_name="run_job",
        script_path=str(old_script),
        job_id=None,
        state="FAILED",
        parameters={"checkpoint": "old.pt"},
    )
    collection.refresh_states = lambda: 0  # type: ignore[method-assign]
    manager = _FakeManager(collection)

    submitted_paths = []
    monkeypatch.setattr(commands, "get_configured_config", lambda _args: _FakeConfig(tmp_path))
    monkeypatch.setattr(commands, "CollectionManager", lambda config=None: manager)
    monkeypatch.setattr(
        commands,
        "submit_job",
        lambda path, dry_run=False: (
            submitted_paths.append(Path(path)),
            (True, "9999", "Submitted batch job 9999"),
        )[1],
    )

    args = _build_resubmit_args(extra_params="checkpoint=new.pt")
    exit_code = commands.cmd_resubmit(args)

    assert exit_code == 0
    assert len(submitted_paths) == 1
    regenerated_script = submitted_paths[0]
    assert regenerated_script.name == "run_job.resubmit-1.job"
    assert regenerated_script.exists()
    assert "checkpoint=new.pt" in regenerated_script.read_text(encoding="utf-8")

    resub = collection.get_job("run_job")["resubmissions"][0]
    assert resub["regenerated"] is True
    assert resub["job_name"] == "run_job.resubmit-1"
    assert resub["script_path"].endswith("run_job.resubmit-1.job")
    assert resub["parameters"]["checkpoint"] == "new.pt"


def test_cmd_resubmit_regenerated_suffix_uses_attempt_count(monkeypatch, tmp_path):
    """Regenerated scripts should increment suffix by total attempt count."""
    template = tmp_path / "train.job.j2"
    template.write_text("#!/bin/bash\necho hi\n", encoding="utf-8")
    old_script = tmp_path / "old.job"
    old_script.write_text("#!/bin/bash\n", encoding="utf-8")
    output_dir = tmp_path / "job_scripts"

    collection = Collection("exp1")
    collection.meta["generation"] = {
        "template_path": str(template),
        "output_dir": str(output_dir),
        "slurm_defaults": {},
    }
    collection.add_job(
        job_name="run_job",
        script_path=str(old_script),
        job_id=None,
        state="FAILED",
        parameters={},
    )
    collection.add_resubmission("run_job", job_id="111")
    collection.refresh_states = lambda: 0  # type: ignore[method-assign]
    manager = _FakeManager(collection)

    submitted_paths = []
    monkeypatch.setattr(commands, "get_configured_config", lambda _args: _FakeConfig(tmp_path))
    monkeypatch.setattr(commands, "CollectionManager", lambda config=None: manager)
    monkeypatch.setattr(
        commands,
        "submit_job",
        lambda path, dry_run=False: (
            submitted_paths.append(Path(path)),
            (True, "9999", "Submitted batch job 9999"),
        )[1],
    )

    exit_code = commands.cmd_resubmit(_build_resubmit_args())
    assert exit_code == 0
    assert submitted_paths[0].name == "run_job.resubmit-2.job"


def test_cmd_resubmit_default_regenerate_fails_without_metadata(monkeypatch, tmp_path, capsys):
    """Collection mode should fail hard without generation metadata."""
    old_script = tmp_path / "old.job"
    old_script.write_text("#!/bin/bash\n", encoding="utf-8")
    collection = Collection("exp1")
    collection.add_job(job_name="run_job", script_path=str(old_script), job_id=None, state="FAILED")
    collection.refresh_states = lambda: 0  # type: ignore[method-assign]
    manager = _FakeManager(collection)

    monkeypatch.setattr(commands, "get_configured_config", lambda _args: _FakeConfig(tmp_path))
    monkeypatch.setattr(commands, "CollectionManager", lambda config=None: manager)

    exit_code = commands.cmd_resubmit(_build_resubmit_args())
    output = capsys.readouterr()
    assert exit_code == 1
    assert "--no-regenerate" in (output.out + output.err)


def test_cmd_resubmit_job_id_mode_defaults_to_reuse(monkeypatch, tmp_path):
    """Job ID mode should keep old script resubmission behavior by default."""
    script = tmp_path / "job123.job"
    script.write_text("#!/bin/bash\n", encoding="utf-8")

    submitted_paths = []
    monkeypatch.setattr(commands, "get_configured_config", lambda _args: _FakeConfig(tmp_path))
    monkeypatch.setattr(commands, "infer_script_path", lambda *args, **kwargs: script)
    monkeypatch.setattr(
        commands,
        "submit_job",
        lambda path, dry_run=False: (
            submitted_paths.append(Path(path)),
            (True, "7777", "Submitted batch job 7777"),
        )[1],
    )

    args = _build_resubmit_args(collection=None, job_ids=["123"], regenerate=None)
    exit_code = commands.cmd_resubmit(args)
    assert exit_code == 0
    assert submitted_paths == [script]


def test_cmd_resubmit_explicit_regenerate_requires_collection(monkeypatch, tmp_path, capsys):
    """Explicit --regenerate should error when not using collection mode."""
    script = tmp_path / "job123.job"
    script.write_text("#!/bin/bash\n", encoding="utf-8")

    monkeypatch.setattr(commands, "get_configured_config", lambda _args: _FakeConfig(tmp_path))
    monkeypatch.setattr(commands, "infer_script_path", lambda *args, **kwargs: script)

    args = _build_resubmit_args(collection=None, job_ids=["123"], regenerate=True)
    exit_code = commands.cmd_resubmit(args)
    output = capsys.readouterr()
    assert exit_code == 1
    assert "--collection" in (output.out + output.err)


def test_cmd_generate_persists_generation_metadata(monkeypatch, tmp_path):
    """cmd_generate should store generation context in collection metadata."""
    template = tmp_path / "train.job.j2"
    template.write_text(
        "#!/bin/bash\n"
        "#SBATCH --partition={{ slurm.partition }}\n"
        "echo {{ run }}\n",
        encoding="utf-8",
    )
    params = tmp_path / "params.yaml"
    params.write_text("mode: list\nvalues:\n  - run: 1\n", encoding="utf-8")
    output_dir = tmp_path / "scripts"

    collection = Collection("exp1")
    manager = _FakeManager(collection)
    monkeypatch.setattr(commands, "get_configured_config", lambda _args: _FakeConfig(tmp_path))
    monkeypatch.setattr(commands, "CollectionManager", lambda config=None: manager)

    args = Namespace(
        spec_file=None,
        template=str(template),
        params=str(params),
        output_dir=str(output_dir),
        collection="exp1",
        slurm_args_file=None,
        dry_run=False,
    )
    exit_code = commands.cmd_generate(args)

    assert exit_code == 0
    assert manager.saved is True
    generation_meta = collection.meta["generation"]
    assert generation_meta["template_path"] == str(template)
    assert generation_meta["output_dir"] == str(output_dir)
    assert generation_meta["slurm_logic_function"] == "get_slurm_args"
    assert isinstance(generation_meta["slurm_defaults"], dict)
    assert collection.parameters == yaml.safe_load(params.read_text(encoding="utf-8"))
