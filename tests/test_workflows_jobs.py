"""Tests for generation, submission, and resubmission workflows."""

from __future__ import annotations

from pathlib import Path

import pytest

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
                "job_subdir: experiments/train_exp",
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
    manager = CollectionManager(config=config)
    spec = _write_spec(tmp_path)
    collection_name = "experiment/group/run_20260406"

    plan = plan_generate(
        config=config,
        manager=manager,
        spec_path=spec,
        collection_name=collection_name,
    )
    result = execute_generate(config=config, manager=manager, plan=plan, dry_run=False)

    collection = manager.load(collection_name)
    assert result["generated_count"] == 2
    assert (tmp_path / ".slurmkit" / "collections" / "experiment" / "group" / "run_20260406.yaml").exists()
    assert collection.generation["spec_path"] == "job_spec.yaml"
    assert collection.generation["job_subdir"] == "experiments/train_exp"
    assert collection.generation["scripts_dir"] == str(tmp_path / ".jobs" / "experiments" / "train_exp" / "job_scripts")
    assert collection.generation["logs_dir"] == str(tmp_path / ".jobs" / "experiments" / "train_exp" / "logs")
    assert len(collection.jobs) == 2


def test_generate_workflow_resolves_templated_job_subdir_and_review(tmp_path):
    config = get_config(project_root=tmp_path, reload=True)
    manager = CollectionManager(config=config)
    template = tmp_path / "template.job.j2"
    template.write_text("#!/bin/bash\n#SBATCH --job-name={{ job_name }}\n", encoding="utf-8")
    spec = tmp_path / "job_spec.yaml"
    spec.write_text(
        "\n".join(
            [
                "name: train_exp",
                f"template: {template.name}",
                "job_subdir: experiments/{{ collection_slug }}/{{ vars.stage }}",
                "variables:",
                "  stage: baseline",
                "parameters:",
                "  mode: list",
                "  values:",
                "    - lr: 0.1",
            ]
        ),
        encoding="utf-8",
    )

    plan = plan_generate(
        config=config,
        manager=manager,
        spec_path=spec,
        collection_name="experiment/group/run_20260406",
    )
    assert "Job subdir (raw): experiments/{{ collection_slug }}/{{ vars.stage }}" in plan.review.lines
    assert "Job subdir (resolved): experiments/experiment-group-run_20260406/baseline" in plan.review.lines

    result = execute_generate(config=config, manager=manager, plan=plan, dry_run=False)
    collection = manager.load("experiment/group/run_20260406")
    assert result["generated_count"] == 1
    assert collection.generation["job_subdir"] == "experiments/experiment-group-run_20260406/baseline"
    assert collection.generation["scripts_dir"] == str(
        tmp_path / ".jobs" / "experiments" / "experiment-group-run_20260406" / "baseline" / "job_scripts"
    )
    assert collection.generation["logs_dir"] == str(
        tmp_path / ".jobs" / "experiments" / "experiment-group-run_20260406" / "baseline" / "logs"
    )


def test_submit_workflow_updates_primary_attempt(monkeypatch, tmp_path):
    config = get_config(project_root=tmp_path, reload=True)
    manager = CollectionManager(config=config)
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
    manager = CollectionManager(config=config)
    template = tmp_path / "template.job.j2"
    template.write_text("#!/bin/bash\n#SBATCH --job-name={{ job_name }}\n", encoding="utf-8")
    scripts_dir = tmp_path / "jobs" / "exp1" / "job_scripts"
    logs_dir = tmp_path / "jobs" / "exp1" / "logs"
    scripts_dir.mkdir(parents=True)
    logs_dir.mkdir(parents=True)
    collection = Collection(
        "exp1",
        generation={
            "template_path": str(template),
            "job_subdir": "exp1",
            "scripts_dir": str(scripts_dir),
            "logs_dir": str(logs_dir),
            "slurm_defaults": {},
            "slurm_logic_file": None,
            "slurm_logic_function": "get_slurm_args",
            "job_name_pattern": None,
        },
    )
    script = scripts_dir / "job1.job"
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


