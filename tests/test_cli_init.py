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


def test_cmd_init_writes_email_notification_route(monkeypatch, tmp_path):
    """Init should support SMTP email route setup prompts."""
    answers = iter(
        [
            "jobs/",
            "compute",
            "24:00:00",
            "16G",
            "",
            "y",
            "email",
            "team_email",
            "ops@example.com,ml@example.com",
            "noreply@example.com",
            "smtp.example.com",
            "587",
            "smtp_user",
            "smtp_pass",
            "y",
            "n",
            "job_failed,collection_failed",
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

    route = data["notifications"]["routes"][0]
    assert route["name"] == "team_email"
    assert route["type"] == "email"
    assert route["to"] == ["ops@example.com", "ml@example.com"]
    assert route["from"] == "noreply@example.com"
    assert route["smtp_host"] == "smtp.example.com"
    assert route["smtp_port"] == 587
    assert route["smtp_username"] == "smtp_user"
    assert route["smtp_password"] == "smtp_pass"
    assert route["smtp_starttls"] is True
    assert route["smtp_ssl"] is False
    assert route["events"] == ["job_failed", "collection_failed"]
