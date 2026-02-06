"""Tests for slurmkit.notifications module."""

from argparse import Namespace
from pathlib import Path

import yaml

from slurmkit.collections import CollectionManager
from slurmkit.config import Config
from slurmkit.notifications import (
    EVENT_JOB_COMPLETED,
    EVENT_JOB_FAILED,
    NotificationService,
    SCHEMA_VERSION,
)


def _make_config(tmp_path: Path, data: dict) -> Config:
    """Create config file and return Config instance."""
    config_dir = tmp_path / ".slurm-kit"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(data, f)
    return Config(project_root=tmp_path)


def test_route_defaults_event_subscription(tmp_path):
    """Routes without events default to job_failed."""
    config = _make_config(
        tmp_path,
        {
            "notifications": {
                "routes": [
                    {"name": "default_route", "type": "webhook", "url": "https://example.test/hook"}
                ]
            }
        },
    )
    service = NotificationService(config=config)

    failed = service.resolve_routes(event=EVENT_JOB_FAILED)
    completed = service.resolve_routes(event=EVENT_JOB_COMPLETED)

    assert len(failed.routes) == 1
    assert len(completed.routes) == 0


def test_env_interpolation_success(tmp_path, monkeypatch):
    """Route URL and headers support ${ENV_VAR} interpolation."""
    monkeypatch.setenv("TEST_NOTIFY_URL", "https://hooks.example.test/abc")
    monkeypatch.setenv("TEST_NOTIFY_TOKEN", "secret-token")

    config = _make_config(
        tmp_path,
        {
            "notifications": {
                "routes": [
                    {
                        "name": "env_route",
                        "type": "webhook",
                        "url": "${TEST_NOTIFY_URL}",
                        "headers": {"Authorization": "Bearer ${TEST_NOTIFY_TOKEN}"},
                    }
                ]
            }
        },
    )
    service = NotificationService(config=config)
    resolution = service.resolve_routes(event=EVENT_JOB_FAILED)

    assert resolution.errors == []
    assert len(resolution.routes) == 1
    route = resolution.routes[0]
    assert route.url == "https://hooks.example.test/abc"
    assert route.headers["Authorization"] == "Bearer secret-token"


def test_env_interpolation_missing_var_is_route_error(tmp_path, monkeypatch):
    """Missing env vars should become route-level errors."""
    monkeypatch.delenv("MISSING_NOTIFY_URL", raising=False)
    config = _make_config(
        tmp_path,
        {
            "notifications": {
                "routes": [
                    {"name": "bad_route", "type": "webhook", "url": "${MISSING_NOTIFY_URL}"}
                ]
            }
        },
    )
    service = NotificationService(config=config)
    resolution = service.resolve_routes(event=EVENT_JOB_FAILED)

    assert len(resolution.routes) == 0
    assert len(resolution.errors) == 1
    assert "Missing environment variable" in resolution.errors[0]


def test_route_filtering_and_unknown_route_error(tmp_path):
    """Route filtering should select requested routes and flag unknown names."""
    config = _make_config(
        tmp_path,
        {
            "notifications": {
                "routes": [
                    {"name": "a", "type": "webhook", "url": "https://example.test/a"},
                    {"name": "b", "type": "webhook", "url": "https://example.test/b"},
                ]
            }
        },
    )
    service = NotificationService(config=config)
    resolution = service.resolve_routes(
        event=EVENT_JOB_FAILED,
        route_names=["b", "missing"],
    )

    assert [route.name for route in resolution.routes] == ["b"]
    assert len(resolution.errors) == 1
    assert "Unknown notification route 'missing'" in resolution.errors[0]


def test_route_retry_timeout_backoff_fallbacks(tmp_path):
    """Routes should inherit retry/timeout values from defaults."""
    config = _make_config(
        tmp_path,
        {
            "notifications": {
                "defaults": {
                    "events": [EVENT_JOB_FAILED],
                    "timeout_seconds": 7,
                    "max_attempts": 4,
                    "backoff_seconds": 0.25,
                },
                "routes": [
                    {"name": "inherits", "type": "webhook", "url": "https://example.test/hook"}
                ],
            }
        },
    )
    service = NotificationService(config=config)
    resolution = service.resolve_routes(event=EVENT_JOB_FAILED)
    route = resolution.routes[0]

    assert route.timeout_seconds == 7
    assert route.max_attempts == 4
    assert route.backoff_seconds == 0.25


def test_build_payload_collection_match_and_failure_tail(tmp_path):
    """A matching collection should enrich payload and include failure tail."""
    output_path = tmp_path / "job.out"
    output_path.write_text("line1\nline2\nline3\n")

    config = _make_config(
        tmp_path,
        {
            "collections_dir": ".job-collections/",
            "notifications": {
                "routes": [
                    {"name": "hook", "type": "webhook", "url": "https://example.test/hook"}
                ]
            },
        },
    )
    manager = CollectionManager(config=config)
    collection = manager.create("exp1")
    collection.add_job(job_name="train", job_id="123", output_path=output_path, state="FAILED")
    manager.save(collection)

    service = NotificationService(config=config)
    payload, warnings = service.build_job_payload(
        job_id="123",
        exit_code=1,
        event=EVENT_JOB_FAILED,
        tail_lines=2,
    )

    assert warnings == []
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["context_source"] == "collection_match"
    assert payload["collection"]["name"] == "exp1"
    assert payload["job"]["job_name"] == "train"
    assert payload["job"]["output_tail"] == "line2\nline3"


