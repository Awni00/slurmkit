"""Top-level generation, submission, resubmission, and status commands."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from slurmkit.collections import CollectionManager
from slurmkit.generate import render_job_spec_template

from .helpers import resolve_collection_name, resolve_spec_path, resolve_target_collection_for_generate
from .prompts import canceled, prompt_confirm
from .rendering import print_json, print_review, render_collection_show
from .runtime import can_prompt, get_state, is_structured_format
from .ui import resolve_ui_context
from slurmkit.workflows.collections import show_collection
from slurmkit.workflows.jobs import (
    execute_generate,
    execute_resubmit_collection,
    execute_submit_collection,
    plan_generate,
    plan_resubmit_collection,
    plan_submit_collection,
)


def register(app: typer.Typer) -> None:
    @app.command("spec-template")
    def spec_template_command(
        ctx: typer.Context,
        output: Path = typer.Option(
            Path("job_spec.yaml"),
            "--output",
            "-o",
            help="Path to write the spec template.",
        ),
        force: bool = typer.Option(False, "--force", help="Overwrite existing output file."),
    ) -> None:
        state = get_state(ctx)
        destination = Path(output)
        if destination.exists() and not force:
            raise typer.BadParameter(
                f"Output file already exists: {destination}. Use --force to overwrite."
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            render_job_spec_template(config=state.config),
            encoding="utf-8",
        )
        typer.echo(f"Spec template written to: {destination}")
        raise typer.Exit(0)

    @app.command("generate")
    def generate_command(
        ctx: typer.Context,
        spec: Optional[Path] = typer.Argument(None, help="Path to a job spec YAML file."),
        into: Optional[str] = typer.Option(None, "--into", help="Target collection name."),
        dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing scripts."),
    ) -> None:
        state = get_state(ctx)
        manager = CollectionManager(config=state.config)
        spec_path = resolve_spec_path(state, spec)
        if not spec_path.exists():
            raise typer.BadParameter(f"Spec file not found: {spec_path}")
        collection_name, _spec_data = resolve_target_collection_for_generate(
            state,
            manager,
            into=into,
            spec_path=spec_path,
        )
        plan = plan_generate(
            config=state.config,
            manager=manager,
            spec_path=spec_path,
            collection_name=collection_name,
        )
        print_review(plan.review)
        if not dry_run and can_prompt(state):
            confirmed = prompt_confirm("Generate these job scripts?", default=True)
            if confirmed is None or not confirmed:
                raise typer.Exit(canceled())
        result = execute_generate(
            config=state.config,
            manager=manager,
            plan=plan,
            dry_run=dry_run,
        )
        if dry_run:
            show_preview = False
            if can_prompt(state):
                confirmed = prompt_confirm("Show preview of first job?", default=False)
                if confirmed is None:
                    raise typer.Exit(canceled())
                show_preview = confirmed
            if show_preview and result["preview"] is not None:
                typer.echo("")
                typer.echo("[DRY RUN] Preview of first job:")
                typer.echo("-" * 80)
                typer.echo(str(result["preview"]).rstrip())
                typer.echo("-" * 80)
            raise typer.Exit(0)
        typer.echo(f"Generated {result['generated_count']} job script(s) into collection '{collection_name}'.")
        raise typer.Exit(0)

    @app.command("submit")
    def submit_command(
        ctx: typer.Context,
        collection: Optional[str] = typer.Argument(None, help="Collection name."),
        filter_name: str = typer.Option("unsubmitted", "--filter", help="Submit unsubmitted jobs or all jobs."),
        delay: float = typer.Option(0.0, "--delay", help="Delay in seconds between submissions."),
        dry_run: bool = typer.Option(False, "--dry-run", help="Preview without submitting."),
        yes: bool = typer.Option(False, "-y", "--yes", help="Skip confirmation prompt."),
    ) -> None:
        state = get_state(ctx)
        manager = CollectionManager(config=state.config)
        collection_name = resolve_collection_name(
            state,
            manager,
            collection,
            prompt_title="Select a collection to submit",
        )
        target = manager.load(collection_name)
        plan = plan_submit_collection(collection=target, filter_name=filter_name)
        print_review(plan.review)
        if not dry_run and not yes and can_prompt(state):
            confirmed = prompt_confirm("Submit jobs now?", default=True)
            if confirmed is None or not confirmed:
                raise typer.Exit(canceled())
        result = execute_submit_collection(
            manager=manager,
            plan=plan,
            delay=delay,
            dry_run=dry_run,
        )
        typer.echo(f"Submitted {result['submitted_count']}/{len(plan.items)} job(s).")
        raise typer.Exit(0)

    @app.command("resubmit")
    def resubmit_command(
        ctx: typer.Context,
        collection: Optional[str] = typer.Argument(None, help="Collection name."),
        job_id: Optional[str] = typer.Option(
            None,
            "--job-id",
            help="Resubmit one logical job by a tracked SLURM job ID.",
        ),
        filter_name: str = typer.Option("failed", "--filter", help="Resubmit failed jobs or all jobs."),
        template: Optional[Path] = typer.Option(None, "--template", help="Override template for regenerated scripts."),
        extra_params: Optional[str] = typer.Option(None, "--extra-params", help="Comma-separated KEY=VAL overrides."),
        extra_params_file: Optional[Path] = typer.Option(None, "--extra-params-file", help="Python file with get_extra_params(context)->dict."),
        extra_params_function: str = typer.Option("get_extra_params", "--extra-params-function", help="Extra params callback name."),
        select_file: Optional[Path] = typer.Option(None, "--select-file", help="Python file with should_resubmit(context)->bool."),
        select_function: str = typer.Option("should_resubmit", "--select-function", help="Selection callback name."),
        submission_group: Optional[str] = typer.Option(None, "--submission-group", help="Submission group label."),
        regenerate: Optional[bool] = typer.Option(None, "--regenerate/--no-regenerate", help="Regenerate scripts before submission."),
        dry_run: bool = typer.Option(False, "--dry-run", help="Preview without resubmitting."),
        yes: bool = typer.Option(False, "-y", "--yes", help="Skip confirmation prompt."),
    ) -> None:
        state = get_state(ctx)
        manager = CollectionManager(config=state.config)
        target_job_names = None
        if job_id is None:
            collection_name = resolve_collection_name(
                state,
                manager,
                collection,
                prompt_title="Select a collection to resubmit",
            )
            target = manager.load(collection_name)
        else:
            if filter_name != "failed":
                raise typer.BadParameter(
                    "`--filter` cannot be used with `--job-id` (only the default `failed` scope is supported).",
                    param_hint="--filter",
                )
            if select_file is not None:
                raise typer.BadParameter(
                    "`--select-file` cannot be used with `--job-id`.",
                    param_hint="--select-file",
                )
            if select_function != "should_resubmit":
                raise typer.BadParameter(
                    "`--select-function` cannot be used with `--job-id`.",
                    param_hint="--select-function",
                )
            resolution = manager.resolve_job_id(job_id, collection_name=collection)
            if collection and any(warning == f"Collection '{collection}' was not found." for warning in resolution.warnings):
                raise typer.BadParameter(
                    f"Collection '{collection}' was not found.",
                    param_hint="collection",
                )
            for warning in resolution.warnings:
                typer.echo(f"Warning: {warning}", err=True)
            if not resolution.matches:
                if collection:
                    raise typer.BadParameter(
                        f"Job ID '{job_id}' was not found in collection '{collection}'.",
                        param_hint="--job-id",
                    )
                raise typer.BadParameter(
                    f"No collection found for job ID '{job_id}'.",
                    param_hint="--job-id",
                )
            if len(resolution.matches) > 1:
                names = ", ".join(sorted(match.collection_name for match in resolution.matches))
                raise typer.BadParameter(
                    f"Job ID '{job_id}' matched multiple collections ({names}). "
                    "Pass the collection positional argument to disambiguate.",
                    param_hint="--job-id",
                )
            match = resolution.matches[0]
            target = match.collection
            target_job_names = [str(match.job["job_name"])]
        plan = plan_resubmit_collection(
            config=state.config,
            collection=target,
            filter_name=filter_name,
            template=template,
            extra_params=extra_params,
            extra_params_file=extra_params_file,
            extra_params_function=extra_params_function,
            select_file=select_file,
            select_function=select_function,
            submission_group=submission_group,
            regenerate=regenerate,
            target_job_names=target_job_names,
        )
        manager.save(target)
        print_review(plan.review)
        for warning in plan.warnings:
            typer.echo(f"Warning: {warning}", err=True)
        if not dry_run and not yes and can_prompt(state):
            confirmed = prompt_confirm("Resubmit jobs now?", default=True)
            if confirmed is None or not confirmed:
                raise typer.Exit(canceled())
        result = execute_resubmit_collection(
            manager=manager,
            plan=plan,
            dry_run=dry_run,
        )
        typer.echo(f"Resubmitted {result['resubmitted_count']}/{len(plan.items)} job(s).")
        raise typer.Exit(0)

    @app.command("status")
    def status_command(
        ctx: typer.Context,
        collection: Optional[str] = typer.Argument(None, help="Collection name."),
        json_mode: bool = typer.Option(False, "--json", help="Emit JSON output."),
    ) -> None:
        state = get_state(ctx)
        manager = CollectionManager(config=state.config)
        collection_name = resolve_collection_name(
            state,
            manager,
            collection,
            prompt_title="Select a collection to inspect",
            structured_output=json_mode,
        )
        rendered = show_collection(
            config=state.config,
            manager=manager,
            name=collection_name,
            refresh=True,
            state_filter="all",
            json_mode=json_mode,
            attempt_mode="latest",
            include_jobs_table=False,
            include_jobs_in_payload=False,
            compact_payload=True,
        )
        if json_mode:
            print_json(rendered.payload)
            raise typer.Exit(0)
        render_collection_show(args=type("Args", (), {"ui": state.ui})(), config=state.config, report=rendered.report)
        raise typer.Exit(0)
