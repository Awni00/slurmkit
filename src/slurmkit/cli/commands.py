"""
Command handlers for slurmkit CLI.

This module contains the implementation of each CLI command.
"""

from __future__ import annotations

import json
import importlib.util
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml
import pandas as pd
from tabulate import tabulate

from slurmkit.cli.ui import (
    UIResolutionError,
    build_collection_analyze_report,
    build_collection_show_report,
    create_ui_backend,
    render_collection_analyze_report,
    render_collection_show_report,
    resolve_ui_context,
)
from slurmkit.config import Config, get_config, init_config
from slurmkit.collections import (
    Collection,
    CollectionManager,
    DEFAULT_COLLECTION_NAME,
    LEGACY_SUBMISSION_GROUP,
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
from slurmkit.notifications import (
    EVENT_COLLECTION_COMPLETED,
    EVENT_COLLECTION_FAILED,
    EVENT_JOB_COMPLETED,
    EVENT_JOB_FAILED,
    NotificationService,
)


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


def _parse_key_value_pairs(raw: Optional[str]) -> Dict[str, str]:
    """Parse KEY=VAL comma-separated pairs."""
    parsed: Dict[str, str] = {}
    if not raw:
        return parsed
    for item in raw.split(","):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        if key:
            parsed[key] = value.strip()
    return parsed


def _load_python_callback(
    file_path: Optional[str],
    function_name: str,
    *,
    callback_kind: str,
) -> Optional[Callable[[Dict[str, Any]], Any]]:
    """
    Load callback from a Python file.

    callback_kind is used in error messages only.
    """
    if not file_path:
        return None

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"{callback_kind} file not found: {path}")

    module_name = f"slurmkit_cli_cb_{callback_kind}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module from {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    if not hasattr(module, function_name):
        raise AttributeError(
            f"{callback_kind} function '{function_name}' not found in {path}"
        )
    callback = getattr(module, function_name)
    if not callable(callback):
        raise TypeError(f"{callback_kind} '{function_name}' in {path} is not callable")

    return callback


def _resolve_resubmit_regenerate_mode(args: Any, is_collection_mode: bool) -> bool:
    """Resolve regenerate mode with mode-specific defaults."""
    regenerate_flag = getattr(args, "regenerate", None)
    if regenerate_flag is None:
        return is_collection_mode
    if regenerate_flag and not is_collection_mode:
        raise ValueError(
            "--regenerate requires --collection so template context can be resolved. "
            "Use collection mode or omit --regenerate for job-id resubmission."
        )
    return bool(regenerate_flag)


def _resolve_generation_context(collection: Collection, args: Any) -> Dict[str, Any]:
    """
    Resolve and validate generation context needed for regenerated resubmissions.

    Raises ValueError with actionable messages when context is missing/incomplete.
    """
    generation_meta = collection.meta.get("generation")
    if not isinstance(generation_meta, dict):
        raise ValueError(
            "Collection is missing generation metadata required for --regenerate. "
            "Use --no-regenerate for legacy collections."
        )

    template_raw = getattr(args, "template", None) or generation_meta.get("template_path")
    output_dir_raw = generation_meta.get("output_dir")
    if not template_raw:
        raise ValueError(
            "Generation metadata is missing 'template_path'. "
            "Pass --template or use --no-regenerate."
        )
    if not output_dir_raw:
        raise ValueError(
            "Generation metadata is missing 'output_dir'. "
            "Use --no-regenerate for legacy collections."
        )

    template_path = Path(str(template_raw))
    if not template_path.exists():
        raise ValueError(
            f"Template file not found for regeneration: {template_path}. "
            "Pass --template or use --no-regenerate."
        )

    slurm_defaults = generation_meta.get("slurm_defaults", {})
    if slurm_defaults is None:
        slurm_defaults = {}
    if not isinstance(slurm_defaults, dict):
        raise ValueError(
            "Generation metadata field 'slurm_defaults' must be a mapping. "
            "Use --no-regenerate or regenerate jobs with slurmkit generate."
        )

    slurm_logic_file = generation_meta.get("slurm_logic_file")
    if slurm_logic_file:
        slurm_logic_file = Path(str(slurm_logic_file))
        if not slurm_logic_file.exists():
            raise ValueError(
                f"SLURM logic file not found for regeneration: {slurm_logic_file}. "
                "Use --no-regenerate or refresh collection generation metadata."
            )

    logs_dir = generation_meta.get("logs_dir")
    return {
        "template_path": template_path,
        "output_dir": Path(str(output_dir_raw)),
        "job_name_pattern": generation_meta.get("job_name_pattern"),
        "logs_dir": Path(str(logs_dir)) if logs_dir else None,
        "slurm_defaults": slurm_defaults,
        "slurm_logic_file": slurm_logic_file,
        "slurm_logic_function": generation_meta.get("slurm_logic_function", "get_slurm_args"),
    }


