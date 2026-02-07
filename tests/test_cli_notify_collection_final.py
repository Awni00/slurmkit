"""Tests for `slurmkit notify collection-final` parser and handler behavior."""

from argparse import Namespace
from pathlib import Path

import yaml

from slurmkit.cli import commands
from slurmkit.collections import CollectionManager
from slurmkit.config import Config
from slurmkit.notifications import DeliveryResult, NotificationService


def _make_config(tmp_path: Path, data: dict) -> Config:
    """Create config file and return Config instance."""
    config_dir = tmp_path / ".slurm-kit"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(data, f)
    return Config(project_root=tmp_path)


def _args(**overrides):
    base = {
        "job_id": "100",
        "collection": None,
        "route": None,
        "strict": False,
        "dry_run": False,
        "force": False,
        "no_refresh": True,
    }
    base.update(overrides)
    return Namespace(**base)


def test_notify_collection_final_parser_args():
    """Parser accepts notify collection-final arguments."""
    from slurmkit.cli.main import create_parser

    parser = create_parser()
    args = parser.parse_args(
        [
            "notify",
            "collection-final",
            "--job-id",
            "123",
            "--collection",
            "exp",
            "--route",
            "r1",
            "--route",
            "r2",
            "--strict",
            "--dry-run",
            "--force",
            "--no-refresh",
        ]
    )

    assert args.command == "notify"
    assert args.notify_action == "collection-final"
    assert args.job_id == "123"
    assert args.collection == "exp"
    assert args.route == ["r1", "r2"]
    assert args.strict is True
    assert args.dry_run is True
    assert args.force is True
    assert args.no_refresh is True


def test_cmd_notify_collection_final_non_terminal_skips(tmp_path, monkeypatch, capsys):
    """Running/pending collections should skip notification send."""
    config = _make_config(
        tmp_path,
        {
            "collections_dir": ".job-collections/",
            "notifications": {
                "routes": [
                    {
                        "name": "r",
                        "type": "webhook",
                        "url": "https://example.test/hook",
                        "events": ["collection_failed", "collection_completed"],
                    }
                ]
            },
        },
    )
    manager = CollectionManager(config=config)
    collection = manager.create("exp")
    collection.add_job(job_name="job1", job_id="100", state="RUNNING")
    manager.save(collection)
    service = NotificationService(config=config)

    calls = {"dispatch": 0}

    def fake_dispatch(**_kwargs):
        calls["dispatch"] += 1
        return []

    monkeypatch.setattr(service, "dispatch", fake_dispatch)
    monkeypatch.setattr(commands, "get_configured_config", lambda _args: config)
    monkeypatch.setattr(commands, "NotificationService", lambda config=None: service)

    exit_code = commands.cmd_notify_collection_final(_args(job_id="100"))
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "not terminal yet" in out
    assert calls["dispatch"] == 0


def test_cmd_notify_collection_final_completed_event(tmp_path, monkeypatch):
    """Terminal successful collection should emit collection_completed payload."""
    config = _make_config(
        tmp_path,
        {
            "collections_dir": ".job-collections/",
            "notifications": {
                "routes": [
                    {
                        "name": "r",
                        "type": "webhook",
                        "url": "https://example.test/hook",
                        "events": ["collection_completed"],
                    }
                ]
            },
        },
    )
    manager = CollectionManager(config=config)
    collection = manager.create("exp")
    collection.add_job(job_name="job1", job_id="100", state="COMPLETED")
    manager.save(collection)
    service = NotificationService(config=config)

    captured = {"payload": None}

    def fake_dispatch(payload, routes, dry_run=False):
        captured["payload"] = payload
        return [DeliveryResult(route_name=routes[0].name, route_type=routes[0].route_type, success=True, attempts=1)]

    monkeypatch.setattr(service, "dispatch", fake_dispatch)
    monkeypatch.setattr(commands, "get_configured_config", lambda _args: config)
    monkeypatch.setattr(commands, "NotificationService", lambda config=None: service)

    exit_code = commands.cmd_notify_collection_final(_args(job_id="100"))

    assert exit_code == 0
    assert captured["payload"]["event"] == "collection_completed"
    assert captured["payload"]["collection"]["name"] == "exp"


def test_cmd_notify_collection_final_failed_event(tmp_path, monkeypatch):
    """Terminal failed collection should emit collection_failed payload."""
    config = _make_config(
        tmp_path,
        {
            "collections_dir": ".job-collections/",
            "notifications": {
                "routes": [
                    {
                        "name": "r",
                        "type": "webhook",
                        "url": "https://example.test/hook",
                        "events": ["collection_failed"],
                    }
                ]
            },
        },
    )
    manager = CollectionManager(config=config)
    collection = manager.create("exp")
    collection.add_job(job_name="job1", job_id="100", state="FAILED")
    manager.save(collection)
    service = NotificationService(config=config)

    captured = {"payload": None}

    def fake_dispatch(payload, routes, dry_run=False):
        captured["payload"] = payload
        return [DeliveryResult(route_name=routes[0].name, route_type=routes[0].route_type, success=True, attempts=1)]

    monkeypatch.setattr(service, "dispatch", fake_dispatch)
    monkeypatch.setattr(commands, "get_configured_config", lambda _args: config)
    monkeypatch.setattr(commands, "NotificationService", lambda config=None: service)

    exit_code = commands.cmd_notify_collection_final(_args(job_id="100"))
    assert exit_code == 0
    assert captured["payload"]["event"] == "collection_failed"