def test_resubmit_workflow_single_target_errors_when_filter_mismatch(monkeypatch, tmp_path):
    config = get_config(project_root=tmp_path, reload=True)
    manager = CollectionManager(config=config)
    collection = Collection("exp1")
    script = tmp_path / "job1.job"
    script.write_text("#!/bin/bash\n", encoding="utf-8")
    collection.add_job("job1", script_path=script, job_id="100", state="COMPLETED", parameters={"lr": 0.1})
    manager.save(collection)

    monkeypatch.setattr("slurmkit.collections.get_canonical_sacct_states", lambda *_args, **_kwargs: {})

    with pytest.raises(ValueError, match="do not match --filter failed"):
        plan_resubmit_collection(
            config=config,
            collection=collection,
            filter_name="failed",
            template=None,
            extra_params=None,
            extra_params_file=None,
            extra_params_function="get_extra_params",
            select_file=None,
            select_function="should_resubmit",
            submission_group="group_b",
            regenerate=False,
            target_job_names=["job1"],
        )


def test_resubmit_workflow_filter_preempted_uses_raw_state_mapping(monkeypatch, tmp_path):
    config = get_config(project_root=tmp_path, reload=True)
    collection = Collection("exp1")
    script_a = tmp_path / "job_a.job"
    script_b = tmp_path / "job_b.job"
    script_a.write_text("#!/bin/bash\n", encoding="utf-8")
    script_b.write_text("#!/bin/bash\n", encoding="utf-8")
    collection.add_job("job_preempted", script_path=script_a, job_id="100", state="FAILED")
    collection.add_job("job_failed", script_path=script_b, job_id="101", state="FAILED")
    collection.get_job("job_preempted")["attempts"][-1]["raw_state"] = {
        "resolution": {"canonical_state": "PREEMPTED"},
    }
    collection.get_job("job_failed")["attempts"][-1]["raw_state"] = {
        "resolution": {"canonical_state": "FAILED"},
    }

    monkeypatch.setattr("slurmkit.collections.get_canonical_sacct_states", lambda *_args, **_kwargs: {})

    plan = plan_resubmit_collection(
        config=config,
        collection=collection,
        filter_name="preempted",
        template=None,
        extra_params=None,
        extra_params_file=None,
        extra_params_function="get_extra_params",
        select_file=None,
        select_function="should_resubmit",
        submission_group="group_preempted",
        regenerate=False,
    )

    assert [item["job_name"] for item in plan.items] == ["job_preempted"]


@pytest.mark.parametrize(
    ("filter_name", "expected_job_name"),
    [
        ("timeout", "job_timeout"),
        ("cancelled", "job_cancelled"),
        ("node_fail", "job_node_fail"),
        ("out_of_memory", "job_oom"),
        ("oom", "job_oom"),
    ],
)
def test_resubmit_workflow_terminal_filters(filter_name, expected_job_name, monkeypatch, tmp_path):
    config = get_config(project_root=tmp_path, reload=True)
    collection = Collection("exp1")
    states = {
        "job_timeout": "TIMEOUT",
        "job_cancelled": "CANCELLED",
        "job_node_fail": "NODE_FAIL",
        "job_oom": "OUT_OF_MEMORY",
    }
    for job_name, state in states.items():
        script = tmp_path / f"{job_name}.job"
        script.write_text("#!/bin/bash\n", encoding="utf-8")
        collection.add_job(job_name, script_path=script, job_id=f"id_{job_name}", state=state)

    monkeypatch.setattr("slurmkit.collections.get_canonical_sacct_states", lambda *_args, **_kwargs: {})

    plan = plan_resubmit_collection(
        config=config,
        collection=collection,
        filter_name=filter_name,
        template=None,
        extra_params=None,
        extra_params_file=None,
        extra_params_function="get_extra_params",
        select_file=None,
        select_function="should_resubmit",
        submission_group="group_terminal",
        regenerate=False,
    )

    assert [item["job_name"] for item in plan.items] == [expected_job_name]


def test_resubmit_workflow_invalid_filter_raises(tmp_path):
    config = get_config(project_root=tmp_path, reload=True)
    collection = Collection("exp1")
    script = tmp_path / "job1.job"
    script.write_text("#!/bin/bash\n", encoding="utf-8")
    collection.add_job("job1", script_path=script, job_id="100", state="FAILED")

    with pytest.raises(ValueError, match="Allowed values:"):
        plan_resubmit_collection(
            config=config,
            collection=collection,
            filter_name="nonsense",
            template=None,
            extra_params=None,
            extra_params_file=None,
            extra_params_function="get_extra_params",
            select_file=None,
            select_function="should_resubmit",
            submission_group="group_invalid",
            regenerate=False,
        )