def test_build_payload_no_match_is_env_only(tmp_path):
    """Missing collection match should still produce a valid env-only payload."""
    config = _make_config(
        tmp_path,
        {
            "notifications": {
                "routes": [
                    {"name": "hook", "type": "webhook", "url": "https://example.test/hook"}
                ]
            }
        },
    )
    service = NotificationService(config=config)
    payload, warnings = service.build_job_payload(
        job_id="999",
        exit_code=1,
        event=EVENT_JOB_FAILED,
    )

    assert payload["context_source"] == "env_only"
    assert payload["collection"] is None
    assert warnings == []


def test_build_payload_ambiguous_match_warns_and_uses_env_only(tmp_path):
    """Ambiguous job IDs across collections should not pick one arbitrarily."""
    config = _make_config(
        tmp_path,
        {
            "collections_dir": ".job-collections/",
            "notifications": {
                "routes": [
                    {"name": "hook", "type": "webhook", "url": "https://example.test/hook"}
                ]
            },
        },
    )
    manager = CollectionManager(config=config)
    c1 = manager.create("exp1")
    c1.add_job(job_name="job_a", job_id="321")
    manager.save(c1)
    c2 = manager.create("exp2")
    c2.add_job(job_name="job_b", job_id="321")
    manager.save(c2)

    service = NotificationService(config=config)
    payload, warnings = service.build_job_payload(
        job_id="321",
        exit_code=1,
        event=EVENT_JOB_FAILED,
    )

    assert payload["context_source"] == "ambiguous_match"
    assert payload["collection"] is None
    assert len(warnings) == 1
    assert "multiple collections" in warnings[0]


def test_output_tail_only_for_failed_event(tmp_path):
    """Output tail should not be attached for successful completion events."""
    output_path = tmp_path / "job.out"
    output_path.write_text("hello\nworld\n")

    config = _make_config(
        tmp_path,
        {
            "collections_dir": ".job-collections/",
            "notifications": {
                "routes": [
                    {"name": "hook", "type": "webhook", "url": "https://example.test/hook"}
                ]
            },
        },
    )
    manager = CollectionManager(config=config)
    collection = manager.create("exp")
    collection.add_job(job_name="job", job_id="777", output_path=output_path, state="COMPLETED")
    manager.save(collection)

    service = NotificationService(config=config)
    payload, _ = service.build_job_payload(
        job_id="777",
        exit_code=0,
        event=EVENT_JOB_COMPLETED,
    )
    assert payload["job"]["output_tail"] is None


def test_dispatch_retries_then_succeeds(tmp_path, monkeypatch):
    """HTTP 5xx should be retried until success within max_attempts."""
    config = _make_config(
        tmp_path,
        {
            "notifications": {
                "defaults": {"max_attempts": 3, "backoff_seconds": 0.01},
                "routes": [
                    {"name": "hook", "type": "webhook", "url": "https://example.test/hook"}
                ],
            }
        },
    )
    service = NotificationService(config=config)
    routes = service.resolve_routes(event=None).routes
    payload = service.build_test_payload()

    class _Response:
        def __init__(self, status_code):
            self.status_code = status_code
            self.text = ""

    calls = {"count": 0}

    def fake_post(*_args, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return _Response(500)
        return _Response(200)

    import slurmkit.notifications as notifications_module

    monkeypatch.setattr(notifications_module, "requests", Namespace(post=fake_post))
    monkeypatch.setattr(notifications_module.time, "sleep", lambda *_args, **_kwargs: None)

    results = service.dispatch(payload=payload, routes=routes, dry_run=False)
    assert len(results) == 1
    assert results[0].success is True
    assert results[0].attempts == 2


def test_partial_success_evaluation_strict_vs_non_strict(tmp_path, monkeypatch):
    """Strict mode should fail on partial route failures."""
    config = _make_config(
        tmp_path,
        {
            "notifications": {
                "defaults": {"max_attempts": 1},
                "routes": [
                    {"name": "ok", "type": "webhook", "url": "https://example.test/ok"},
                    {"name": "bad", "type": "webhook", "url": "https://example.test/bad"},
                ],
            }
        },
    )
    service = NotificationService(config=config)
    routes = service.resolve_routes(event=None).routes
    payload = service.build_test_payload()

    class _Response:
        def __init__(self, status_code):
            self.status_code = status_code
            self.text = ""

    def fake_post(url, **_kwargs):
        if url.endswith("/ok"):
            return _Response(200)
        return _Response(500)

    import slurmkit.notifications as notifications_module

    monkeypatch.setattr(notifications_module, "requests", Namespace(post=fake_post))
    monkeypatch.setattr(notifications_module.time, "sleep", lambda *_args, **_kwargs: None)

    results = service.dispatch(payload=payload, routes=routes, dry_run=False)

    assert sum(1 for r in results if r.success) == 1
    assert service.evaluate_delivery(results, strict=False) == 0
    assert service.evaluate_delivery(results, strict=True) == 1
