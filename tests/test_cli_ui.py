"""Tests for CLI UI context and rendering primitives."""

from argparse import Namespace

import pytest

from slurmkit.cli.ui.models import MetricItem
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
    assert report.summary_title == (
        "Summary: 1 primary jobs | 2 submitted SLURM jobs (incl. resubmissions)"
    )


def test_collection_show_report_summary_counts_unsubmitted_primaries():
    """Summary counts should separate primary rows from submitted attempts."""

    class _Collection:
        name = "exp2"
        description = "demo"
        created_at = "2026-02-07T10:00:00"
        updated_at = "2026-02-07T11:00:00"
        cluster = "cluster-a"
        parameters = {}

    report = build_collection_show_report(
        collection=_Collection(),
        jobs=[
            {
                "job_name": "job_submitted",
                "primary_job_id": "200",
                "resubmissions_count": 2,
            },
            {
                "job_name": "job_not_submitted",
                "primary_job_id": None,
                "resubmissions_count": 0,
            },
        ],
        summary={
            "total": 2,
            "completed": 0,
            "failed": 0,
            "running": 0,
            "pending": 0,
            "unknown": 0,
            "not_submitted": 1,
        },
        attempt_mode="latest",
        submission_group=None,
    )

    assert report.summary_title == (
        "Summary: 2 primary jobs | 3 submitted SLURM jobs (incl. resubmissions)"
    )


def test_collection_show_report_summary_details_break_down_raw_states():
    """Summary metrics should include present raw-state breakdowns only."""

    class _Collection:
        name = "exp3"
        description = "demo"
        created_at = "2026-02-07T10:00:00"
        updated_at = "2026-02-07T11:00:00"
        cluster = "cluster-a"
        parameters = {}

    report = build_collection_show_report(
        collection=_Collection(),
        jobs=[
            {
                "job_name": "job_completed",
                "primary_job_id": "1",
                "resubmissions_count": 0,
                "effective_state": "completed",
                "effective_state_raw": "COMPLETED",
            },
            {
                "job_name": "job_failed_a",
                "primary_job_id": "2",
                "resubmissions_count": 0,
                "effective_state": "failed",
                "effective_state_raw": "FAILED",
            },
            {
                "job_name": "job_failed_b",
                "primary_job_id": "3",
                "resubmissions_count": 0,
                "effective_state": "failed",
                "effective_state_raw": "TIMEOUT",
            },
            {
                "job_name": "job_failed_c",
                "primary_job_id": "4",
                "resubmissions_count": 0,
                "effective_state": "failed",
                "effective_state_raw": "TIMEOUT",
            },
            {
                "job_name": "job_failed_d",
                "primary_job_id": "5",
                "resubmissions_count": 0,
                "effective_state": "failed",
                "effective_state_raw": "CANCELLED",
            },
            {
                "job_name": "job_running",
                "primary_job_id": "6",
                "resubmissions_count": 0,
                "effective_state": "running",
                "effective_state_raw": "RUNNING",
            },
            {
                "job_name": "job_pending",
                "primary_job_id": "7",
                "resubmissions_count": 0,
                "effective_state": "pending",
                "effective_state_raw": "PENDING",
            },
            {
                "job_name": "job_pending_placeholder",
                "primary_job_id": "8",
                "resubmissions_count": 0,
                "effective_state": "pending",
                "effective_state_raw": "N/A",
            },
        ],
        summary={
            "total": 8,
            "completed": 1,
            "failed": 4,
            "running": 1,
            "pending": 2,
            "unknown": 0,
            "not_submitted": 0,
        },
        attempt_mode="latest",
        submission_group=None,
    )

    details = {item.label: item.details for item in report.summary_metrics}
    assert details["Completed"] == "COMPLETED: 1"
    assert details["Failed"] == "TIMEOUT: 2, CANCELLED: 1, FAILED: 1"
    assert details["Running"] == "RUNNING: 1"
    assert details["Pending"] == "PENDING: 1"
    assert details["Not Submitted"] is None
    assert "NODE_FAIL: 0" not in str(details["Failed"])


def test_plain_backend_metrics_renders_indented_details_line(capsys):
    """Plain metrics renderer should print details as an indented second line."""
    backend = PlainBackend(enable_color=False)
    backend.metrics(
        "Summary",
        [
            MetricItem(
                label="Failed",
                value="3",
                percent=30.0,
                state="failed",
                details="FAILED: 2, TIMEOUT: 1",
            )
        ],
    )

    output = capsys.readouterr().out
    assert "Summary" in output
    assert "  Failed: 3 (30.0%)" in output
    assert "    FAILED: 2, TIMEOUT: 1" in output
