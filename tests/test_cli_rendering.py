"""Tests for CLI render helpers."""

from types import SimpleNamespace

from slurmkit.cli.rendering import render_collection_show
from slurmkit.cli.ui.models import CollectionShowReport, MetricItem, TableSection


class _FakeConfig:
    def __init__(self, values: dict):
        self._values = values

    def get(self, key: str, default=None):
        return self._values.get(key, default)


def _sample_report(row_count: int) -> CollectionShowReport:
    rows = [["job_a", "RUNNING"] for _ in range(row_count)]
    return CollectionShowReport(
        title="Collection: exp1",
        metadata=[("Collection", "exp1")],
        summary_title="Summary",
        summary_metrics=[MetricItem(label="Running", value="1", percent=100.0, state="running")],
        jobs_table=TableSection(
            title=f"Jobs ({row_count}):",
            headers=["Job Name", "State"],
            rows=rows,
            status_columns=(1,),
        ),
    )


def test_render_collection_show_uses_pager_when_enabled(monkeypatch):
    called = {"count": 0, "content": "", "color": None}

    def _capture(message, color=None):
        called["count"] += 1
        called["content"] = message
        called["color"] = color

    monkeypatch.setattr("slurmkit.cli.rendering.supports_interaction", lambda: True)
    monkeypatch.setattr("slurmkit.cli.rendering.click.echo_via_pager", _capture)

    render_collection_show(
        args=SimpleNamespace(ui="plain"),
        config=_FakeConfig(
            {
                "ui.mode": "plain",
                "ui.collections_show.pager": "less",
            }
        ),
        report=_sample_report(1),
        enable_pager=True,
    )

    assert called["count"] == 1
    assert "Collection: exp1" in called["content"]
    assert called["color"] is True


def test_render_collection_show_skips_pager_when_non_interactive(monkeypatch):
    called = {"count": 0}

    def _capture(_message, color=None):
        called["count"] += 1

    monkeypatch.setattr("slurmkit.cli.rendering.supports_interaction", lambda: False)
    monkeypatch.setattr("slurmkit.cli.rendering.click.echo_via_pager", _capture)

    render_collection_show(
        args=SimpleNamespace(ui="plain"),
        config=_FakeConfig(
            {
                "ui.mode": "plain",
                "ui.collections_show.pager": "less",
            }
        ),
        report=_sample_report(100),
        enable_pager=True,
    )

    assert called["count"] == 0


def test_render_collection_show_rich_pager_preserves_ansi(monkeypatch):
    called = {"count": 0, "content": "", "color": None}

    def _capture(message, color=None):
        called["count"] += 1
        called["content"] = message
        called["color"] = color

    monkeypatch.setattr("slurmkit.cli.rendering.supports_interaction", lambda: True)
    monkeypatch.setattr("slurmkit.cli.rendering.click.echo_via_pager", _capture)

    render_collection_show(
        args=SimpleNamespace(ui="rich"),
        config=_FakeConfig(
            {
                "ui.mode": "rich",
                "ui.collections_show.pager": "less",
            }
        ),
        report=_sample_report(1),
        enable_pager=True,
    )

    assert called["count"] == 1
    assert called["color"] is True
    assert "\x1b[" in called["content"]


def test_render_collection_show_pager_none_skips_echo_pager(monkeypatch):
    called = {"count": 0}

    def _capture(_message, color=None):
        called["count"] += 1

    monkeypatch.setattr("slurmkit.cli.rendering.supports_interaction", lambda: True)
    monkeypatch.setattr("slurmkit.cli.rendering.click.echo_via_pager", _capture)

    render_collection_show(
        args=SimpleNamespace(ui="plain"),
        config=_FakeConfig(
            {
                "ui.mode": "plain",
                "ui.collections_show.pager": "none",
            }
        ),
        report=_sample_report(40),
        enable_pager=True,
    )

    assert called["count"] == 0
