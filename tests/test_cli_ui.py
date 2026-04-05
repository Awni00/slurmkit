"""Tests for CLI UI context and rendering primitives."""

from datetime import datetime
from types import SimpleNamespace

import pytest

from slurmkit.cli.ui.models import MetricItem
from slurmkit.cli.ui.context import UIResolutionError, resolve_ui_context
from slurmkit.cli.ui.plain import PlainBackend
from slurmkit.cli.ui.rich_backend import RichBackend
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
    args = SimpleNamespace(ui="plain")
    cfg = _FakeConfig(mode="rich")
    monkeypatch.setattr("slurmkit.cli.ui.context._is_rich_available", lambda: True)
    monkeypatch.setattr("slurmkit.cli.ui.context._stdout_isatty", lambda: True)

    ctx = resolve_ui_context(args, cfg)
    assert ctx.effective_mode == "plain"


def test_resolve_ui_context_auto_falls_back_to_plain(monkeypatch):
    """Auto mode should fall back when rich is unavailable or non-tty."""
    args = SimpleNamespace(ui="auto")
    cfg = _FakeConfig(mode="plain")
    monkeypatch.setattr("slurmkit.cli.ui.context._is_rich_available", lambda: False)
    monkeypatch.setattr("slurmkit.cli.ui.context._stdout_isatty", lambda: True)

    ctx = resolve_ui_context(args, cfg)
    assert ctx.effective_mode == "plain"


def test_resolve_ui_context_rich_missing_raises(monkeypatch):
    """Explicit rich mode should error if rich dependency is missing."""
    args = SimpleNamespace(ui="rich")
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
    """Collection show report should include configured primary/history columns."""
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
        jobs_table_columns=["job_name", "primary_job_id", "primary_state", "history"],
    )

    assert "Primary Job ID" in report.jobs_table.headers
    assert "History" in report.jobs_table.headers
    assert report.summary_title == (
        "Summary: 1 primary jobs | 2 submitted SLURM jobs (incl. resubmissions)"
    )


def test_collection_show_report_hostname_column_is_opt_in():
    """Hostname should only appear when configured as a column."""

    class _Collection:
        name = "exp_host"
        description = ""
        created_at = "2026-02-07T10:00:00"
        updated_at = "2026-02-07T11:00:00"
        cluster = "cluster-a"

    base_job = {
        "job_name": "job_a",
        "effective_job_id": "101",
        "effective_state_raw": "RUNNING",
        "effective_attempt_label": "primary",
        "resubmissions_count": 0,
        "effective_hostname": "cluster-a",
        "primary_job_id": "101",
    }
    summary = {
        "total": 1,
        "completed": 0,
        "failed": 0,
        "running": 1,
        "pending": 0,
        "unknown": 0,
        "not_submitted": 0,
    }

    report_default = build_collection_show_report(
        collection=_Collection(),
        jobs=[base_job],
        summary=summary,
        attempt_mode="latest",
        submission_group=None,
    )
    assert "Hostname" not in report_default.jobs_table.headers

    report_with_hostname = build_collection_show_report(
        collection=_Collection(),
        jobs=[base_job],
        summary=summary,
        attempt_mode="latest",
        submission_group=None,
        jobs_table_columns=["job_name", "hostname", "state"],
    )
    assert report_with_hostname.jobs_table.headers == ["Job Name", "Hostname", "State"]


def test_collection_show_report_runtime_column_completed_and_running():
    """Runtime should be computed from start/end timestamps."""

    class _Collection:
        name = "exp_runtime"
        description = ""
        created_at = "2026-02-07T10:00:00"
        updated_at = "2026-02-07T11:00:00"
        cluster = "cluster-a"

    report = build_collection_show_report(
        collection=_Collection(),
        jobs=[
            {
                "job_name": "completed_job",
                "effective_job_id": "101",
                "effective_state_raw": "COMPLETED",
                "effective_attempt_label": "primary",
                "resubmissions_count": 0,
                "primary_job_id": "101",
                "effective_started_at": "2026-02-07T10:00:00",
                "effective_completed_at": "2026-02-07T10:01:05",
            },
            {
                "job_name": "running_job",
                "effective_job_id": "102",
                "effective_state_raw": "RUNNING",
                "effective_attempt_label": "primary",
                "resubmissions_count": 0,
                "primary_job_id": "102",
                "effective_started_at": "2026-02-07T10:00:00",
                "effective_completed_at": None,
            },
        ],
        summary={
            "total": 2,
            "completed": 1,
            "failed": 0,
            "running": 1,
            "pending": 0,
            "unknown": 0,
            "not_submitted": 0,
        },
        attempt_mode="latest",
        submission_group=None,
        jobs_table_columns=["job_name", "runtime"],
        runtime_now=datetime.fromisoformat("2026-02-07T10:01:30+00:00"),
    )

    assert report.jobs_table.rows[0][1] == "1m 05s"
    assert report.jobs_table.rows[1][1] == "1m 30s"


def test_collection_show_report_can_skip_jobs_table():
    """Summary-only views should not carry a jobs table."""

    class _Collection:
        name = "exp_summary_only"
        description = ""
        created_at = "2026-02-07T10:00:00"
        updated_at = "2026-02-07T11:00:00"
        cluster = "cluster-a"

    report = build_collection_show_report(
        collection=_Collection(),
        jobs=[],
        summary={
            "total": 0,
            "completed": 0,
            "failed": 0,
            "running": 0,
            "pending": 0,
            "unknown": 0,
            "not_submitted": 0,
        },
        attempt_mode="latest",
        submission_group=None,
        include_jobs_table=False,
    )

    assert report.jobs_table is None


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


def test_rich_backend_output_path_cell_renders_short_hyperlink_label():
    backend = RichBackend()
    rendered = backend._render_output_link("/tmp/demo_output.out")
    assert rendered.plain == "output logs"
    assert any("link file://" in str(span.style) for span in rendered.spans)


def test_rich_backend_header_path_value_renders_relative_hyperlink():
    backend = RichBackend()
    rendered = backend._render_kv_value("Spec", "experiments/exp1/slurmkit/job_spec.yaml")
    assert rendered.plain == "experiments/exp1/slurmkit/job_spec.yaml"
    assert any("link file://" in str(span.style) for span in rendered.spans)