def test_resubmit_workflow_all_filter_is_explicit(monkeypatch, tmp_path):
    config = get_config(project_root=tmp_path, reload=True)
    collection = Collection("exp1")
    for idx, state in enumerate(("FAILED", "COMPLETED", "RUNNING"), start=1):
        script = tmp_path / f"job{idx}.job"
        script.write_text("#!/bin/bash\n", encoding="utf-8")
        collection.add_job(f"job{idx}", script_path=script, job_id=str(100 + idx), state=state)

    monkeypatch.setattr("slurmkit.collections.get_canonical_sacct_states", lambda *_args, **_kwargs: {})

    plan = plan_resubmit_collection(
        config=config,
        collection=collection,
        filter_name="all",
        template=None,
        extra_params=None,
        extra_params_file=None,
        extra_params_function="get_extra_params",
        select_file=None,
        select_function="should_resubmit",
        submission_group="group_all",
        regenerate=False,
    )
    assert [item["job_name"] for item in plan.items] == ["job1", "job2", "job3"]


def test_resubmit_workflow_single_target_dry_run_does_not_mutate_collection(monkeypatch, tmp_path):
    config = get_config(project_root=tmp_path, reload=True)
    manager = CollectionManager(config=config)
    collection = Collection("exp1")
    script = tmp_path / "job1.job"
    script.write_text("#!/bin/bash\n", encoding="utf-8")
    collection.add_job("job1", script_path=script, job_id="100", state="FAILED", parameters={"lr": 0.1})
    manager.save(collection)

    monkeypatch.setattr("slurmkit.collections.get_canonical_sacct_states", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("slurmkit.workflows.jobs.submit_job", lambda _path, dry_run=False: (True, "101", "Submitted batch job 101"))

    plan = plan_resubmit_collection(
        config=config,
        collection=collection,
        filter_name="failed",
        template=None,
        extra_params=None,
        extra_params_file=None,
        extra_params_function="get_extra_params",
        select_file=None,
        select_function="should_resubmit",
        submission_group="group_c",
        regenerate=False,
        target_job_names=["job1"],
    )
    result = execute_resubmit_collection(manager=manager, plan=plan, dry_run=True)
    updated = manager.load("exp1")
    assert result["resubmitted_count"] == 1
    assert len(updated.jobs[0]["attempts"]) == 1


def test_resubmit_workflow_single_target_uses_latest_attempt_chain(monkeypatch, tmp_path):
    config = get_config(project_root=tmp_path, reload=True)
    manager = CollectionManager(config=config)
    collection = Collection("exp1")
    primary_script = tmp_path / "job1_primary.job"
    retry_script = tmp_path / "job1_retry.job"
    primary_script.write_text("#!/bin/bash\n", encoding="utf-8")
    retry_script.write_text("#!/bin/bash\n", encoding="utf-8")
    collection.add_job("job1", script_path=primary_script, job_id="100", state="FAILED", parameters={"lr": 0.1})
    collection.add_resubmission("job1", job_id="101", attempt_script_path=retry_script)
    collection.get_job("job1")["attempts"][-1]["state"] = "FAILED"
    manager.save(collection)

    monkeypatch.setattr("slurmkit.collections.get_canonical_sacct_states", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("slurmkit.workflows.jobs.submit_job", lambda _path, dry_run=False: (True, "102", "Submitted batch job 102"))

    plan = plan_resubmit_collection(
        config=config,
        collection=collection,
        filter_name="failed",
        template=None,
        extra_params=None,
        extra_params_file=None,
        extra_params_function="get_extra_params",
        select_file=None,
        select_function="should_resubmit",
        submission_group="group_d",
        regenerate=False,
        target_job_names=["job1"],
    )
    assert len(plan.items) == 1
    assert plan.items[0]["original_job_id"] == "101"

    result = execute_resubmit_collection(manager=manager, plan=plan, dry_run=False)
    updated = manager.load("exp1")
    assert result["resubmitted_count"] == 1
    assert len(updated.jobs[0]["attempts"]) == 3
    assert updated.jobs[0]["attempts"][-1]["job_id"] == "102"
