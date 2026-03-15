"""Tests for generation, submission, and resubmission workflows."""

from __future__ import annotations

from pathlib import Path

from slurmkit.collections import Collection, CollectionManager
from slurmkit.config import get_config
from slurmkit.workflows.jobs import (
    execute_generate,
    execute_resubmit_collection,
    execute_submit_collection,
    plan_generate,
    plan_resubmit_collection,
    plan_submit_collection,
)


def _write_spec(tmp_path: Path) -> Path:
    template = tmp_path / "template.job.j2"
    template.write_text("#!/bin/bash\n#SBATCH --job-name={{ job_name }}\necho {{ params.lr }}\n", encoding="utf-8")
    spec = tmp_path / "job_spec.yaml"
    spec.write_text(
        "\n".join(
            [
                "name: train_exp",
                f"template: {template.name}",
                "parameters:",
                "  mode: grid",
                "  values:",
                "    lr: [0.1, 0.2]",
            ]
        ),
        encoding="utf-8",
    )
    return spec


def test_generate_workflow_persists_generation_metadata(tmp_path):
    config = get_config(project_root=tmp_path, reload=True)
    manager = CollectionManager(collections_dir=tmp_path / ".job-collections", config=config)
    spec = _write_spec(tmp_path)

    plan = plan_generate(
        config=config,
        manager=manager,
        spec_path=spec,
        collection_name="train_exp_20260315",
        output_dir=tmp_path / "jobs",
    )
    result = execute_generate(config=config, manager=manager, plan=plan, dry_run=False)

    collection = manager.load("train_exp_20260315")
    assert result["generated_count"] == 2
    assert collection.generation["spec_path"] == "job_spec.yaml"
    assert len(collection.jobs) == 2


def test_submit_workflow_updates_primary_attempt(monkeypatch, tmp_path):
    manager = CollectionManager(collections_dir=tmp_path / ".job-collections")
    collection = Collection("exp1")
    script = tmp_path / "job1.job"
    script.write_text("#!/bin/bash\n", encoding="utf-8")
    collection.add_job("job1", script_path=script)
    manager.save(collection)

    monkeypatch.setattr("slurmkit.workflows.jobs.submit_job", lambda _path, dry_run=False: (True, "9001", "Submitted batch job 9001"))

    plan = plan_submit_collection(collection=collection, filter_name="unsubmitted")
    result = execute_submit_collection(manager=manager, plan=plan, delay=0.0, dry_run=False)

    updated = manager.load("exp1")
    assert result["submitted_count"] == 1
    assert updated.jobs[0]["attempts"][0]["job_id"] == "9001"


def test_resubmit_workflow_adds_attempt(monkeypatch, tmp_path):
    config = get_config(project_root=tmp_path, reload=True)
    manager = CollectionManager(collections_dir=tmp_path / ".job-collections", config=config)
    template = tmp_path / "template.job.j2"
    template.write_text("#!/bin/bash\n#SBATCH --job-name={{ job_name }}\n", encoding="utf-8")
    output_dir = tmp_path / "jobs"
    output_dir.mkdir()
    collection = Collection(
        "exp1",
        generation={
            "template_path": str(template),
            "output_dir": str(output_dir),
            "slurm_defaults": {},
            "slurm_logic_file": None,
            "slurm_logic_function": "get_slurm_args",
            "job_name_pattern": None,
            "logs_dir": None,
        },
    )
    script = output_dir / "job1.job"
    script.write_text("#!/bin/bash\n", encoding="utf-8")
    collection.add_job("job1", script_path=script, job_id="100", state="FAILED", parameters={"lr": 0.1})
    manager.save(collection)

    monkeypatch.setattr("slurmkit.workflows.jobs.submit_job", lambda _path, dry_run=False: (True, "101", "Submitted batch job 101"))

    plan = plan_resubmit_collection(
        config=config,
        collection=collection,
        filter_name="failed",
        template=None,
        extra_params="checkpoint=last.pt",
        extra_params_file=None,
        extra_params_function="get_extra_params",
        select_file=None,
        select_function="should_resubmit",
        submission_group="group_a",
        regenerate=True,
    )
    result = execute_resubmit_collection(manager=manager, plan=plan, dry_run=False)

    updated = manager.load("exp1")
    assert result["resubmitted_count"] == 1
    assert len(updated.jobs[0]["attempts"]) == 2
    assert updated.jobs[0]["attempts"][1]["job_id"] == "101"
    assert updated.jobs[0]["attempts"][1]["submission_group"] == "group_a"