def _build_generation_metadata(
    generator: JobGenerator,
    output_dir: Path,
) -> Dict[str, Any]:
    """Build serializable generation metadata for collection persistence."""
    return {
        "template_path": str(generator.template_path),
        "output_dir": str(output_dir),
        "job_name_pattern": generator.job_name_pattern,
        "logs_dir": str(generator.logs_dir) if generator.logs_dir else None,
        "slurm_defaults": generator.slurm_defaults,
        "slurm_logic_file": str(generator.slurm_logic_file) if generator.slurm_logic_file else None,
        "slurm_logic_function": generator.slurm_logic_function,
    }


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

    # CLI UI settings
    print("\nCLI output UI:")
    ui_mode = input("  Default UI mode [plain|rich|auto, default: plain]: ").strip().lower() or "plain"
    if ui_mode not in ("plain", "rich", "auto"):
        print("  Invalid UI mode. Falling back to 'plain'.")
        ui_mode = "plain"

    # Notification settings (optional)
    print("\nNotifications (optional):")
    enable_notifications = prompt_yes_no("  Configure notifications now? [y/N]: ")
    notification_route = None
    if enable_notifications:
        route_type = input("  Route type [webhook]: ").strip().lower() or "webhook"
        if route_type not in ("webhook", "slack", "discord", "email"):
            print("  Invalid route type. Falling back to 'webhook'.")
            route_type = "webhook"

        default_route_name = f"{route_type}_default"
        route_name = input(f"  Route name [{default_route_name}]: ").strip() or default_route_name
        if route_type == "email":
            recipients_raw = input(
                "  Email recipient(s) (comma-separated, supports ${ENV_VAR}): "
            ).strip()
            from_address = input("  From address (supports ${ENV_VAR}): ").strip()
            smtp_host = input("  SMTP host (supports ${ENV_VAR}): ").strip()
            smtp_port_raw = input("  SMTP port [587]: ").strip() or "587"
            smtp_username = input("  SMTP username (optional, supports ${ENV_VAR}): ").strip()
            smtp_password = input("  SMTP password (optional, supports ${ENV_VAR}): ").strip()
            use_starttls_raw = input("  Use STARTTLS? [Y/n]: ").strip().lower()
            use_ssl_raw = input("  Use SMTP SSL? [y/N]: ").strip().lower()

            if not recipients_raw or not from_address or not smtp_host:
                print("  Missing required email fields. Notifications setup skipped.")
            else:
                try:
                    smtp_port = int(smtp_port_raw)
                    if smtp_port <= 0:
                        raise ValueError
                except ValueError:
                    print("  Invalid SMTP port. Falling back to 587.")
                    smtp_port = 587

                smtp_starttls = use_starttls_raw not in ("n", "no", "0", "false")
                smtp_ssl = use_ssl_raw in ("y", "yes", "1", "true")
                if smtp_starttls and smtp_ssl:
                    print("  STARTTLS and SMTP SSL cannot both be enabled. Using STARTTLS only.")
                    smtp_ssl = False

                if bool(smtp_username) != bool(smtp_password):
                    print("  SMTP username/password must both be set. Notifications setup skipped.")
                    smtp_username = ""
                    smtp_password = ""
                    recipients = []
                else:
                    recipients = [entry.strip() for entry in recipients_raw.split(",") if entry.strip()]

                if not recipients:
                    print("  No valid recipients parsed. Notifications setup skipped.")
                else:
                    events_raw = input("  Events (comma-separated) [job_failed]: ").strip() or "job_failed"
                    events = [event.strip() for event in events_raw.split(",") if event.strip()]
                    notification_route = {
                        "name": route_name,
                        "type": route_type,
                        "enabled": True,
                        "events": events or ["job_failed"],
                        "to": recipients,
                        "from": from_address,
                        "smtp_host": smtp_host,
                        "smtp_port": smtp_port,
                        "smtp_starttls": smtp_starttls,
                        "smtp_ssl": smtp_ssl,
                    }
                    if smtp_username:
                        notification_route["smtp_username"] = smtp_username
                    if smtp_password:
                        notification_route["smtp_password"] = smtp_password
        else:
            route_url = input("  Route URL (supports ${ENV_VAR}): ").strip()
            if not route_url:
                print("  Empty route URL. Notifications setup skipped.")
            else:
                events_raw = input("  Events (comma-separated) [job_failed]: ").strip() or "job_failed"
                events = [event.strip() for event in events_raw.split(",") if event.strip()]
                notification_route = {
                    "name": route_name,
                    "type": route_type,
                    "url": route_url,
                    "enabled": True,
                    "events": events or ["job_failed"],
                    "headers": {},
                }

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
        "ui": {
            "mode": ui_mode,
        },
        "notifications": {
            "defaults": {
                "events": ["job_failed"],
                "timeout_seconds": 5,
                "max_attempts": 3,
                "backoff_seconds": 0.5,
                "output_tail_lines": 40,
            },
            "collection_final": {
                "attempt_mode": "latest",
                "min_support": 3,
                "top_k": 10,
                "include_failed_output_tail_lines": 20,
                "ai": {
                    "enabled": False,
                    "callback": None,
                },
            },
            "routes": [],
        },
    }

    if wandb_entity:
        config_data["wandb"] = {
            "entity": wandb_entity,
            "default_projects": [],
        }

    if notification_route:
        config_data["notifications"]["routes"].append(notification_route)

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

    generation_meta = _build_generation_metadata(
        generator=generator,
        output_dir=Path(output_dir),
    )
    if not isinstance(collection.meta, dict):
        collection.meta = {}
    collection.meta["generation"] = generation_meta

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
        if args.filter == "unsubmitted":
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

    jobs_to_consider = []
    collection_for_tracking: Optional[Collection] = None
    submission_group = args.submission_group or datetime.now().strftime("resubmit_%Y%m%d_%H%M%S")
    is_collection_mode = bool(args.collection)

    if args.collection:
        # Resubmit from collection
        if not manager.exists(args.collection):
            print(f"Error: Collection not found: {args.collection}")
            return 1

        collection = manager.load(args.collection)
        collection_for_tracking = collection

        # Refresh states first
        collection.refresh_states()
        manager.save(collection)

        # Filter jobs
        if args.filter == "failed":
            jobs = [
                row["job"]
                for row in collection.get_effective_jobs(attempt_mode="latest", state="failed")
            ]
        else:
            jobs = collection.jobs

        for job in jobs:
            script_path = job.get("script_path")
            if script_path:
                jobs_to_consider.append({
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
                jobs_to_consider.append({
                    "job_name": script_path.stem,
                    "script_path": script_path,
                    "original_job_id": job_id,
                    "collection_job": None,
                })
            else:
                print(f"Warning: Could not find script for job {job_id}")

    else:
        print("Error: Specify job IDs or --collection.")
        return 1

    if not jobs_to_consider:
        print("No jobs to resubmit.")
        return 0

    try:
        regenerate = _resolve_resubmit_regenerate_mode(
            args,
            is_collection_mode=is_collection_mode,
        )
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    generation_context: Optional[Dict[str, Any]] = None
    resubmit_generator: Optional[JobGenerator] = None
    if regenerate:
        if collection_for_tracking is None:
            print(
                "Error: --regenerate requires --collection mode so generation metadata can be loaded."
            )
            return 1
        try:
            generation_context = _resolve_generation_context(collection_for_tracking, args)
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
        except Exception as exc:
            print(f"Error: {exc}")
            return 1

    static_extra_params = _parse_key_value_pairs(args.extra_params)

    try:
        extra_params_callback = _load_python_callback(
            getattr(args, "extra_params_file", None),
            getattr(args, "extra_params_function", "get_extra_params"),
            callback_kind="extra_params",
        )
        select_callback = _load_python_callback(
            getattr(args, "select_file", None),
            getattr(args, "select_function", "should_resubmit"),
            callback_kind="selection",
        )
    except Exception as exc:
        print(f"Error: {exc}")
        return 1

    jobs_to_resubmit = []
    skipped_jobs = []
    for job in jobs_to_consider:
        callback_context = {
            "job_name": job["job_name"],
            "script_path": str(job["script_path"]),
            "original_job_id": job.get("original_job_id"),
            "collection_name": args.collection,
            "collection_job": job.get("collection_job"),
            "submission_group": submission_group,
            "static_extra_params": static_extra_params.copy(),
        }

        reason = None
        if select_callback is not None:
            try:
                decision = select_callback(callback_context.copy())
            except Exception as exc:
                print(f"Error: selection callback failed for '{job['job_name']}': {exc}")
                return 1

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
                print(
                    "Error: selection callback must return bool or (bool, reason), "
                    f"got {type(decision).__name__} for '{job['job_name']}'."
                )
                return 1

            if not include_job:
                skipped_jobs.append({**job, "reason": reason})
                continue

        dynamic_extra_params: Dict[str, Any] = {}
        if extra_params_callback is not None:
            try:
                callback_result = extra_params_callback(callback_context.copy())
            except Exception as exc:
                print(f"Error: extra params callback failed for '{job['job_name']}': {exc}")
                return 1

            if callback_result is None:
                callback_result = {}
            if not isinstance(callback_result, dict):
                print(
                    "Error: extra params callback must return a dict, "
                    f"got {type(callback_result).__name__} for '{job['job_name']}'."
                )
                return 1
            dynamic_extra_params = dict(callback_result)

        resolved_extra_params = dict(dynamic_extra_params)
        resolved_extra_params.update(static_extra_params)

        prepared_job = {
            **job,
            "resolved_extra_params": resolved_extra_params,
            "regenerated": regenerate,
        }
        if regenerate:
            collection_job = job.get("collection_job")
            if not isinstance(collection_job, dict):
                print(
                    f"Error: job '{job['job_name']}' is missing collection metadata required "
                    "for regeneration. Use --no-regenerate."
                )
                return 1
            base_params = collection_job.get("parameters") or {}
            if not isinstance(base_params, dict):
                print(
                    f"Error: job '{job['job_name']}' has non-mapping parameters in collection metadata. "
                    "Use --no-regenerate."
                )
                return 1

            resubmit_count = len(collection_job.get("resubmissions", []) or []) + 1
            attempt_job_name = f"{job['job_name']}.resubmit-{resubmit_count}"
            effective_params = dict(base_params)
            effective_params.update(resolved_extra_params)
            prepared_job.update({
                "attempt_job_name": attempt_job_name,
                "attempt_script_path": generation_context["output_dir"] / f"{attempt_job_name}.job",
                "effective_params": effective_params,
            })

        jobs_to_resubmit.append(prepared_job)

    # Display jobs
    print(f"Submission group: {submission_group}")
    print(f"Regenerate scripts: {'yes' if regenerate else 'no'}")
    print(f"Will resubmit {len(jobs_to_resubmit)} job(s):")
    print_separator()
    for job in jobs_to_resubmit:
        print(f"  {job['job_name']} (original ID: {job['original_job_id']})")
        if job["regenerated"]:
            print(f"    Generated script: {job['attempt_script_path']}")
        else:
            print(f"    Script: {job['script_path']}")
        if job.get("resolved_extra_params"):
            print(f"    Extra parameters: {job['resolved_extra_params']}")
    if skipped_jobs:
        print(f"\nSkipped {len(skipped_jobs)} job(s) due to selection callback:")
        for job in skipped_jobs:
            if job.get("reason"):
                print(f"  {job['job_name']}: {job['reason']}")
            else:
                print(f"  {job['job_name']}")
    print_separator()

    if not jobs_to_resubmit:
        print("No jobs to resubmit after applying selection logic.")
        return 0

    if args.dry_run:
        print("\n[DRY RUN] No jobs were resubmitted.")
        return 0

    # Confirm
    if not args.yes:
        if not prompt_yes_no(f"\nResubmit these {len(jobs_to_resubmit)} job(s)? [y/N]: "):
            print("Aborted.")
            return 0

    # Resubmit jobs
    resubmitted = 0
    for job in jobs_to_resubmit:
        script_path = job["script_path"]
        attempt_script_path = script_path

        if job["regenerated"]:
            try:
                generated_job = resubmit_generator.generate_one(
                    output_dir=generation_context["output_dir"],
                    params=job["effective_params"],
                    job_name=job["attempt_job_name"],
                    dry_run=False,
                )
                attempt_script_path = generated_job["script_path"]
            except Exception as exc:
                print(
                    f"Failed: {job['job_name']} -> regeneration failed: {exc}",
                    file=sys.stderr,
                )
                continue

        if not attempt_script_path.exists():
            print(f"Error: Script not found: {attempt_script_path}", file=sys.stderr)
            continue

        success, job_id, message = submit_job(attempt_script_path, dry_run=False)

        if success:
            print(f"Resubmitted: {job['job_name']} -> {message}")
            resubmitted += 1

            # Record resubmission in collection
            if collection_for_tracking:
                collection_for_tracking.add_resubmission(
                    job["job_name"],
                    job_id=job_id,
                    extra_params=job.get("resolved_extra_params") or None,
                    submission_group=submission_group,
                    attempt_job_name=job.get("attempt_job_name"),
                    attempt_script_path=attempt_script_path if job["regenerated"] else None,
                    attempt_parameters=job.get("effective_params"),
                    regenerated=job["regenerated"],
                )
        else:
            print(f"Failed: {job['job_name']} -> {message}", file=sys.stderr)

    # Save collection
    if collection_for_tracking:
        manager.save(collection_for_tracking)

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

    summaries = manager.list_collections_with_summary(
        attempt_mode=getattr(args, "attempt_mode", "latest"),
    )

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

    state_filter = None if args.state == "all" else args.state
    effective_jobs = collection.get_effective_jobs(
        attempt_mode=args.attempt_mode,
        submission_group=args.submission_group,
        state=state_filter,
    )
    effective_summary = collection.get_effective_summary(
        attempt_mode=args.attempt_mode,
        submission_group=args.submission_group,
    )
    summary_jobs = effective_jobs
    if state_filter is not None:
        summary_jobs = collection.get_effective_jobs(
            attempt_mode=args.attempt_mode,
            submission_group=args.submission_group,
            state=None,
        )

    serialized_jobs = []
    for row in effective_jobs:
        serialized = dict(row["job"])
        serialized["effective_job_id"] = row.get("effective_job_id")
        serialized["effective_state"] = row.get("effective_state_raw")
        serialized["effective_state_normalized"] = row.get("effective_state")
        serialized["effective_hostname"] = row.get("effective_hostname")
        serialized["effective_attempt_label"] = row.get("effective_attempt_label")
        serialized["effective_attempt_index"] = row.get("effective_attempt_index")
        serialized["effective_submission_group"] = row.get("effective_submission_group")
        if getattr(args, "show_history", False):
            serialized["effective_attempt_history"] = row.get("attempt_history", [])
        serialized_jobs.append(serialized)

    # Output format
    if args.format == "json":
        data = collection.to_dict()
        data["jobs"] = serialized_jobs
        data["effective_summary"] = effective_summary
        data["effective_attempt_mode"] = args.attempt_mode
        data["effective_submission_group"] = args.submission_group
        print(json.dumps(data, indent=2, default=str))
        return 0

    elif args.format == "yaml":
        data = collection.to_dict()
        data["jobs"] = serialized_jobs
        data["effective_summary"] = effective_summary
        data["effective_attempt_mode"] = args.attempt_mode
        data["effective_submission_group"] = args.submission_group
        print(yaml.dump(data, default_flow_style=False, sort_keys=False))
        return 0

    try:
        ui_context = resolve_ui_context(args, config)
        backend = create_ui_backend(ui_context)
    except UIResolutionError as exc:
        print(f"Error: {exc}")
        return 1

    report = build_collection_show_report(
        collection=collection,
        jobs=effective_jobs,
        summary=effective_summary,
        attempt_mode=args.attempt_mode,
        submission_group=args.submission_group,
        show_primary=getattr(args, "show_primary", False),
        show_history=getattr(args, "show_history", False),
        summary_jobs=summary_jobs,
    )
    render_collection_show_report(report, backend)

    return 0


def cmd_collection_analyze(args: Any) -> int:
    """Analyze state patterns by parameter values in a collection."""
    if args.min_support < 1:
        print("Error: --min-support must be >= 1")
        return 1
    if args.top_k < 1:
        print("Error: --top-k must be >= 1")
        return 1

    config = get_configured_config(args)
    manager = CollectionManager(config=config)

    if not manager.exists(args.name):
        print(f"Error: Collection not found: {args.name}")
        return 1

    collection = manager.load(args.name)

    # Refresh job states from SLURM unless --no-refresh is specified
    if not getattr(args, "no_refresh", False):
        collection.refresh_states()
        manager.save(collection)

    analysis = collection.analyze_status_by_params(
        attempt_mode=args.attempt_mode,
        submission_group=args.submission_group,
        min_support=args.min_support,
        selected_params=args.param,
        top_k=args.top_k,
    )

    if args.format == "json":
        print(json.dumps(analysis, indent=2, default=str))
        return 0

    try:
        ui_context = resolve_ui_context(args, config)
        backend = create_ui_backend(ui_context)
    except UIResolutionError as exc:
        print(f"Error: {exc}")
        return 1

    report = build_collection_analyze_report(
        collection_name=collection.name,
        analysis=analysis,
        attempt_mode=analysis["metadata"]["attempt_mode"],
        min_support=args.min_support,
        top_k=args.top_k,
        selected_params=args.param,
        submission_group=args.submission_group,
    )
    render_collection_analyze_report(report, backend)

    return 0


def cmd_collection_groups(args: Any) -> int:
    """Show submission group counts for a collection."""
    config = get_configured_config(args)
    manager = CollectionManager(config=config)

    if not manager.exists(args.name):
        print(f"Error: Collection not found: {args.name}")
        return 1

    collection = manager.load(args.name)
    groups = collection.get_submission_groups_summary()

    if args.format == "json":
        print(json.dumps(groups, indent=2, default=str))
        return 0

    if args.format == "yaml":
        print(yaml.dump(groups, default_flow_style=False, sort_keys=False))
        return 0

    print(f"Submission groups for collection: {args.name}")
    print_separator()
    if not groups:
        print("  (no submission groups)")
        return 0

    rows = []
    for group in groups:
        rows.append(
            [
                group["submission_group"],
                group["slurm_job_count"],
                group["parent_job_count"],
                group.get("first_submitted_at") or "",
                group.get("last_submitted_at") or "",
            ]
        )

    print(
        tabulate(
            rows,
            headers=[
                "Submission Group",
                "SLURM Jobs",
                "Parent Jobs",
                "First Submitted",
                "Last Submitted",
            ],
            tablefmt="simple",
        )
    )
    if any(group["submission_group"] == LEGACY_SUBMISSION_GROUP for group in groups):
        print(f"\nNote: '{LEGACY_SUBMISSION_GROUP}' includes historical resubmissions without a group label.")
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
# notify Commands
# =============================================================================

def _compute_notification_exit_code(
    success_count: int,
    attempted_count: int,
    strict: bool,
) -> int:
    """Compute command exit code from route-delivery outcomes."""
    if attempted_count == 0:
        return 0
    if strict:
        return 0 if success_count == attempted_count else 1
    return 0 if success_count > 0 else 1


def _print_notification_results(
    delivery_results: List[Any],
    route_errors: List[str],
) -> None:
    """Print human-readable delivery summary."""
    for error in route_errors:
        print(f"[route-error] {error}")

    for result in delivery_results:
        if result.success:
            mode = "dry-run" if result.dry_run else "sent"
            attempts = f"{result.attempts} attempt(s)" if not result.dry_run else "no request sent"
            print(f"[ok] {result.route_name} ({result.route_type}) - {mode}, {attempts}")
        else:
            details = result.error or "unknown error"
            if result.status_code is not None:
                details = f"HTTP {result.status_code} - {details}"
            print(f"[failed] {result.route_name} ({result.route_type}) - {details}")


def cmd_notify_job(args: Any) -> int:
    """Send notification for a completed/failed job."""
    config = get_configured_config(args)
    service = NotificationService(config=config)

    job_id = args.job_id or os.environ.get("SLURM_JOB_ID")
    if not job_id:
        print("Error: Missing job ID. Pass --job-id or set SLURM_JOB_ID.")
        return 1

    exit_code = int(args.exit_code)
    event = EVENT_JOB_FAILED if exit_code != 0 else EVENT_JOB_COMPLETED

    if args.on == "failed" and event != EVENT_JOB_FAILED:
        print("Skipping notification: event is job_completed and --on failed is active.")
        return 0

    payload, context_warnings = service.build_job_payload(
        job_id=job_id,
        exit_code=exit_code,
        event=event,
        collection_name=args.collection,
        tail_lines=args.tail_lines,
    )
    for warning in context_warnings:
        print(f"[context-warning] {warning}")

    ai_summary, ai_status, ai_warning = service.run_job_ai_callback(payload)
    if ai_warning:
        print(f"[ai-warning] {ai_warning}")
    payload["ai_status"] = ai_status
    payload["ai_summary"] = ai_summary

    route_resolution = service.resolve_routes(
        event=event,
        route_names=args.route,
    )

    if not route_resolution.routes and not route_resolution.errors:
        print(f"No notification routes matched event '{event}'.")
        return 0

    if args.dry_run:
        print("Dry run enabled. Payload preview:")
        print(json.dumps(payload, indent=2, default=str))
        if route_resolution.routes:
            names = ", ".join(route.name for route in route_resolution.routes)
            print(f"Resolved routes: {names}")
        else:
            print("Resolved routes: (none)")

    delivery_results = service.dispatch(
        payload=payload,
        routes=route_resolution.routes,
        dry_run=args.dry_run,
    )
    _print_notification_results(delivery_results, route_resolution.errors)

    success_count = sum(1 for result in delivery_results if result.success)
    attempted_count = len(delivery_results) + len(route_resolution.errors)
    return _compute_notification_exit_code(
        success_count=success_count,
        attempted_count=attempted_count,
        strict=args.strict,
    )


def cmd_notify_test(args: Any) -> int:
    """Send synthetic test notification to configured routes."""
    config = get_configured_config(args)
    service = NotificationService(config=config)

    payload = service.build_test_payload()
    route_resolution = service.resolve_routes(
        event=None,
        route_names=args.route,
    )

    if not route_resolution.routes and not route_resolution.errors:
        print("No enabled notification routes configured.")
        return 0

    if args.dry_run:
        print("Dry run enabled. Payload preview:")
        print(json.dumps(payload, indent=2, default=str))
        if route_resolution.routes:
            names = ", ".join(route.name for route in route_resolution.routes)
            print(f"Resolved routes: {names}")
        else:
            print("Resolved routes: (none)")

    delivery_results = service.dispatch(
        payload=payload,
        routes=route_resolution.routes,
        dry_run=args.dry_run,
    )
    _print_notification_results(delivery_results, route_resolution.errors)

    success_count = sum(1 for result in delivery_results if result.success)
    attempted_count = len(delivery_results) + len(route_resolution.errors)
    return _compute_notification_exit_code(
        success_count=success_count,
        attempted_count=attempted_count,
        strict=args.strict,
    )


def cmd_notify_collection_final(args: Any) -> int:
    """Send collection-final report if the target collection is terminal."""
    config = get_configured_config(args)
    service = NotificationService(config=config)

    trigger_job_id = args.job_id or os.environ.get("SLURM_JOB_ID")
    if not trigger_job_id:
        print("Error: Missing job ID. Pass --job-id or set SLURM_JOB_ID.")
        return 1

    resolution = service.resolve_collection_for_job(
        job_id=trigger_job_id,
        collection_name=args.collection,
    )
    for warning in resolution.warnings:
        print(f"[context-warning] {warning}")

    if resolution.collection is None:
        print("Error: Could not resolve a single collection for collection-final notification.")
        return 1

    collection_name = resolution.collection.name
    manager = service.collection_manager

    try:
        with service.collection_lock(collection_name):
            collection = manager.load(collection_name)

            if not args.no_refresh:
                collection.refresh_states()
                manager.save(collection)

            cfg = service.get_collection_final_config()
            finality = service.evaluate_collection_finality(
                collection=collection,
                attempt_mode=cfg.attempt_mode,
                trigger_job_id=trigger_job_id,
                trigger_exit_code=args.trigger_exit_code,
            )
            for warning in finality.warnings:
                print(f"[finality-warning] {warning}")

            counts = finality.counts
            if not finality.terminal:
                print(
                    "Collection is not terminal yet: "
                    f"pending={counts.get('pending', 0)}, running={counts.get('running', 0)}"
                )
                return 0

            event = finality.event
            if event not in (EVENT_COLLECTION_COMPLETED, EVENT_COLLECTION_FAILED):
                print("Error: Failed to determine collection terminal event.")
                return 1

            fingerprint = service.compute_collection_final_fingerprint(
                collection_name=collection.name,
                event=event,
                effective_rows=finality.effective_rows,
            )
            if not args.force and service.should_skip_collection_final(
                collection=collection,
                event=event,
                fingerprint=fingerprint,
            ):
                print(
                    "Skipping notification: collection-final notification "
                    "for this terminal snapshot was already sent."
                )
                return 0

            report = service.build_collection_report(
                collection=collection,
                trigger_job_id=trigger_job_id,
                attempt_mode=cfg.attempt_mode,
                min_support=cfg.min_support,
                top_k=cfg.top_k,
                failed_tail_lines=cfg.include_failed_output_tail_lines,
                precomputed_finality=finality,
            )

            ai_summary, ai_status, ai_warning = service.run_collection_ai_callback(report)
            if ai_warning:
                print(f"[ai-warning] {ai_warning}")

            payload = service.build_collection_final_payload(
                collection=collection,
                event=event,
                trigger_job_id=trigger_job_id,
                report=report,
                ai_status=ai_status,
                ai_summary=ai_summary,
            )

            route_resolution = service.resolve_routes(
                event=event,
                route_names=args.route,
            )
            if not route_resolution.routes and not route_resolution.errors:
                print(f"No notification routes matched event '{event}'.")
                return 0

            if args.dry_run:
                print("Dry run enabled. Payload preview:")
                print(json.dumps(payload, indent=2, default=str))
                if route_resolution.routes:
                    names = ", ".join(route.name for route in route_resolution.routes)
                    print(f"Resolved routes: {names}")
                else:
                    print("Resolved routes: (none)")

            delivery_results = service.dispatch(
                payload=payload,
                routes=route_resolution.routes,
                dry_run=args.dry_run,
            )
            _print_notification_results(delivery_results, route_resolution.errors)

            success_count = sum(1 for result in delivery_results if result.success)
            attempted_count = len(delivery_results) + len(route_resolution.errors)
            exit_code = _compute_notification_exit_code(
                success_count=success_count,
                attempted_count=attempted_count,
                strict=args.strict,
            )

            if exit_code == 0 and not args.dry_run:
                service.mark_collection_final_sent(
                    collection=collection,
                    event=event,
                    fingerprint=fingerprint,
                    trigger_job_id=trigger_job_id,
                )
                manager.save(collection)

            return exit_code

    except TimeoutError as e:
        print(f"Error: {e}")
        return 1


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
