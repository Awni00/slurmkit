"""
Main CLI entry point for slurmkit.

This module provides the main command-line interface with subcommands
for all slurmkit functionality.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from slurmkit import __version__


def create_parser() -> argparse.ArgumentParser:
    """
    Create the main argument parser with all subcommands.

    Returns:
        Configured ArgumentParser.
    """
    parser = argparse.ArgumentParser(
        prog="slurmkit",
        description="CLI tools for managing and generating SLURM jobs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  slurmkit init                    Initialize project configuration
  slurmkit status                  Show status for all jobs
  slurmkit status exp1             Show job status for specific experiment
  slurmkit find 12345              Find output file for job ID
  slurmkit generate job_spec.yaml  Generate jobs from spec file
  slurmkit submit jobs/exp1/       Submit job scripts
  slurmkit notify test             Test notification routes
  slurmkit collection list         List all collections
  slurmkit sync                    Sync job states to file

For more information on a command, run: slurmkit <command> --help
""",
    )

    parser.add_argument(
        "-V", "--version",
        action="version",
        version=f"slurmkit {__version__}",
    )

    # Global options
    parser.add_argument(
        "--config",
        metavar="PATH",
        help="Path to config file (default: .slurm-kit/config.yaml)",
    )
    parser.add_argument(
        "--ui",
        choices=["plain", "rich", "auto"],
        default=None,
        help="UI mode override (plain, rich, auto). Defaults to config ui.mode or plain.",
    )

    # Subcommands
    subparsers = parser.add_subparsers(
        dest="command",
        title="commands",
        metavar="<command>",
    )

    # init
    init_parser = subparsers.add_parser(
        "init",
        help="Initialize project configuration",
        description="Create or update the project configuration file.",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing configuration",
    )

    # status
    status_parser = subparsers.add_parser(
        "status",
        help="Show job status for an experiment",
        description="Display status of jobs in an experiment directory or all jobs.",
    )
    status_parser.add_argument(
        "experiment",
        nargs="?",
        help="Experiment subdirectory name (if not specified, shows all jobs)",
    )
    status_parser.add_argument(
        "--jobs-dir",
        metavar="PATH",
        help="Override jobs directory",
    )
    status_parser.add_argument(
        "--collection",
        metavar="NAME",
        help="Filter to jobs in a specific collection",
    )
    status_parser.add_argument(
        "--state",
        choices=["all", "running", "pending", "completed", "failed"],
        default="all",
        help="Filter by job state (default: all)",
    )
    status_parser.add_argument(
        "--format",
        choices=["table", "json", "csv"],
        default="table",
        help="Output format (default: table)",
    )

    # find
    find_parser = subparsers.add_parser(
        "find",
        help="Find job output file by job ID",
        description="Locate and preview SLURM job output files.",
    )
    find_parser.add_argument(
        "job_id",
        help="SLURM job ID to search for",
    )
    find_parser.add_argument(
        "--jobs-dir",
        metavar="PATH",
        help="Override jobs directory",
    )
    find_parser.add_argument(
        "--preview",
        action="store_true",
        help="Show preview of output file",
    )
    find_parser.add_argument(
        "--lines",
        type=int,
        default=50,
        metavar="N",
        help="Number of lines to show in preview (default: 50)",
    )
    find_parser.add_argument(
        "--open",
        action="store_true",
        help="Open file in $EDITOR or pager",
    )

    # clean
    clean_parser = subparsers.add_parser(
        "clean",
        help="Clean up failed jobs or wandb runs",
        description="Remove output files for failed jobs or clean up W&B runs.",
    )
    clean_subparsers = clean_parser.add_subparsers(
        dest="clean_type",
        title="clean types",
        metavar="<type>",
    )

    # clean outputs
    clean_outputs_parser = clean_subparsers.add_parser(
        "outputs",
        help="Clean failed job output files",
        description="Delete output files for failed jobs with short runtimes.",
    )
    clean_outputs_parser.add_argument(
        "experiment",
        help="Experiment subdirectory name",
    )
    clean_outputs_parser.add_argument(
        "--jobs-dir",
        metavar="PATH",
        help="Override jobs directory",
    )
    clean_outputs_parser.add_argument(
        "--threshold",
        type=int,
        default=300,
        metavar="SECONDS",
        help="Max runtime in seconds for jobs to delete (default: 300)",
    )
    clean_outputs_parser.add_argument(
        "--min-age",
        type=int,
        default=3,
        metavar="DAYS",
        help="Min age in days for jobs to consider (default: 3)",
    )
    clean_outputs_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without deleting",
    )
    clean_outputs_parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )

    # clean wandb
    clean_wandb_parser = clean_subparsers.add_parser(
        "wandb",
        help="Clean failed W&B runs",
        description="Delete failed/crashed W&B runs with short runtimes.",
    )
    clean_wandb_parser.add_argument(
        "--projects",
        nargs="+",
        metavar="PROJECT",
        help="W&B projects to clean",
    )
    clean_wandb_parser.add_argument(
        "--entity",
        metavar="ENTITY",
        help="W&B entity (default: from config)",
    )
    clean_wandb_parser.add_argument(
        "--threshold",
        type=int,
        default=300,
        metavar="SECONDS",
        help="Max runtime in seconds for runs to delete (default: 300)",
    )
    clean_wandb_parser.add_argument(
        "--min-age",
        type=int,
        default=3,
        metavar="DAYS",
        help="Min age in days for runs to consider (default: 3)",
    )
    clean_wandb_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without deleting",
    )
    clean_wandb_parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )

    # generate
    generate_parser = subparsers.add_parser(
        "generate",
        help="Generate job scripts from template",
        description="Generate SLURM job scripts from a template and parameters.",
    )
    generate_parser.add_argument(
        "spec_file",
        nargs="?",
        help="Job spec YAML file",
    )
    generate_parser.add_argument(
        "--template",
        metavar="FILE",
        help="Template file (alternative to spec file)",
    )
    generate_parser.add_argument(
        "--params",
        metavar="FILE",
        help="Parameters YAML file (alternative to spec file)",
    )
    generate_parser.add_argument(
        "--output-dir",
        metavar="DIR",
        help="Output directory for generated scripts",
    )
    generate_parser.add_argument(
        "--collection",
        metavar="NAME",
        help="Add generated jobs to collection (creates if needed)",
    )
    generate_parser.add_argument(
        "--slurm-args-file",
        metavar="FILE",
        help="Python file with SLURM args logic function",
    )
    generate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be generated without writing files",
    )

    # submit
    submit_parser = subparsers.add_parser(
        "submit",
        help="Submit job scripts",
        description="Submit SLURM job scripts using sbatch.",
    )
    submit_parser.add_argument(
        "paths",
        nargs="*",
        help="Job script(s) or directory of scripts",
    )
    submit_parser.add_argument(
        "--collection",
        metavar="NAME",
        help="Submit from collection or add submitted jobs to collection",
    )
    submit_parser.add_argument(
        "--filter",
        choices=["unsubmitted", "all"],
        default="unsubmitted",
        help="For collection mode: which jobs to submit (default: unsubmitted)",
    )
    submit_parser.add_argument(
        "--delay",
        type=float,
        default=0,
        metavar="SECONDS",
        help="Delay between submissions (default: 0)",
    )
    submit_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be submitted without submitting",
    )
    submit_parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )

    # resubmit
    resubmit_parser = subparsers.add_parser(
        "resubmit",
        help="Resubmit failed jobs",
        description="Resubmit failed SLURM jobs.",
    )
    resubmit_parser.add_argument(
        "job_ids",
        nargs="*",
        help="Job ID(s) to resubmit",
    )
    resubmit_parser.add_argument(
        "--collection",
        metavar="NAME",
        help="Resubmit from collection",
    )
    resubmit_parser.add_argument(
        "--filter",
        choices=["failed", "all"],
        default="failed",
        help="For collection mode: which jobs to resubmit (default: failed)",
    )
    resubmit_parser.add_argument(
        "--template",
        metavar="FILE",
        help="Use modified template for resubmission",
    )
    resubmit_parser.add_argument(
        "--extra-params",
        metavar="KEY=VAL,...",
        help="Extra template parameters for resubmission",
    )
    resubmit_parser.add_argument(
        "--extra-params-file",
        metavar="FILE",
        help="Python file with get_extra_params(context)->dict callback",
    )
    resubmit_parser.add_argument(
        "--extra-params-function",
        metavar="NAME",
        default="get_extra_params",
        help="Callback function name in --extra-params-file (default: get_extra_params)",
    )
    resubmit_parser.add_argument(
        "--select-file",
        metavar="FILE",
        help="Python file with should_resubmit(context)->bool callback",
    )
    resubmit_parser.add_argument(
        "--select-function",
        metavar="NAME",
        default="should_resubmit",
        help="Callback function name in --select-file (default: should_resubmit)",
    )
    resubmit_parser.add_argument(
        "--submission-group",
        metavar="NAME",
        help="Submission group label (default: auto-generated per resubmit command)",
    )
    resubmit_parser.add_argument(
        "--jobs-dir",
        metavar="PATH",
        help="Override jobs directory",
    )
    resubmit_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be resubmitted without submitting",
    )
    resubmit_parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )

    # collection
    collection_parser = subparsers.add_parser(
        "collection",
        help="Manage job collections",
        description="Create, list, and manage job collections.",
    )
    collection_subparsers = collection_parser.add_subparsers(
        dest="collection_action",
        title="actions",
        metavar="<action>",
    )

    # collection create
    coll_create_parser = collection_subparsers.add_parser(
        "create",
        help="Create a new collection",
    )
    coll_create_parser.add_argument(
        "name",
        help="Collection name",
    )
    coll_create_parser.add_argument(
        "--description",
        default="",
        help="Collection description",
    )

    # collection list
    collection_subparsers.add_parser(
        "list",
        help="List all collections",
    )

    # collection show
    coll_show_parser = collection_subparsers.add_parser(
        "show",
        help="Show collection details",
    )
    coll_show_parser.add_argument(
        "name",
        help="Collection name",
    )
    coll_show_parser.add_argument(
        "--format",
        choices=["table", "json", "yaml"],
        default="table",
        help="Output format (default: table)",
    )
    coll_show_parser.add_argument(
        "--state",
        choices=["all", "pending", "running", "completed", "failed"],
        default="all",
        help="Filter by job state (default: all)",
    )
    coll_show_parser.add_argument(
        "--attempt-mode",
        choices=["primary", "latest"],
        default="latest",
        help="Show primary submission state or latest attempt state (default: latest)",
    )
    coll_show_parser.add_argument(
        "--submission-group",
        metavar="NAME",
        help="Show only jobs that have a resubmission in this submission group",
    )
    coll_show_parser.add_argument(
        "--show-primary",
        action="store_true",
        help="Include primary submission Job ID/State columns",
    )
    coll_show_parser.add_argument(
        "--show-history",
        action="store_true",
        help="Include compact attempt history column",
    )
    coll_show_parser.add_argument(
        "--no-refresh",
        action="store_true",
        help="Don't refresh job states from SLURM before displaying (faster but may show stale data)",
    )

    # collection update
    coll_analyze_parser = collection_subparsers.add_parser(
        "analyze",
        help="Analyze job outcomes by parameter values",
    )
    coll_analyze_parser.add_argument(
        "name",
        help="Collection name",
    )
    coll_analyze_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format (default: table)",
    )
    coll_analyze_parser.add_argument(
        "--no-refresh",
        action="store_true",
        help="Don't refresh job states from SLURM before analysis",
    )
    coll_analyze_parser.add_argument(
        "--min-support",
        type=int,
        default=3,
        metavar="N",
        help="Minimum sample size for high-confidence highlights (default: 3)",
    )
    coll_analyze_parser.add_argument(
        "--param",
        action="append",
        metavar="KEY",
        help="Analyze only selected parameter key(s); repeat to include multiple",
    )
    coll_analyze_parser.add_argument(
        "--attempt-mode",
        choices=["primary", "latest"],
        default="primary",
        help="Use primary job states or latest resubmission states (default: primary)",
    )
    coll_analyze_parser.add_argument(
        "--submission-group",
        metavar="NAME",
        help="Analyze only jobs with resubmissions in this submission group "
             "(uses latest attempt within the group)",
    )
    coll_analyze_parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        metavar="N",
        help="Number of entries to show for risky/stable summaries (default: 10)",
    )

    # collection groups
    coll_groups_parser = collection_subparsers.add_parser(
        "groups",
        help="List submission groups and counts",
    )
    coll_groups_parser.add_argument(
        "name",
        help="Collection name",
    )
    coll_groups_parser.add_argument(
        "--format",
        choices=["table", "json", "yaml"],
        default="table",
        help="Output format (default: table)",
    )

    # collection update
    coll_update_parser = collection_subparsers.add_parser(
        "update",
        help="Refresh job states in collection",
    )
    coll_update_parser.add_argument(
        "name",
        help="Collection name",
    )

    # collection delete
    coll_delete_parser = collection_subparsers.add_parser(
        "delete",
        help="Delete a collection",
    )
    coll_delete_parser.add_argument(
        "name",
        help="Collection name",
    )
    coll_delete_parser.add_argument(
        "--keep-scripts",
        action="store_true",
        help="Keep job script files",
    )
    coll_delete_parser.add_argument(
        "--keep-outputs",
        action="store_true",
        help="Keep output files",
    )
    coll_delete_parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )

    # collection add
    coll_add_parser = collection_subparsers.add_parser(
        "add",
        help="Add jobs to collection",
    )
    coll_add_parser.add_argument(
        "name",
        help="Collection name",
    )
    coll_add_parser.add_argument(
        "job_ids",
        nargs="+",
        help="Job ID(s) to add",
    )

    # collection remove
    coll_remove_parser = collection_subparsers.add_parser(
        "remove",
        help="Remove jobs from collection",
    )
    coll_remove_parser.add_argument(
        "name",
        help="Collection name",
    )
    coll_remove_parser.add_argument(
        "job_ids",
        nargs="+",
        help="Job ID(s) to remove",
    )

    # sync
    sync_parser = subparsers.add_parser(
        "sync",
        help="Sync job states for cross-cluster tracking",
        description="Refresh job states and write sync file.",
    )
    sync_parser.add_argument(
        "--collection",
        nargs="+",
        metavar="NAME",
        help="Sync specific collections (default: all)",
    )
    sync_parser.add_argument(
        "--output",
        metavar="FILE",
        help="Output file path",
    )
    sync_parser.add_argument(
        "--push",
        action="store_true",
        help="Git commit and push sync file",
    )

    # notify
    notify_parser = subparsers.add_parser(
        "notify",
        help="Send job lifecycle notifications",
        description="Send notifications to configured webhook routes.",
    )
    notify_subparsers = notify_parser.add_subparsers(
        dest="notify_action",
        title="actions",
        metavar="<action>",
    )

    # notify job
    notify_job_parser = notify_subparsers.add_parser(
        "job",
        help="Send notification for a completed job",
    )
    notify_job_parser.add_argument(
        "--job-id",
        metavar="JOB_ID",
        help="SLURM job ID (defaults to SLURM_JOB_ID env var)",
    )
    notify_job_parser.add_argument(
        "--collection",
        metavar="NAME",
        help="Optional collection name to narrow metadata lookup",
    )
    notify_job_parser.add_argument(
        "--exit-code",
        type=int,
        default=0,
        metavar="N",
        help="Process exit code used to derive event type (default: 0)",
    )
    notify_job_parser.add_argument(
        "--on",
        choices=["failed", "always"],
        default="failed",
        help="Notification trigger mode (default: failed)",
    )
    notify_job_parser.add_argument(
        "--route",
        action="append",
        metavar="NAME",
        help="Route name filter (repeatable)",
    )
    notify_job_parser.add_argument(
        "--tail-lines",
        type=int,
        metavar="N",
        help="Override number of output tail lines for failure notifications",
    )
    notify_job_parser.add_argument(
        "--strict",
        action="store_true",
        help="Require all selected routes to succeed",
    )
    notify_job_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show resolved routes and payload without sending requests",
    )

    # notify test
    notify_test_parser = notify_subparsers.add_parser(
        "test",
        help="Send synthetic test notification",
    )
    notify_test_parser.add_argument(
        "--route",
        action="append",
        metavar="NAME",
        help="Route name filter (repeatable)",
    )
    notify_test_parser.add_argument(
        "--strict",
        action="store_true",
        help="Require all selected routes to succeed",
    )
    notify_test_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show resolved routes and payload without sending requests",
    )

    # notify collection-final
    notify_collection_final_parser = notify_subparsers.add_parser(
        "collection-final",
        help="Send collection-final report notification when a collection becomes terminal",
    )
    notify_collection_final_parser.add_argument(
        "--job-id",
        metavar="JOB_ID",
        help="SLURM job ID that triggered this check (defaults to SLURM_JOB_ID env var)",
    )
    notify_collection_final_parser.add_argument(
        "--collection",
        metavar="NAME",
        help="Collection name (optional if job ID maps to exactly one collection)",
    )
    notify_collection_final_parser.add_argument(
        "--route",
        action="append",
        metavar="NAME",
        help="Route name filter (repeatable)",
    )
    notify_collection_final_parser.add_argument(
        "--strict",
        action="store_true",
        help="Require all attempted routes to succeed",
    )
    notify_collection_final_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show resolved routes and payload without sending requests",
    )
    notify_collection_final_parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass collection-final deduplication guard",
    )
    notify_collection_final_parser.add_argument(
        "--no-refresh",
        action="store_true",
        help="Skip SLURM refresh before finality check",
    )

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """
    Main CLI entry point.

    Args:
        argv: Command-line arguments. If None, uses sys.argv.

    Returns:
        Exit code (0 for success).
    """
    parser = create_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    # Import command handlers
    from slurmkit.cli import commands

    # Route to appropriate command handler
    try:
        if args.command == "init":
            return commands.cmd_init(args)

        elif args.command == "status":
            return commands.cmd_status(args)

        elif args.command == "find":
            return commands.cmd_find(args)

        elif args.command == "clean":
            if args.clean_type == "outputs":
                return commands.cmd_clean_outputs(args)
            elif args.clean_type == "wandb":
                return commands.cmd_clean_wandb(args)
            else:
                parser.parse_args([args.command, "--help"])
                return 1

        elif args.command == "generate":
            return commands.cmd_generate(args)

        elif args.command == "submit":
            return commands.cmd_submit(args)

        elif args.command == "resubmit":
            return commands.cmd_resubmit(args)

        elif args.command == "collection":
            if args.collection_action == "create":
                return commands.cmd_collection_create(args)
            elif args.collection_action == "list":
                return commands.cmd_collection_list(args)
            elif args.collection_action == "show":
                return commands.cmd_collection_show(args)
            elif args.collection_action == "analyze":
                return commands.cmd_collection_analyze(args)
            elif args.collection_action == "groups":
                return commands.cmd_collection_groups(args)
            elif args.collection_action == "update":
                return commands.cmd_collection_update(args)
            elif args.collection_action == "delete":
                return commands.cmd_collection_delete(args)
            elif args.collection_action == "add":
                return commands.cmd_collection_add(args)
            elif args.collection_action == "remove":
                return commands.cmd_collection_remove(args)
            else:
                parser.parse_args([args.command, "--help"])
                return 1

        elif args.command == "sync":
            return commands.cmd_sync(args)

        elif args.command == "notify":
            if args.notify_action == "job":
                return commands.cmd_notify_job(args)
            elif args.notify_action == "test":
                return commands.cmd_notify_test(args)
            elif args.notify_action == "collection-final":
                return commands.cmd_notify_collection_final(args)
            else:
                parser.parse_args([args.command, "--help"])
                return 1

        else:
            parser.print_help()
            return 1

    except KeyboardInterrupt:
        print("\nAborted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