def test_cmd_notify_collection_final_dedup_and_force(tmp_path, monkeypatch):
    """Repeated call should dedup unless --force is used."""
    config = _make_config(
        tmp_path,
        {
            "collections_dir": ".job-collections/",
            "notifications": {
                "routes": [
                    {
                        "name": "r",
                        "type": "webhook",
                        "url": "https://example.test/hook",
                        "events": ["collection_completed"],
                    }
                ]
            },
        },
    )
    manager = CollectionManager(config=config)
    collection = manager.create("exp")
    collection.add_job(job_name="job1", job_id="100", state="COMPLETED")
    manager.save(collection)
    service = NotificationService(config=config)

    calls = {"dispatch": 0}

    def fake_dispatch(payload, routes, dry_run=False):
        calls["dispatch"] += 1
        return [DeliveryResult(route_name=routes[0].name, route_type=routes[0].route_type, success=True, attempts=1)]

    monkeypatch.setattr(service, "dispatch", fake_dispatch)
    monkeypatch.setattr(commands, "get_configured_config", lambda _args: config)
    monkeypatch.setattr(commands, "NotificationService", lambda config=None: service)

    assert commands.cmd_notify_collection_final(_args(job_id="100")) == 0
    assert commands.cmd_notify_collection_final(_args(job_id="100")) == 0
    assert calls["dispatch"] == 1

    assert commands.cmd_notify_collection_final(_args(job_id="100", force=True)) == 0
    assert calls["dispatch"] == 2


def test_cmd_notify_collection_final_ambiguous_collection_errors(tmp_path, monkeypatch):
    """Ambiguous collection resolution should return non-zero and skip send."""
    config = _make_config(
        tmp_path,
        {
            "collections_dir": ".job-collections/",
            "notifications": {
                "routes": [
                    {
                        "name": "r",
                        "type": "webhook",
                        "url": "https://example.test/hook",
                        "events": ["collection_completed", "collection_failed"],
                    }
                ]
            },
        },
    )
    manager = CollectionManager(config=config)
    c1 = manager.create("exp1")
    c1.add_job(job_name="job", job_id="100", state="COMPLETED")
    manager.save(c1)
    c2 = manager.create("exp2")
    c2.add_job(job_name="job", job_id="100", state="COMPLETED")
    manager.save(c2)
    service = NotificationService(config=config)

    monkeypatch.setattr(commands, "get_configured_config", lambda _args: config)
    monkeypatch.setattr(commands, "NotificationService", lambda config=None: service)

    assert commands.cmd_notify_collection_final(_args(job_id="100")) == 1


def test_cmd_notify_collection_final_ai_callback_success(tmp_path, monkeypatch):
    """AI callback output should be attached to payload when callback succeeds."""
    module_path = tmp_path / "ai_cb.py"
    module_path.write_text(
        "def summarize(report):\n"
        "    return 'AI concise summary'\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    config = _make_config(
        tmp_path,
        {
            "collections_dir": ".job-collections/",
            "notifications": {
                "collection_final": {
                    "ai": {
                        "enabled": True,
                        "callback": "ai_cb:summarize",
                    }
                },
                "routes": [
                    {
                        "name": "r",
                        "type": "webhook",
                        "url": "https://example.test/hook",
                        "events": ["collection_completed"],
                    }
                ],
            },
        },
    )
    manager = CollectionManager(config=config)
    c = manager.create("exp")
    c.add_job(job_name="job", job_id="100", state="COMPLETED")
    manager.save(c)
    service = NotificationService(config=config)

    captured = {"payload": None}

    def fake_dispatch(payload, routes, dry_run=False):
        captured["payload"] = payload
        return [DeliveryResult(route_name=routes[0].name, route_type=routes[0].route_type, success=True, attempts=1)]

    monkeypatch.setattr(service, "dispatch", fake_dispatch)
    monkeypatch.setattr(commands, "get_configured_config", lambda _args: config)
    monkeypatch.setattr(commands, "NotificationService", lambda config=None: service)

    assert commands.cmd_notify_collection_final(_args(job_id="100")) == 0
    assert captured["payload"]["ai_status"] == "available"
    assert captured["payload"]["ai_summary"] == "AI concise summary"


