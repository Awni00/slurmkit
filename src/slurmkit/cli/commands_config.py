"""Configuration and initialization commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import typer
import yaml

from slurmkit.config import DEFAULT_CONFIG
from slurmkit.workflows.configuration import (
    build_config_summary,
    load_config_data,
    normalize_config_data,
    open_config_in_editor,
    write_config_data,
)

from .prompts import canceled, prompt_choice, prompt_comma_separated, prompt_confirm, prompt_text
from .rendering import print_json, print_review
from .runtime import can_prompt, get_state
from slurmkit.workflows.shared import format_review


config_app = typer.Typer(help="Inspect and edit slurmkit configuration.")


def register(app: typer.Typer) -> None:
    app.add_typer(config_app, name="config")

    @app.command("init")
    def init_command(
        ctx: typer.Context,
        force: bool = typer.Option(False, "--force", help="Overwrite an existing config file."),
    ) -> None:
        state = get_state(ctx)
        config_path = state.config.config_path
        if config_path.exists() and not force:
            raise typer.BadParameter(f"Configuration file already exists: {config_path}")
        updated = _run_config_wizard(config_path=config_path, current={})
        review = format_review("Config plan", build_config_summary(updated), [])
        print_review(review)
        confirmed = prompt_confirm("Write this configuration?", default=True)
        if confirmed is None or not confirmed:
            raise typer.Exit(canceled())
        write_config_data(config_path, updated)
        typer.echo(f"Configuration saved to: {config_path}")
        raise typer.Exit(0)


@config_app.command("show")
def show_command(ctx: typer.Context, json_mode: bool = typer.Option(False, "--json", help="Emit JSON output.")) -> None:
    state = get_state(ctx)
    current = normalize_config_data(load_config_data(state.config.config_path))
    if json_mode:
        print_json(current)
    else:
        typer.echo(yaml.dump(current, default_flow_style=False, sort_keys=False).rstrip())
    raise typer.Exit(0)


@config_app.command("edit")
def edit_command(ctx: typer.Context) -> None:
    state = get_state(ctx)
    open_config_in_editor(state.config.config_path)
    raise typer.Exit(0)


@config_app.command("wizard")
def wizard_command(ctx: typer.Context) -> None:
    state = get_state(ctx)
    if not can_prompt(state):
        raise typer.BadParameter("Interactive prompting is not available.")
    current = load_config_data(state.config.config_path)
    updated = _run_config_wizard(config_path=state.config.config_path, current=current)
    review = format_review("Config plan", build_config_summary(updated), [])
    print_review(review)
    confirmed = prompt_confirm("Write this configuration?", default=True)
    if confirmed is None or not confirmed:
        raise typer.Exit(canceled())
    write_config_data(state.config.config_path, updated)
    typer.echo(f"Configuration saved to: {state.config.config_path}")
    raise typer.Exit(0)


def _prompt_notification_route(existing: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    route_type = prompt_choice(
        "Route type",
        [
            ("webhook", "Webhook"),
            ("slack", "Slack"),
            ("discord", "Discord"),
            ("email", "Email"),
        ],
        default_value=str(existing.get("type", "webhook")) if existing else "webhook",
    )
    if route_type is None:
        return None
    route_name = prompt_text(
        "Route name",
        default=str(existing.get("name")) if existing and existing.get("name") else f"{route_type}_default",
    )
    if route_name is None:
        return None
    events = prompt_comma_separated(
        "Events (comma-separated)",
        default=",".join(existing.get("events", ["job_failed"])) if existing else "job_failed",
    )
    if events is None:
        return None
    if route_type == "email":
        recipients = prompt_comma_separated(
            "Email recipient(s), comma-separated",
            default=",".join(existing.get("to", [])) if existing else "",
        )
        if recipients is None:
            return None
        from_address = prompt_text("From address", default=str(existing.get("from", "")) if existing else "")
        smtp_host = prompt_text("SMTP host", default=str(existing.get("smtp_host", "")) if existing else "")
        if from_address is None or smtp_host is None:
            return None
        smtp_port = prompt_text("SMTP port", default=str(existing.get("smtp_port", 587)) if existing else "587")
        if smtp_port is None:
            return None
        smtp_username = prompt_text("SMTP username", default=str(existing.get("smtp_username", "")) if existing else "")
        smtp_password = prompt_text("SMTP password", default=str(existing.get("smtp_password", "")) if existing else "")
        smtp_starttls = prompt_confirm("Use STARTTLS?", default=bool(existing.get("smtp_starttls", True)) if existing else True)
        smtp_ssl = prompt_confirm("Use SMTP SSL?", default=bool(existing.get("smtp_ssl", False)) if existing else False)
        if smtp_starttls is None or smtp_ssl is None:
            return None
        route = {
            "name": route_name,
            "type": route_type,
            "enabled": True,
            "events": events or ["job_failed"],
            "to": recipients or [],
            "from": from_address,
            "smtp_host": smtp_host,
            "smtp_port": int(str(smtp_port)),
            "smtp_starttls": smtp_starttls,
            "smtp_ssl": smtp_ssl,
        }
        if smtp_username:
            route["smtp_username"] = smtp_username
        if smtp_password:
            route["smtp_password"] = smtp_password
        return route

    url = prompt_text("Route URL", default=str(existing.get("url", "")) if existing else "")
    if url is None:
        return None
    return {
        "name": route_name,
        "type": route_type,
        "url": url,
        "enabled": True,
        "events": events or ["job_failed"],
        "headers": existing.get("headers", {}) if existing else {},
    }


def _run_config_wizard(*, config_path: Path, current: Dict[str, Any]) -> Dict[str, Any]:
    updated = normalize_config_data(current)
    jobs_dir = prompt_text("Jobs directory", default=str(updated.get("jobs_dir", DEFAULT_CONFIG["jobs_dir"])))
    if jobs_dir is None:
        raise typer.Exit(canceled())
    partition = prompt_text("Default partition", default=str(updated["slurm_defaults"].get("partition", "compute")))
    time_limit = prompt_text("Default time limit", default=str(updated["slurm_defaults"].get("time", "24:00:00")))
    memory = prompt_text("Default memory", default=str(updated["slurm_defaults"].get("mem", "16G")))
    wandb_entity = prompt_text("W&B entity", default=str(updated.get("wandb", {}).get("entity") or ""))
    ui_mode = prompt_choice(
        "UI mode",
        [("auto", "auto"), ("plain", "plain"), ("rich", "rich")],
        default_value=str(updated.get("ui", {}).get("mode", "auto")),
    )
    interactive_enabled = prompt_confirm(
        "Enable interactive prompts?",
        default=bool(updated.get("ui", {}).get("interactive", True)),
    )
    show_banner = prompt_confirm(
        "Show banner and command picker hints?",
        default=bool(updated.get("ui", {}).get("show_banner", True)),
    )
    if None in {partition, time_limit, memory, ui_mode, interactive_enabled, show_banner}:
        raise typer.Exit(canceled())

    routes = updated.get("notifications", {}).get("routes", [])
    configure_notifications = prompt_confirm(
        "Configure a notification route now?",
        default=bool(routes),
    )
    if configure_notifications is None:
        raise typer.Exit(canceled())
    route = None
    if configure_notifications:
        route = _prompt_notification_route(routes[0] if routes else None)
        if route is None:
            raise typer.Exit(canceled())

    updated["jobs_dir"] = jobs_dir
    updated.setdefault("slurm_defaults", {})
    updated["slurm_defaults"]["partition"] = partition
    updated["slurm_defaults"]["time"] = time_limit
    updated["slurm_defaults"]["mem"] = memory
    updated.setdefault("wandb", {})
    updated["wandb"]["entity"] = wandb_entity or None
    updated.setdefault("ui", {})
    updated["ui"]["mode"] = ui_mode
    updated["ui"]["interactive"] = interactive_enabled
    updated["ui"]["show_banner"] = show_banner
    updated.setdefault("notifications", {})
    updated["notifications"].setdefault("defaults", DEFAULT_CONFIG["notifications"]["defaults"])
    updated["notifications"].setdefault("collection_final", DEFAULT_CONFIG["notifications"]["collection_final"])
    updated["notifications"]["routes"] = [route] if route else []
    return updated
