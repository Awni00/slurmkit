"""Tests for the Typer-based CLI surface."""

from __future__ import annotations

from importlib import import_module

from typer.testing import CliRunner

from slurmkit.cli.app import app as cli_app


runner = CliRunner()
cli_module = import_module("slurmkit.cli.app")


def test_root_no_args_opens_home_when_prompting_enabled(monkeypatch):
    """Interactive no-arg invocations should route to the command picker."""
    called = {"home": 0}

    monkeypatch.setattr(cli_module, "can_prompt", lambda _state: True)
    monkeypatch.setattr(
        cli_module,
        "_home_impl",
        lambda _ctx: called.__setitem__("home", called["home"] + 1) or 0,
    )

    result = runner.invoke(cli_app, [])

    assert result.exit_code == 0
    assert called["home"] == 1


def test_root_no_args_prints_help_when_not_interactive():
    """Non-interactive no-arg invocations should print help."""
    result = runner.invoke(cli_app, [])
    assert result.exit_code == 0
    assert "Usage:" in result.stdout


def test_structured_output_disables_prompt_fallback(monkeypatch):
    """Structured output should fail fast instead of prompting for a collection."""
    monkeypatch.setattr(cli_module, "can_prompt", lambda _state: True)

    result = runner.invoke(cli_app, ["collections", "show", "--format", "json"])

    assert result.exit_code == 2
    assert "Missing collection argument." in (result.stderr or result.stdout)


def test_collections_refresh_all_flag(monkeypatch):
    """collections refresh --all should pass the all-collections flag."""
    captured = {}

    monkeypatch.setattr(
        cli_module,
        "_collection_refresh_impl",
        lambda _ctx, *, name, refresh_all: captured.update(
            {"name": name, "refresh_all": refresh_all}
        ) or 0,
    )

    result = runner.invoke(cli_app, ["collections", "refresh", "--all"])

    assert result.exit_code == 0
    assert captured == {"name": None, "refresh_all": True}
