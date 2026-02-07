"""Tests for CLI UI context and rendering primitives."""

from argparse import Namespace

import pytest

from slurmkit.cli.ui.context import UIResolutionError, resolve_ui_context
from slurmkit.cli.ui.plain import PlainBackend
from slurmkit.cli.ui.reports import build_collection_show_report


class _FakeConfig:
    def __init__(self, mode="plain"):
        self.mode = mode

    def get(self, key, default=None):
        if key == "ui.mode":
            return self.mode
        return default


def test_resolve_ui_context_prefers_cli_override(monkeypatch):
    """CLI --ui should override config ui.mode."""
    args = Namespace(ui="plain")
    cfg = _FakeConfig(mode="rich")
    monkeypatch.setattr("slurmkit.cli.ui.context._is_rich_available", lambda: True)
    monkeypatch.setattr("slurmkit.cli.ui.context._stdout_isatty", lambda: True)

    ctx = resolve_ui_context(args, cfg)
    assert ctx.effective_mode == "plain"


def test_resolve_ui_context_auto_falls_back_to_plain(monkeypatch):
    """Auto mode should fall back when rich is unavailable or non-tty."""
    args = Namespace(ui="auto")
    cfg = _FakeConfig(mode="plain")
    monkeypatch.setattr("slurmkit.cli.ui.context._is_rich_available", lambda: False)
    monkeypatch.setattr("slurmkit.cli.ui.context._stdout_isatty", lambda: True)

    ctx = resolve_ui_context(args, cfg)
    assert ctx.effective_mode == "plain"


def test_resolve_ui_context_rich_missing_raises(monkeypatch):
    """Explicit rich mode should error if rich dependency is missing."""
    args = Namespace(ui="rich")
    cfg = _FakeConfig(mode="plain")
    monkeypatch.setattr("slurmkit.cli.ui.context._is_rich_available", lambda: False)
    monkeypatch.setattr("slurmkit.cli.ui.context._stdout_isatty", lambda: True)

    with pytest.raises(UIResolutionError):
        resolve_ui_context(args, cfg)


def test_plain_backend_status_color_toggle():
    """Plain backend should only emit ANSI codes when enabled."""
    backend_plain = PlainBackend(enable_color=False)
    assert backend_plain.style_status("FAILED") == "FAILED"

    backend_color = PlainBackend(enable_color=True)
    styled = backend_color.style_status("FAILED")
    assert styled != "FAILED"
    assert "\033[" in styled


def test_collection_show_report_supports_primary_and_history_columns():
    """Collection show report should include optional primary/history columns."""
    class _Collection:
        name = "exp1"
        description = "demo"
        created_at = "2026-02-07T10:00:00"
        updated_at = "2026-02-07T11:00:00"
        cluster = "cluster-a"
        parameters = {}

    report = build_collection_show_report(
        collection=_Collection(),
        jobs=[
            {
                "job_name": "job_a",
                "effective_job_id": "101",
                "effective_state_raw": "COMPLETED",
                "effective_attempt_label": "resubmission #1",
                "effective_submission_group": "g1",
                "resubmissions_count": 1,
                "effective_hostname": "cluster-a",
                "primary_job_id": "100",
                "primary_state_raw": "FAILED",
                "attempt_history": ["100(FAILED)", "101(COMPLETED)"],
            }
        ],
        summary={
            "total": 1,
            "completed": 1,
            "failed": 0,
            "running": 0,
            "pending": 0,
            "unknown": 0,
            "not_submitted": 0,
        },
        attempt_mode="latest",
        submission_group="g1",
        show_primary=True,
        show_history=True,
    )

    assert "Primary Job ID" in report.jobs_table.headers
    assert "History" in report.jobs_table.headers
