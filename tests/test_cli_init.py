"""Tests for interactive init command flows."""

from argparse import Namespace
from pathlib import Path

import yaml

from slurmkit.cli import commands


def test_cmd_init_writes_notification_route(monkeypatch, tmp_path):
    """Init should support minimal notification route setup prompts."""
    answers = iter(
        [
            "jobs/",
            "compute",
            "12:00:00",
            "8G",
            "",
            "y",
            "slack",
            "team_alerts",
            "${SLACK_WEBHOOK_URL}",
            "job_failed,job_completed",
        ]
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    exit_code = commands.cmd_init(Namespace(force=False))
    assert exit_code == 0

    config_path = Path(tmp_path) / ".slurm-kit" / "config.yaml"
    assert config_path.exists()

    with open(config_path, "r") as f:
        data = yaml.safe_load(f)

    assert "notifications" in data
    assert data["notifications"]["defaults"]["events"] == ["job_failed"]
    assert len(data["notifications"]["routes"]) == 1
    route = data["notifications"]["routes"][0]
    assert route["name"] == "team_alerts"
    assert route["type"] == "slack"
    assert route["url"] == "${SLACK_WEBHOOK_URL}"
    assert route["events"] == ["job_failed", "job_completed"]
