"""Generation, submission, and resubmission workflows."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from slurmkit.collections import Collection, CollectionManager, JOB_STATE_FAILED
from slurmkit.config import Config
from slurmkit.generate import JobGenerator, load_job_spec
from slurmkit.slurm import submit_job

from .shared import (
    ReviewPlan,
    build_generation_metadata,
    format_review,
    load_python_callback,
    parse_key_value_pairs,
    resolve_generation_context,
    resolve_job_paths_from_spec,
)


@dataclass
class GeneratePlan:
    spec_path: Path
    spec_data: Dict[str, Any]
    generator: JobGenerator
    collection_name: str
    existing_collection: Optional[Collection]
    job_subdir: str
    scripts_dir: Path
    logs_dir: Path
    items: List[Dict[str, Any]]
    review: ReviewPlan


@dataclass
class SubmitPlan:
    collection: Collection
    filter_name: str
    items: List[Dict[str, Any]]
    review: ReviewPlan


@dataclass
class ResubmitPlan:
    collection: Collection
    submission_group: str
    regenerate: bool
    items: List[Dict[str, Any]]
    skipped: List[Dict[str, Any]]
    resubmit_generator: Optional[JobGenerator]
    generation_context: Optional[Dict[str, Any]]
    review: ReviewPlan


def plan_generate(
    *,
    config: Config,
    manager: CollectionManager,
    spec_path: Path,
    collection_name: str,
) -> GeneratePlan:
    spec_data = load_job_spec(spec_path)
    existing_collection = manager.load(collection_name) if manager.exists(collection_name) else None
    generator = JobGenerator.from_spec(spec_path, config=config)
    job_paths = resolve_job_paths_from_spec(config=config, spec_data=spec_data)
    scripts_dir = job_paths["scripts_dir"]
    logs_dir = job_paths["logs_dir"]
    job_subdir = str(job_paths["job_subdir"])
    items = generator.plan(output_dir=scripts_dir, collection=existing_collection)
    renamed = [
        f"{item['base_job_name']} -> {item['job_name']}"
        for item in items
        if item["base_job_name"] != item["job_name"]
    ]
    review_items = [item["job_name"] for item in items[:10]]
    if len(items) > 10:
        review_items.append(f"... and {len(items) - 10} more")
    if renamed:
        review_items.extend(f"rename {entry}" for entry in renamed[:5])
    review = format_review(
        "Generation plan",
        [
            f"Spec: {spec_path}",
            f"Collection: {collection_name} ({'existing' if existing_collection else 'new'})",
            f"Job subdir: {job_subdir}",
            f"Scripts dir: {scripts_dir}",
            f"Logs dir: {logs_dir}",
            f"Jobs to generate: {len(items)}",
            "Mode: append-only",
        ] + ([f"Renamed for collisions: {len(renamed)}"] if renamed else []),
        review_items,
    )
    return GeneratePlan(
        spec_path=spec_path,
        spec_data=spec_data,
        generator=generator,
        collection_name=collection_name,
        existing_collection=existing_collection,
        job_subdir=job_subdir,
        scripts_dir=scripts_dir,
        logs_dir=logs_dir,
        items=items,
        review=review,
    )


def execute_generate(
    *,
    config: Config,
    manager: CollectionManager,
    plan: GeneratePlan,
    dry_run: bool,
) -> Dict[str, Any]:
    preview = None
    if plan.items:
        first = plan.items[0]
        preview = plan.generator.render_script(first["parameters"], first["job_name"])

    if dry_run or not plan.items:
        return {
            "generated_count": 0 if dry_run else len(plan.items),
            "preview": preview,
            "collection": None,
        }

    collection = manager.get_or_create(
        plan.collection_name,
        description=plan.spec_data.get("description", ""),
    )
    generated = plan.generator.generate(
        output_dir=plan.scripts_dir,
        collection=collection,
        dry_run=False,
    )
    collection.parameters = plan.spec_data.get("parameters", {})
    if plan.spec_data.get("description"):
        collection.description = plan.spec_data.get("description", "")
    collection.generation = build_generation_metadata(
        generator=plan.generator,
        scripts_dir=plan.scripts_dir,
        logs_dir=plan.logs_dir,
        job_subdir=plan.job_subdir,
        spec_path=plan.spec_path,
        project_root=getattr(config, "project_root", None),
    )
    manager.save(collection)
    return {
        "generated_count": len(generated),
        "preview": preview,
        "collection": collection,
    }


def plan_submit_collection(
    *,
    collection: Collection,
    filter_name: str,
) -> SubmitPlan:
    if filter_name == "unsubmitted":
        items = [
            {
                "job_name": job["job_name"],
                "path": Path(job["attempts"][0]["script_path"]),
                "job": job,
            }
            for job in collection.jobs
            if job["attempts"][0].get("script_path") and job["attempts"][0].get("job_id") is None
        ]
    else:
        items = [
            {
                "job_name": job["job_name"],
                "path": Path(job["attempts"][0]["script_path"]),
                "job": job,
            }
            for job in collection.jobs
            if job["attempts"][0].get("script_path")
        ]
    review = format_review(
        "Submit plan",
        [
            f"Collection: {collection.name}",
            f"Target scope: {filter_name}",
            f"Jobs to submit: {len(items)}",
        ],
        [f"{item['job_name']}: {item['path']}" for item in items[:10]],
    )
    return SubmitPlan(
        collection=collection,
        filter_name=filter_name,
        items=items,
        review=review,
    )


def execute_submit_collection(
    *,
    manager: CollectionManager,
    plan: SubmitPlan,
    delay: float,
    dry_run: bool,
) -> Dict[str, Any]:
    submitted = 0
    results: List[Dict[str, Any]] = []
    for index, item in enumerate(plan.items):
        success, job_id, message = submit_job(item["path"], dry_run=dry_run)
        results.append(
            {
                "job_name": item["job_name"],
                "success": success,
                "job_id": job_id,
                "message": message,
            }
        )
        if success:
            submitted += 1
            if not dry_run:
                plan.collection.update_job(
                    item["job_name"],
                    job_id=job_id,
                    submitted_at=datetime.now().isoformat(timespec="seconds"),
                )
        if delay > 0 and index < len(plan.items) - 1 and not dry_run:
            time.sleep(delay)

    if not dry_run and submitted:
        manager.save(plan.collection)

    return {
        "submitted_count": submitted,
        "results": results,
    }


def _resolve_resubmit_jobs(collection: Collection, filter_name: str) -> List[Dict[str, Any]]:
    if filter_name == "failed":
        return [
            row["job"]
            for row in collection.get_effective_jobs(attempt_mode="latest", state=JOB_STATE_FAILED)
        ]
    return list(collection.jobs)


def plan_resubmit_collection(
    *,
    config: Config,
    collection: Collection,
    filter_name: str,
    template: Optional[Path],
    extra_params: Optional[str],
    extra_params_file: Optional[Path],
    extra_params_function: str,
    select_file: Optional[Path],
    select_function: str,
    submission_group: Optional[str],
    regenerate: Optional[bool],
) -> ResubmitPlan:
    collection.refresh_states()
    static_extra_params = parse_key_value_pairs(extra_params)
    resolved_regenerate = True if regenerate is None else bool(regenerate)
    group_name = submission_group or datetime.now().strftime("resubmit_%Y%m%d_%H%M%S")

    extra_params_callback = load_python_callback(
        extra_params_file,
        extra_params_function,
        callback_kind="extra_params",
    )
    select_callback = load_python_callback(
        select_file,
        select_function,
        callback_kind="selection",
    )

    jobs_to_consider = _resolve_resubmit_jobs(collection, filter_name)
    generation_context: Optional[Dict[str, Any]] = None
    resubmit_generator: Optional[JobGenerator] = None
    if resolved_regenerate:
        generation_context = resolve_generation_context(
            collection,
            template_override=template,
        )
        resubmit_generator = JobGenerator(
            template_path=generation_context["template_path"],
            parameters={"mode": "list", "values": []},
            slurm_defaults=generation_context["slurm_defaults"],
            slurm_logic_file=generation_context["slurm_logic_file"],
            slurm_logic_function=generation_context["slurm_logic_function"],
            job_name_pattern=generation_context["job_name_pattern"],
            logs_dir=generation_context["logs_dir"],
            config=config,
        )

    items: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for job in jobs_to_consider:
        latest_attempt = job["attempts"][-1]
        callback_context = {
            "job_name": job["job_name"],
            "script_path": latest_attempt.get("script_path"),
            "original_job_id": latest_attempt.get("job_id"),
            "collection_name": collection.name,
            "collection_job": job,
            "submission_group": group_name,
            "static_extra_params": static_extra_params.copy(),
        }

        reason = None
        if select_callback is not None:
            decision = select_callback(callback_context.copy())
            if isinstance(decision, bool):
                include_job = decision
            elif (
                isinstance(decision, tuple)
                and len(decision) == 2
                and isinstance(decision[0], bool)
            ):
                include_job = decision[0]
                reason = "" if decision[1] is None else str(decision[1])
            else:
                raise ValueError(
                    "selection callback must return bool or (bool, reason)"
                )
            if not include_job:
                skipped.append({"job_name": job["job_name"], "reason": reason})
                continue

        dynamic_extra_params: Dict[str, Any] = {}
        if extra_params_callback is not None:
            callback_result = extra_params_callback(callback_context.copy())
            if callback_result is None:
                callback_result = {}
            if not isinstance(callback_result, dict):
                raise ValueError("extra params callback must return a dict")
            dynamic_extra_params = dict(callback_result)

        resolved_extra_params = dict(dynamic_extra_params)
        resolved_extra_params.update(static_extra_params)

        attempt_script_path = Path(str(latest_attempt.get("script_path") or ""))
        attempt_job_name = job["job_name"]
        effective_params = dict(job.get("parameters", {}) or {})
        effective_params.update(resolved_extra_params)

        if resolved_regenerate:
            resubmit_count = max(len(job["attempts"]) - 1, 0) + 1
            attempt_job_name = f"{job['job_name']}.resubmit-{resubmit_count}"
            attempt_script_path = generation_context["scripts_dir"] / f"{attempt_job_name}.job"

        items.append(
            {
                "job": job,
                "job_name": job["job_name"],
                "original_job_id": latest_attempt.get("job_id"),
                "resolved_extra_params": resolved_extra_params,
                "regenerated": resolved_regenerate,
                "attempt_job_name": attempt_job_name,
                "attempt_script_path": attempt_script_path,
                "effective_params": effective_params,
            }
        )

    review_items = []
    for item in items[:10]:
        review_items.append(f"{item['job_name']} (original ID: {item['original_job_id']})")
        if item["resolved_extra_params"]:
            review_items.append(f"extra params: {item['resolved_extra_params']}")
    if skipped:
        review_items.extend(
            f"skip {item['job_name']}{': ' + item['reason'] if item.get('reason') else ''}"
            for item in skipped[:5]
        )

    review = format_review(
        "Resubmit plan",
        [
            f"Collection: {collection.name}",
            f"Target scope: {filter_name}",
            f"Regenerate scripts: {'yes' if resolved_regenerate else 'no'}",
            f"Submission group: {group_name}",
            f"Jobs to resubmit: {len(items)}",
        ],
        review_items,
    )
    return ResubmitPlan(
        collection=collection,
        submission_group=group_name,
        regenerate=resolved_regenerate,
        items=items,
        skipped=skipped,
        resubmit_generator=resubmit_generator,
        generation_context=generation_context,
        review=review,
    )


def execute_resubmit_collection(
    *,
    manager: CollectionManager,
    plan: ResubmitPlan,
    dry_run: bool,
) -> Dict[str, Any]:
    resubmitted = 0
    results = []

    for item in plan.items:
        attempt_script_path = item["attempt_script_path"]
        if item["regenerated"]:
            assert plan.resubmit_generator is not None
            plan.resubmit_generator.generate_one(
                output_dir=plan.generation_context["scripts_dir"],
                params=item["effective_params"],
                job_name=item["attempt_job_name"],
                dry_run=dry_run,
            )

        success, job_id, message = submit_job(attempt_script_path, dry_run=dry_run)
        results.append(
            {
                "job_name": item["job_name"],
                "success": success,
                "job_id": job_id,
                "message": message,
            }
        )
        if success:
            resubmitted += 1
            if not dry_run:
                plan.collection.add_resubmission(
                    item["job_name"],
                    job_id=str(job_id),
                    extra_params=item["resolved_extra_params"],
                    submission_group=plan.submission_group,
                    attempt_job_name=item["attempt_job_name"],
                    attempt_script_path=attempt_script_path,
                    attempt_parameters=item["effective_params"] if item["regenerated"] else item["job"].get("parameters", {}),
                    regenerated=item["regenerated"],
                )

    if not dry_run and resubmitted:
        manager.save(plan.collection)

    return {
        "resubmitted_count": resubmitted,
        "results": results,
        "skipped": plan.skipped,
    }
