"""
Command handlers for slurmkit CLI.

This module contains the implementation of each CLI command.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
import pandas as pd
from tabulate import tabulate

from slurmkit.config import Config, get_config, init_config
from slurmkit.collections import (
    Collection,
    CollectionManager,
    DEFAULT_COLLECTION_NAME,
)
from slurmkit.slurm import (
    find_job_output,
    get_jobs_data,
    get_sacct_info,
    infer_script_path,
    parse_elapsed_to_seconds,
    parse_timestamp,
    submit_job,
)
from slurmkit.generate import (
    JobGenerator,
    generate_jobs_from_spec,
    load_job_spec,
    expand_parameters,
    resolve_parameters_filter_spec,
)
from slurmkit.sync import SyncManager


# =============================================================================
# Helper Functions
# =============================================================================

def prompt_yes_no(message: str) -> bool:
    """Prompt user for yes/no confirmation."""
    answer = input(message).strip().lower()
    return answer in ("y", "yes")


def print_separator(char: str = "-", width: int = 80) -> None:
    """Print a separator line."""
    print(char * width)


def get_configured_config(args: Any) -> Config:
    """Get Config instance with CLI overrides."""
    config_path = getattr(args, "config", None)
    return get_config(config_path=config_path, reload=True)


# =============================================================================
# init Command
# =============================================================================

def cmd_init(args: Any) -> int:
    """Initialize project configuration."""
    config_path = Path(".slurm-kit/config.yaml")

    if config_path.exists() and not args.force:
        print(f"Configuration file already exists: {config_path}")
        if not prompt_yes_no("Overwrite? [y/N]: "):
            print("Aborted.")
            return 0

    print("Initializing slurmkit configuration...\n")

    # Interactive prompts for key settings
    print("Enter configuration values (press Enter for defaults):\n")

    # Jobs directory
    jobs_dir = input("Jobs directory [jobs/]: ").strip() or "jobs/"

    # SLURM defaults
    print("\nSLURM defaults:")
    partition = input("  Default partition [compute]: ").strip() or "compute"
    time_limit = input("  Default time limit [24:00:00]: ").strip() or "24:00:00"
    memory = input("  Default memory [16G]: ").strip() or "16G"

    # W&B settings (optional)
    print("\nW&B settings (optional, press Enter to skip):")
    wandb_entity = input("  W&B entity: ").strip() or None

    # Build config
    config_data = {
        "jobs_dir": jobs_dir,
        "collections_dir": ".job-collections/",
        "sync_dir": ".slurm-kit/sync/",
        "output_patterns": [
            "{job_name}.{job_id}.out",
            "{job_name}.{job_id}.*.out",
            "slurm-{job_id}.out",
        ],
        "slurm_defaults": {
            "partition": partition,
            "time": time_limit,
            "mem": memory,
            "nodes": 1,
            "ntasks": 1,
        },
        "job_structure": {
            "scripts_subdir": "job_scripts/",
            "logs_subdir": "logs/",
        },
        "cleanup": {
            "threshold_seconds": 300,
            "min_age_days": 3,
        },
    }

    if wandb_entity:
        config_data["wandb"] = {
            "entity": wandb_entity,
            "default_projects": [],
        }

    # Write config
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)

    print(f"\nConfiguration saved to: {config_path}")
    print("\nYou can edit this file to customize settings.")
    return 0


# =============================================================================
# status Command
# =============================================================================

def cmd_status(args: Any) -> int:
    """Show job status for an experiment."""
    config = get_configured_config(args)

    # Resolve jobs directory
    if args.jobs_dir:
        jobs_dir = Path(args.jobs_dir)
    else:
        jobs_dir = config.get_path("jobs_dir")

    # If experiment not specified, scan all jobs
    if args.experiment:
        target_dir = jobs_dir / args.experiment
        experiment_label = args.experiment
    else:
        target_dir = jobs_dir
        experiment_label = "all jobs"

    if not target_dir.exists():
        print(f"Error: Directory not found: {target_dir}")
        return 1

    # Get job data
    jobs_data = get_jobs_data(
        target_dir,
        include_sacct_info=True,
        include_pending=True,
        config=config,
    )

    if not jobs_data:
        print(f"No job files found in {target_dir}")
        return 0

    # Convert to DataFrame for easy manipulation
    df = pd.DataFrame(jobs_data)

    # Rename columns for display
    column_map = {
        "job_name": "Job Name",
        "job_id": "Job ID",
        "state": "State",
        "start": "Start",
        "elapsed": "Elapsed",
        "wait_time": "Wait Time",
    }

    # Select columns to display
    display_cols = ["job_name", "job_id", "state", "start", "elapsed"]
    if "wait_time" in df.columns:
        display_cols.append("wait_time")

    # Filter columns that exist
    display_cols = [c for c in display_cols if c in df.columns]

    # Apply state filter
    if args.state != "all":
        state_map = {
            "pending": ["PENDING", "REQUEUED", "SUSPENDED"],
            "running": ["RUNNING", "COMPLETING"],
            "completed": ["COMPLETED"],
            "failed": ["FAILED", "CANCELLED", "TIMEOUT", "NODE_FAIL", "PREEMPTED", "OUT_OF_MEMORY"],
        }
        valid_states = state_map.get(args.state, [])
        df = df[df["state"].str.upper().isin(valid_states)]

    if df.empty:
        print(f"No jobs matching state '{args.state}' found.")
        return 0

    # Sort by job name and ID
    df = df.sort_values(by=["job_name", "job_id"])

    # Output format
    if args.format == "json":
        print(df[display_cols].to_json(orient="records", indent=2))
    elif args.format == "csv":
        print(df[display_cols].to_csv(index=False))
    else:
        # Table format
        print(f"Status for: {experiment_label}")
        print_separator()

        # Rename columns for display
        df_display = df[display_cols].rename(columns=column_map)
        print(tabulate(df_display, headers="keys", tablefmt="simple", showindex=False))

        print_separator()

        # Summary
        state_counts = df["state"].value_counts()
        print(f"\nSummary: {len(df)} jobs")
        for state, count in state_counts.items():
            print(f"  {state}: {count}")

    return 0


# =============================================================================
# find Command
# =============================================================================

def cmd_find(args: Any) -> int:
    """Find job output file by job ID."""
    config = get_configured_config(args)

    # Resolve jobs directory
    if args.jobs_dir:
        jobs_dir = Path(args.jobs_dir)
    else:
        jobs_dir = config.get_path("jobs_dir")

    # Get sacct info
    print("[sacct] Job info:")
    info = get_sacct_info([args.job_id])
    if args.job_id in info:
        for field, value in info[args.job_id].items():
            print(f"  {field}: {value}")
    else:
        print("  (no sacct info available)")
    print()

    # Find output files
    matches = find_job_output(args.job_id, jobs_dir, config)

    if not matches:
        print(f"No .out file found for job ID '{args.job_id}'")
        return 1

    if len(matches) > 1:
        print(f"Multiple .out files found for job ID '{args.job_id}':")
        for p in matches:
            print(f"  - {p}")
        return 2

    # Single match
    output_path = matches[0]
    print(f"Output file: {output_path}")
    print()

    # Open in editor if requested
    if args.open:
        editor = os.environ.get("EDITOR", "less")
        subprocess.run([editor, str(output_path)])
        return 0

    # Preview if requested
    if args.preview:
        try:
            lines = output_path.read_text().splitlines()
        except OSError as e:
            print(f"Error reading file: {e}")
            return 1

        print_separator()
        if len(lines) <= args.lines * 2:
            print("\n".join(lines))
        else:
            print("\n".join(lines[:args.lines]))
            print(f"\n... ({len(lines) - args.lines * 2} lines omitted) ...\n")
            print("\n".join(lines[-args.lines:]))
        print_separator()

    return 0


# =============================================================================
# clean outputs Command
# =============================================================================

def cmd_clean_outputs(args: Any) -> int:
    """Clean failed job output files."""
    config = get_configured_config(args)

    # Resolve jobs directory
    if args.jobs_dir:
        jobs_dir = Path(args.jobs_dir)
    else:
        jobs_dir = config.get_path("jobs_dir")

    target_dir = jobs_dir / args.experiment

    if not target_dir.exists():
        print(f"Error: Directory not found: {target_dir}")
        return 1

    # Get job data
    jobs_data = get_jobs_data(
        target_dir,
        include_sacct_info=True,
        sacct_fields=["JobID", "State", "Elapsed", "End"],
        include_pending=False,
        config=config,
    )

    if not jobs_data:
        print(f"No job files found in {target_dir}")
        return 0

    # Calculate age cutoff
    from datetime import timedelta
    age_cutoff = datetime.now() - timedelta(days=args.min_age)

    # Build file path map
    file_path_map = {f.name: f for f in target_dir.rglob("*.out")}

    # Filter for failed jobs with short runtimes
    files_to_delete = []

    for job in jobs_data:
        state = job.get("state", "")
        if state != "FAILED":
            continue

        elapsed = job.get("elapsed", "")
        elapsed_seconds = parse_elapsed_to_seconds(elapsed)
        if elapsed_seconds < 0:
            continue

        end_time_str = job.get("end", "")
        end_time = parse_timestamp(end_time_str)
        if end_time is None:
            continue
        if end_time > age_cutoff:
            continue

        if elapsed_seconds <= args.threshold:
            output_file = job.get("output_file")
            if output_file and output_file.name in file_path_map:
                files_to_delete.append({
                    "path": file_path_map[output_file.name],
                    "job_name": job.get("job_name", ""),
                    "job_id": job.get("job_id", ""),
                    "elapsed": elapsed,
                })

    if not files_to_delete:
        print(f"No failed jobs with elapsed time <= {args.threshold}s "
              f"and age >= {args.min_age} days found.")
        return 0

    # Display files
    print(f"Found {len(files_to_delete)} file(s) to delete:")
    print_separator()
    for f in files_to_delete:
        print(f"  {f['job_name']} (ID: {f['job_id']}, Elapsed: {f['elapsed']})")
        print(f"    -> {f['path']}")
    print_separator()

    if args.dry_run:
        print("\n[DRY RUN] No files were deleted.")
        return 0

    # Confirm
    if not args.yes:
        if not prompt_yes_no(f"\nDelete these {len(files_to_delete)} file(s)? [y/N]: "):
            print("Aborted.")
            return 0

    # Delete files
    deleted = 0
    for f in files_to_delete:
        try:
            f["path"].unlink()
            deleted += 1
            print(f"Deleted: {f['path'].name}")
        except OSError as e:
            print(f"Error deleting {f['path']}: {e}", file=sys.stderr)

    print(f"\nDeleted {deleted}/{len(files_to_delete)} file(s).")
    return 0


# =============================================================================
# clean wandb Command
# =============================================================================

def cmd_clean_wandb(args: Any) -> int:
    """Clean failed W&B runs."""
    config = get_configured_config(args)

    # Import wandb utilities (may fail if wandb not installed)
    try:
        from slurmkit.wandb_utils import clean_failed_runs, format_runs_table, get_failed_runs
    except ImportError as e:
        print(f"Error: wandb is not installed. Install it with: pip install wandb")
        return 1

    # Get projects
    projects = args.projects
    if not projects:
        projects = config.get("wandb.default_projects", [])
        if not projects:
            print("Error: No projects specified. Use --projects or set wandb.default_projects in config.")
            return 1

    entity = args.entity or config.get("wandb.entity")

    print(f"Scanning for failed runs (runtime <= {args.threshold}s, age >= {args.min_age} days)...")
    print_separator()

    # Collect failed runs
    all_failed_runs = []
    for project in projects:
        print(f"\nProject: {project}")
        try:
            failed_runs = get_failed_runs(
                project=project,
                entity=entity,
                threshold_seconds=args.threshold,
                min_age_days=args.min_age,
                config=config,
            )
            for run_info in failed_runs:
                run_info["project"] = project
            all_failed_runs.extend(failed_runs)
            print(f"  Found {len(failed_runs)} failed run(s)")
        except Exception as e:
            print(f"  Error: {e}", file=sys.stderr)

    print_separator()

    if not all_failed_runs:
        print(f"\nNo failed runs matching criteria found.")
        return 0

    # Display runs
    print(f"\nFound {len(all_failed_runs)} run(s) to delete:\n")
    print(format_runs_table(all_failed_runs))

    if args.dry_run:
        print("\n[DRY RUN] No runs were deleted.")
        return 0

    # Confirm
    if not args.yes:
        if not prompt_yes_no(f"\nDelete these {len(all_failed_runs)} run(s)? [y/N]: "):
            print("Aborted.")
            return 0

    # Delete runs
    deleted = 0
    for run_info in all_failed_runs:
        try:
            run_obj = run_info["_run_obj"]
            run_obj.delete()
            deleted += 1
            print(f"Deleted: {run_info.get('name', 'unknown')}")
        except Exception as e:
            print(f"Error deleting {run_info.get('name', 'unknown')}: {e}", file=sys.stderr)

    print(f"\nDeleted {deleted}/{len(all_failed_runs)} run(s).")
    return 0


# =============================================================================
# generate Command
# =============================================================================

def cmd_generate(args: Any) -> int:
    """Generate job scripts from template."""
    config = get_configured_config(args)

    # Determine collection name
    collection_name = args.collection
    if collection_name is None:
        collection_name = DEFAULT_COLLECTION_NAME
        print(f"Note: No collection specified. Using '{DEFAULT_COLLECTION_NAME}' collection.")

    # Check for spec file or template+params
    if args.spec_file:
        spec_path = Path(args.spec_file)
        if not spec_path.exists():
            print(f"Error: Spec file not found: {spec_path}")
            return 1

        # Load spec
        spec = load_job_spec(spec_path)

        # Determine output directory
        if args.output_dir:
            output_dir = Path(args.output_dir)
        else:
            output_dir = spec.get("output_dir", ".")
            if not Path(output_dir).is_absolute():
                output_dir = spec_path.parent / output_dir

        # Create generator
        generator = JobGenerator.from_spec(spec_path, config=config)

    elif args.template and args.params:
        template_path = Path(args.template)
        params_path = Path(args.params)

        if not template_path.exists():
            print(f"Error: Template file not found: {template_path}")
            return 1
        if not params_path.exists():
            print(f"Error: Parameters file not found: {params_path}")
            return 1

        # Load parameters
        with open(params_path, "r") as f:
            parameters = yaml.safe_load(f) or {}

        parameters_for_gen = resolve_parameters_filter_spec(
            parameters,
            base_dir=params_path.parent,
        )

        # Determine output directory
        output_dir = Path(args.output_dir) if args.output_dir else Path(".")

        # Create generator
        generator = JobGenerator(
            template_path=template_path,
            parameters=parameters_for_gen,
            slurm_defaults=config.get_slurm_defaults(),
            slurm_logic_file=args.slurm_args_file,
            config=config,
        )

    else:
        print("Error: Specify either a spec file or --template and --params.")
        return 1

    # Preview what will be generated
    job_count = generator.count_jobs()
    job_names = generator.list_job_names()

    print(f"\nWill generate {job_count} job script(s) in: {output_dir}")
    print(f"Collection: {collection_name}")
    print("\nJob names:")
    for name in job_names[:10]:
        print(f"  - {name}")
    if len(job_names) > 10:
        print(f"  ... and {len(job_names) - 10} more")

    if args.dry_run:
        print("\n[DRY RUN] Preview of first job:\n")
        print_separator()
        print(generator.preview(0))
        print_separator()
        return 0

    # Generate jobs
    manager = CollectionManager(config=config)
    collection = manager.get_or_create(
        collection_name,
        description=spec.get("description", "") if args.spec_file else "",
    )

    result = generator.generate(
        output_dir=output_dir,
        collection=collection,
        dry_run=False,
    )

    # Update collection with generation parameters
    if args.spec_file:
        spec = load_job_spec(Path(args.spec_file))
        collection.parameters = spec.get("parameters", {})
    else:
        with open(params_path, "r") as f:
            collection.parameters = yaml.safe_load(f) or {}

    manager.save(collection)

    print(f"\nGenerated {len(result)} job script(s).")
    print(f"Collection '{collection_name}' updated with {len(collection)} job(s).")

    return 0


# =============================================================================
# submit Command
# =============================================================================

def cmd_submit(args: Any) -> int:
    """Submit job scripts."""
    config = get_configured_config(args)
    manager = CollectionManager(config=config)

    scripts_to_submit = []

    # Collect scripts to submit
    if args.collection and not args.paths:
        # Submit from collection
        if not manager.exists(args.collection):
            print(f"Error: Collection not found: {args.collection}")
            return 1

        collection = manager.load(args.collection)

        # Filter jobs
        if args.filter == "pending":
            jobs = collection.filter_jobs(submitted=False)
        else:
            jobs = collection.jobs

        for job in jobs:
            script_path = job.get("script_path")
            if script_path and Path(script_path).exists():
                scripts_to_submit.append({
                    "path": Path(script_path),
                    "job_name": job.get("job_name"),
                    "collection_job": job,
                })

    else:
        # Submit from paths
        for path_str in args.paths:
            path = Path(path_str)

            if path.is_dir():
                # Submit all .job files in directory
                for script in sorted(path.glob("*.job")):
                    scripts_to_submit.append({
                        "path": script,
                        "job_name": script.stem,
                    })
            elif path.exists():
                scripts_to_submit.append({
                    "path": path,
                    "job_name": path.stem,
                })
            else:
                print(f"Warning: Path not found: {path}")

    if not scripts_to_submit:
        print("No job scripts to submit.")
        return 0

    # Display scripts
    print(f"Will submit {len(scripts_to_submit)} job(s):")
    print_separator()
    for script in scripts_to_submit:
        print(f"  {script['job_name']}: {script['path']}")
    print_separator()

    if args.dry_run:
        print("\n[DRY RUN] No jobs were submitted.")
        return 0

    # Confirm
    if not args.yes:
        if not prompt_yes_no(f"\nSubmit these {len(scripts_to_submit)} job(s)? [y/N]: "):
            print("Aborted.")
            return 0

    # Get or create collection for tracking
    collection = None
    if args.collection:
        collection = manager.get_or_create(args.collection)

    # Submit jobs
    submitted = 0
    for i, script in enumerate(scripts_to_submit):
        success, job_id, message = submit_job(script["path"], dry_run=False)

        if success:
            print(f"Submitted: {script['job_name']} -> {message}")
            submitted += 1

            # Update collection
            if collection:
                job_name = script["job_name"]
                existing_job = collection.get_job(job_name)

                if existing_job:
                    collection.update_job(
                        job_name,
                        job_id=job_id,
                        submitted_at=datetime.now().isoformat(timespec="seconds"),
                    )
                else:
                    collection.add_job(
                        job_name=job_name,
                        script_path=script["path"],
                        job_id=job_id,
                        submitted_at=datetime.now().isoformat(timespec="seconds"),
                    )
        else:
            print(f"Failed: {script['job_name']} -> {message}", file=sys.stderr)

        # Delay between submissions
        if args.delay > 0 and i < len(scripts_to_submit) - 1:
            time.sleep(args.delay)

    # Save collection
    if collection:
        manager.save(collection)

    print(f"\nSubmitted {submitted}/{len(scripts_to_submit)} job(s).")
    return 0


# =============================================================================
# resubmit Command
# =============================================================================

def cmd_resubmit(args: Any) -> int:
    """Resubmit failed jobs."""
    config = get_configured_config(args)
    manager = CollectionManager(config=config)

    # Resolve jobs directory
    if args.jobs_dir:
        jobs_dir = Path(args.jobs_dir)
    else:
        jobs_dir = config.get_path("jobs_dir")

    jobs_to_resubmit = []

    if args.collection:
        # Resubmit from collection
        if not manager.exists(args.collection):
            print(f"Error: Collection not found: {args.collection}")
            return 1

        collection = manager.load(args.collection)

        # Refresh states first
        collection.refresh_states()

        # Filter jobs
        if args.filter == "failed":
            jobs = collection.filter_jobs(state="failed")
        else:
            jobs = collection.jobs

        for job in jobs:
            script_path = job.get("script_path")
            if script_path:
                jobs_to_resubmit.append({
                    "job_name": job.get("job_name"),
                    "script_path": Path(script_path),
                    "original_job_id": job.get("job_id"),
                    "collection_job": job,
                })

    elif args.job_ids:
        # Resubmit by job ID
        for job_id in args.job_ids:
            script_path = infer_script_path(job_id, jobs_dir, config)
            if script_path:
                jobs_to_resubmit.append({
                    "job_name": script_path.stem,
                    "script_path": script_path,
                    "original_job_id": job_id,
                })
            else:
                print(f"Warning: Could not find script for job {job_id}")

    else:
        print("Error: Specify job IDs or --collection.")
        return 1

    if not jobs_to_resubmit:
        print("No jobs to resubmit.")
        return 0

    # Parse extra params
    extra_params = {}
    if args.extra_params:
        for item in args.extra_params.split(","):
            if "=" in item:
                key, value = item.split("=", 1)
                extra_params[key.strip()] = value.strip()

    # Display jobs
    print(f"Will resubmit {len(jobs_to_resubmit)} job(s):")
    print_separator()
    for job in jobs_to_resubmit:
        print(f"  {job['job_name']} (original ID: {job['original_job_id']})")
        print(f"    Script: {job['script_path']}")
    if extra_params:
        print(f"\nExtra parameters: {extra_params}")
    print_separator()

    if args.dry_run:
        print("\n[DRY RUN] No jobs were resubmitted.")
        return 0

    # Confirm
    if not args.yes:
        if not prompt_yes_no(f"\nResubmit these {len(jobs_to_resubmit)} job(s)? [y/N]: "):
            print("Aborted.")
            return 0

    # Get collection for tracking
    collection = None
    if args.collection:
        collection = manager.load(args.collection)

    # Resubmit jobs
    resubmitted = 0
    for job in jobs_to_resubmit:
        script_path = job["script_path"]

        if not script_path.exists():
            print(f"Error: Script not found: {script_path}", file=sys.stderr)
            continue

        success, job_id, message = submit_job(script_path, dry_run=False)

        if success:
            print(f"Resubmitted: {job['job_name']} -> {message}")
            resubmitted += 1

            # Record resubmission in collection
            if collection:
                collection.add_resubmission(
                    job["job_name"],
                    job_id=job_id,
                    extra_params=extra_params if extra_params else None,
                )
        else:
            print(f"Failed: {job['job_name']} -> {message}", file=sys.stderr)

    # Save collection
    if collection:
        manager.save(collection)

    print(f"\nResubmitted {resubmitted}/{len(jobs_to_resubmit)} job(s).")
    return 0


# =============================================================================
# collection Commands
# =============================================================================

def cmd_collection_create(args: Any) -> int:
    """Create a new collection."""
    config = get_configured_config(args)
    manager = CollectionManager(config=config)

    if manager.exists(args.name):
        print(f"Error: Collection already exists: {args.name}")
        return 1

    collection = manager.create(
        args.name,
        description=args.description,
    )

    print(f"Created collection: {args.name}")
    print(f"  File: {manager._get_path(args.name)}")
    return 0


def cmd_collection_list(args: Any) -> int:
    """List all collections."""
    config = get_configured_config(args)
    manager = CollectionManager(config=config)

    summaries = manager.list_collections_with_summary()

    if not summaries:
        print("No collections found.")
        return 0

    print(f"Found {len(summaries)} collection(s):\n")

    # Format as table
    headers = ["Name", "Description", "Total", "Completed", "Failed", "Pending", "Running"]
    rows = []

    for s in summaries:
        rows.append([
            s["name"],
            (s["description"][:30] + "...") if len(s.get("description", "")) > 30 else s.get("description", ""),
            s["total"],
            s["completed"],
            s["failed"],
            s["pending"],
            s["running"],
        ])

    print(tabulate(rows, headers=headers, tablefmt="simple"))
    return 0


def cmd_collection_show(args: Any) -> int:
    """Show collection details."""
    config = get_configured_config(args)
    manager = CollectionManager(config=config)

    if not manager.exists(args.name):
        print(f"Error: Collection not found: {args.name}")
        return 1

    collection = manager.load(args.name)

    # Refresh job states from SLURM unless --no-refresh is specified
    if not getattr(args, 'no_refresh', False):
        collection.refresh_states()
        manager.save(collection)

    # Apply state filter
    if args.state != "all":
        jobs = collection.filter_jobs(state=args.state)
    else:
        jobs = collection.jobs

    # Output format
    if args.format == "json":
        data = collection.to_dict()
        if args.state != "all":
            data["jobs"] = jobs
        print(json.dumps(data, indent=2, default=str))
        return 0

    elif args.format == "yaml":
        data = collection.to_dict()
        if args.state != "all":
            data["jobs"] = jobs
        print(yaml.dump(data, default_flow_style=False, sort_keys=False))
        return 0

    # Table format
    print(f"Collection: {collection.name}")
    print(f"Description: {collection.description}")
    print(f"Created: {collection.created_at}")
    print(f"Updated: {collection.updated_at}")
    print(f"Cluster: {collection.cluster}")

    if collection.parameters:
        print(f"\nGeneration Parameters:")
        print(yaml.dump(collection.parameters, default_flow_style=False, indent=2))

    summary = collection.get_summary()
    print(f"\nSummary: {summary['total']} jobs")
    print(f"  Completed: {summary['completed']}")
    print(f"  Failed: {summary['failed']}")
    print(f"  Running: {summary['running']}")
    print(f"  Pending: {summary['pending']}")
    print(f"  Not submitted: {summary['not_submitted']}")

    print(f"\nJobs ({len(jobs)}):")
    print_separator()

    if jobs:
        headers = ["Job Name", "Job ID", "State", "Hostname", "Resubmissions"]
        rows = []
        for job in jobs:
            resub_count = len(job.get("resubmissions", []))
            rows.append([
                job.get("job_name", ""),
                job.get("job_id", "N/A"),
                job.get("state", "N/A"),
                job.get("hostname", ""),
                resub_count if resub_count > 0 else "",
            ])
        print(tabulate(rows, headers=headers, tablefmt="simple"))
    else:
        print("  (no jobs)")

    return 0


def cmd_collection_update(args: Any) -> int:
    """Refresh job states in collection."""
    config = get_configured_config(args)
    manager = CollectionManager(config=config)

    if not manager.exists(args.name):
        print(f"Error: Collection not found: {args.name}")
        return 1

    collection = manager.load(args.name)

    print(f"Refreshing states for collection: {args.name}")
    updated = collection.refresh_states()

    manager.save(collection)

    print(f"Updated {updated} job state(s).")
    return 0


def cmd_collection_delete(args: Any) -> int:
    """Delete a collection."""
    config = get_configured_config(args)
    manager = CollectionManager(config=config)

    if not manager.exists(args.name):
        print(f"Error: Collection not found: {args.name}")
        return 1

    collection = manager.load(args.name)

    print(f"Collection: {args.name}")
    print(f"  Jobs: {len(collection)}")

    if not args.yes:
        if not prompt_yes_no(f"\nDelete collection '{args.name}'? [y/N]: "):
            print("Aborted.")
            return 0

    # Optionally delete associated files
    if not args.keep_scripts or not args.keep_outputs:
        for job in collection.jobs:
            if not args.keep_scripts:
                script_path = job.get("script_path")
                if script_path and Path(script_path).exists():
                    try:
                        Path(script_path).unlink()
                        print(f"Deleted script: {script_path}")
                    except OSError:
                        pass

            if not args.keep_outputs:
                output_path = job.get("output_path")
                if output_path and Path(output_path).exists():
                    try:
                        Path(output_path).unlink()
                        print(f"Deleted output: {output_path}")
                    except OSError:
                        pass

    manager.delete(args.name)
    print(f"Deleted collection: {args.name}")
    return 0


def cmd_collection_add(args: Any) -> int:
    """Add jobs to collection."""
    config = get_configured_config(args)
    manager = CollectionManager(config=config)

    if not manager.exists(args.name):
        print(f"Error: Collection not found: {args.name}")
        return 1

    collection = manager.load(args.name)
    jobs_dir = config.get_path("jobs_dir")

    added = 0
    for job_id in args.job_ids:
        # Find output file and script
        outputs = find_job_output(job_id, jobs_dir, config)
        script_path = infer_script_path(job_id, jobs_dir, config)

        # Get job info from sacct
        info = get_sacct_info([job_id])
        state = info.get(job_id, {}).get("State", "UNKNOWN")

        job_name = script_path.stem if script_path else f"job_{job_id}"
        output_path = outputs[0] if outputs else None

        collection.add_job(
            job_name=job_name,
            job_id=job_id,
            script_path=script_path,
            output_path=output_path,
            state=state,
        )
        added += 1
        print(f"Added: {job_name} (ID: {job_id})")

    manager.save(collection)
    print(f"\nAdded {added} job(s) to collection '{args.name}'.")
    return 0


def cmd_collection_remove(args: Any) -> int:
    """Remove jobs from collection."""
    config = get_configured_config(args)
    manager = CollectionManager(config=config)

    if not manager.exists(args.name):
        print(f"Error: Collection not found: {args.name}")
        return 1

    collection = manager.load(args.name)

    removed = 0
    for job_id in args.job_ids:
        job = collection.get_job_by_id(job_id)
        if job:
            collection.remove_job(job["job_name"])
            removed += 1
            print(f"Removed: {job['job_name']} (ID: {job_id})")
        else:
            print(f"Not found: {job_id}")

    manager.save(collection)
    print(f"\nRemoved {removed} job(s) from collection '{args.name}'.")
    return 0


# =============================================================================
# sync Command
# =============================================================================

def cmd_sync(args: Any) -> int:
    """Sync job states for cross-cluster tracking."""
    config = get_configured_config(args)
    sync_manager = SyncManager(config=config)

    collection_names = args.collection

    print(f"Syncing job states on {sync_manager.hostname}...")

    result = sync_manager.sync_all(collection_names=collection_names)

    print(f"\nSynced {result['total_collections']} collection(s)")
    print(f"Updated {result['total_jobs_updated']} job state(s)")
    print(f"Sync file: {sync_manager.get_sync_file_path()}")

    if args.push:
        print("\nPushing to git...")
        if sync_manager.push():
            print("Successfully pushed sync file.")
        else:
            print("Failed to push sync file.")
            return 1

    return 0