def test_cmd_notify_collection_final_ai_callback_failure_fallback(tmp_path, monkeypatch):
    """AI callback failures should not block deterministic notification send."""
    config = _make_config(
        tmp_path,
        {
            "collections_dir": ".job-collections/",
            "notifications": {
                "collection_final": {
                    "ai": {
                        "enabled": True,
                        "callback": "missing.module:fn",
                    }
                },
                "routes": [
                    {
                        "name": "r",
                        "type": "webhook",
                        "url": "https://example.test/hook",
                        "events": ["collection_completed"],
                    }
                ],
            },
        },
    )
    manager = CollectionManager(config=config)
    c = manager.create("exp")
    c.add_job(job_name="job", job_id="100", state="COMPLETED")
    manager.save(c)
    service = NotificationService(config=config)

    captured = {"payload": None}

    def fake_dispatch(payload, routes, dry_run=False):
        captured["payload"] = payload
        return [DeliveryResult(route_name=routes[0].name, route_type=routes[0].route_type, success=True, attempts=1)]

    monkeypatch.setattr(service, "dispatch", fake_dispatch)
    monkeypatch.setattr(commands, "get_configured_config", lambda _args: config)
    monkeypatch.setattr(commands, "NotificationService", lambda config=None: service)

    assert commands.cmd_notify_collection_final(_args(job_id="100")) == 0
    assert captured["payload"]["ai_status"] == "unavailable"
    assert captured["payload"]["ai_summary"] is None


def test_cmd_notify_collection_final_event_route_filtering_skip(tmp_path, monkeypatch):
    """No route subscribed to collection_completed should skip send with exit 0."""
    config = _make_config(
        tmp_path,
        {
            "collections_dir": ".job-collections/",
            "notifications": {
                "routes": [
                    {
                        "name": "r_failed_only",
                        "type": "webhook",
                        "url": "https://example.test/hook",
                        "events": ["collection_failed"],
                    }
                ]
            },
        },
    )
    manager = CollectionManager(config=config)
    c = manager.create("exp")
    c.add_job(job_name="job", job_id="100", state="COMPLETED")
    manager.save(c)
    service = NotificationService(config=config)

    calls = {"dispatch": 0}

    def fake_dispatch(**_kwargs):
        calls["dispatch"] += 1
        return []

    monkeypatch.setattr(service, "dispatch", fake_dispatch)
    monkeypatch.setattr(commands, "get_configured_config", lambda _args: config)
    monkeypatch.setattr(commands, "NotificationService", lambda config=None: service)

    assert commands.cmd_notify_collection_final(_args(job_id="100")) == 0
    assert calls["dispatch"] == 0


def test_cmd_notify_collection_final_strict_vs_non_strict(tmp_path, monkeypatch):
    """Strict mode should fail if any route fails for collection-final sends."""
    config = _make_config(
        tmp_path,
        {
            "collections_dir": ".job-collections/",
            "notifications": {
                "routes": [
                    {
                        "name": "r1",
                        "type": "webhook",
                        "url": "https://example.test/1",
                        "events": ["collection_completed"],
                    },
                    {
                        "name": "r2",
                        "type": "webhook",
                        "url": "https://example.test/2",
                        "events": ["collection_completed"],
                    },
                ]
            },
        },
    )
    manager = CollectionManager(config=config)
    c = manager.create("exp")
    c.add_job(job_name="job", job_id="100", state="COMPLETED")
    manager.save(c)
    service = NotificationService(config=config)

    def fake_dispatch(payload, routes, dry_run=False):
        return [
            DeliveryResult(route_name=routes[0].name, route_type=routes[0].route_type, success=True, attempts=1),
            DeliveryResult(route_name=routes[1].name, route_type=routes[1].route_type, success=False, attempts=1, error="boom"),
        ]

    monkeypatch.setattr(service, "dispatch", fake_dispatch)
    monkeypatch.setattr(commands, "get_configured_config", lambda _args: config)
    monkeypatch.setattr(commands, "NotificationService", lambda config=None: service)

    assert commands.cmd_notify_collection_final(_args(job_id="100", strict=False)) == 0
    assert commands.cmd_notify_collection_final(_args(job_id="100", strict=True, force=True)) == 1


def test_cmd_notify_collection_final_with_email_route_output(tmp_path, monkeypatch, capsys):
    """Collection-final command should print email route delivery lines."""
    config = _make_config(
        tmp_path,
        {
            "collections_dir": ".job-collections/",
            "notifications": {
                "routes": [
                    {
                        "name": "team_email",
                        "type": "email",
                        "to": "ops@example.com",
                        "from": "noreply@example.com",
                        "smtp_host": "smtp.example.com",
                        "events": ["collection_completed"],
                    }
                ]
            },
        },
    )
    manager = CollectionManager(config=config)
    c = manager.create("exp")
    c.add_job(job_name="job", job_id="100", state="COMPLETED")
    manager.save(c)
    service = NotificationService(config=config)

    def fake_dispatch(payload, routes, dry_run=False):
        return [
            DeliveryResult(
                route_name=routes[0].name,
                route_type=routes[0].route_type,
                success=True,
                attempts=0,
                dry_run=True,
            )
        ]

    monkeypatch.setattr(service, "dispatch", fake_dispatch)
    monkeypatch.setattr(commands, "get_configured_config", lambda _args: config)
    monkeypatch.setattr(commands, "NotificationService", lambda config=None: service)

    exit_code = commands.cmd_notify_collection_final(_args(job_id="100", dry_run=True))
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "team_email (email)" in out
