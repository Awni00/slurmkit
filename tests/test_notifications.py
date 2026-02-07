"""Tests for slurmkit.notifications module."""

from argparse import Namespace
from pathlib import Path
import smtplib

import yaml

from slurmkit.collections import CollectionManager
from slurmkit.config import Config
from slurmkit.notifications import (
    EVENT_COLLECTION_COMPLETED,
    EVENT_JOB_COMPLETED,
    EVENT_JOB_FAILED,
    EVENT_TEST,
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


def test_route_filtering_ignores_unselected_route_parse_errors(tmp_path, monkeypatch):
    """Filtering to specific routes should not parse unrelated routes."""
    monkeypatch.delenv("MISSING_NOTIFY_URL", raising=False)
    config = _make_config(
        tmp_path,
        {
            "notifications": {
                "routes": [
                    {"name": "broken", "type": "webhook", "url": "${MISSING_NOTIFY_URL}"},
                    {"name": "ok", "type": "webhook", "url": "https://example.test/ok"},
                ]
            }
        },
    )
    service = NotificationService(config=config)
    resolution = service.resolve_routes(
        event=EVENT_JOB_FAILED,
        route_names=["ok"],
    )

    assert [route.name for route in resolution.routes] == ["ok"]
    assert resolution.errors == []


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


def test_email_route_parses_recipients_and_defaults(tmp_path):
    """Email route should parse recipients and apply SMTP defaults."""
    config = _make_config(
        tmp_path,
        {
            "notifications": {
                "routes": [
                    {
                        "name": "mail",
                        "type": "email",
                        "to": "ops@example.com, ml@example.com, ops@example.com",
                        "from": "noreply@example.com",
                        "smtp_host": "smtp.example.com",
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
    assert route.route_type == "email"
    assert route.email_to == ["ops@example.com", "ml@example.com"]
    assert route.email_from == "noreply@example.com"
    assert route.smtp_host == "smtp.example.com"
    assert route.smtp_port == 587
    assert route.smtp_starttls is True
    assert route.smtp_ssl is False


def test_email_route_accepts_list_recipients(tmp_path):
    """Email route should accept recipient list format."""
    config = _make_config(
        tmp_path,
        {
            "notifications": {
                "routes": [
                    {
                        "name": "mail",
                        "type": "email",
                        "to": ["ops@example.com", "ml@example.com"],
                        "from": "noreply@example.com",
                        "smtp_host": "smtp.example.com",
                    }
                ]
            }
        },
    )
    service = NotificationService(config=config)
    resolution = service.resolve_routes(event=EVENT_JOB_FAILED)
    assert resolution.errors == []
    assert resolution.routes[0].email_to == ["ops@example.com", "ml@example.com"]


def test_email_route_missing_required_fields(tmp_path):
    """Email route requires to/from/smtp_host fields."""
    config = _make_config(
        tmp_path,
        {
            "notifications": {
                "routes": [
                    {"name": "m1", "type": "email", "from": "x@example.com", "smtp_host": "smtp.example.com"},
                    {"name": "m2", "type": "email", "to": ["x@example.com"], "smtp_host": "smtp.example.com"},
                    {"name": "m3", "type": "email", "to": ["x@example.com"], "from": "x@example.com"},
                ]
            }
        },
    )
    service = NotificationService(config=config)
    resolution = service.resolve_routes(event=EVENT_JOB_FAILED)
    assert len(resolution.routes) == 0
    assert len(resolution.errors) == 3
    joined = "\n".join(resolution.errors)
    assert "required field 'to'" in joined
    assert "required field 'from'" in joined
    assert "required field 'smtp_host'" in joined


def test_email_route_invalid_tls_ssl_combination(tmp_path):
    """STARTTLS and SMTP SSL cannot both be enabled."""
    config = _make_config(
        tmp_path,
        {
            "notifications": {
                "routes": [
                    {
                        "name": "mail",
                        "type": "email",
                        "to": "ops@example.com",
                        "from": "noreply@example.com",
                        "smtp_host": "smtp.example.com",
                        "smtp_starttls": True,
                        "smtp_ssl": True,
                    }
                ]
            }
        },
    )
    service = NotificationService(config=config)
    resolution = service.resolve_routes(event=EVENT_JOB_FAILED)
    assert len(resolution.routes) == 0
    assert len(resolution.errors) == 1
    assert "cannot enable both smtp_starttls and smtp_ssl" in resolution.errors[0]


def test_email_route_invalid_auth_pair(tmp_path):
    """Username/password auth must be configured together."""
    config = _make_config(
        tmp_path,
        {
            "notifications": {
                "routes": [
                    {
                        "name": "mail",
                        "type": "email",
                        "to": "ops@example.com",
                        "from": "noreply@example.com",
                        "smtp_host": "smtp.example.com",
                        "smtp_username": "user-only",
                    }
                ]
            }
        },
    )
    service = NotificationService(config=config)
    resolution = service.resolve_routes(event=EVENT_JOB_FAILED)
    assert len(resolution.routes) == 0
    assert len(resolution.errors) == 1
    assert "smtp_username and smtp_password together" in resolution.errors[0]


def test_email_route_rejects_url_and_headers(tmp_path):
    """Email routes should not define webhook fields."""
    config = _make_config(
        tmp_path,
        {
            "notifications": {
                "routes": [
                    {
                        "name": "mail",
                        "type": "email",
                        "to": "ops@example.com",
                        "from": "noreply@example.com",
                        "smtp_host": "smtp.example.com",
                        "url": "https://example.com/hook",
                    },
                    {
                        "name": "mail2",
                        "type": "email",
                        "to": "ops@example.com",
                        "from": "noreply@example.com",
                        "smtp_host": "smtp.example.com",
                        "headers": {"X-Test": "1"},
                    },
                ]
            }
        },
    )
    service = NotificationService(config=config)
    resolution = service.resolve_routes(event=EVENT_JOB_FAILED)
    assert len(resolution.routes) == 0
    assert len(resolution.errors) == 2
    assert "must not define field 'url'" in resolution.errors[0]
    assert "must not define field 'headers'" in resolution.errors[1]


def test_email_route_env_interpolation_success(tmp_path, monkeypatch):
    """Email fields support environment variable interpolation."""
    monkeypatch.setenv("MAIL_TO", "ops@example.com,ml@example.com")
    monkeypatch.setenv("MAIL_FROM", "noreply@example.com")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "1025")
    monkeypatch.setenv("SMTP_STARTTLS", "false")
    monkeypatch.setenv("SMTP_SSL", "true")
    monkeypatch.setenv("SMTP_USER", "demo-user")
    monkeypatch.setenv("SMTP_PASS", "demo-pass")
    config = _make_config(
        tmp_path,
        {
            "notifications": {
                "routes": [
                    {
                        "name": "mail",
                        "type": "email",
                        "to": "${MAIL_TO}",
                        "from": "${MAIL_FROM}",
                        "smtp_host": "${SMTP_HOST}",
                        "smtp_port": "${SMTP_PORT}",
                        "smtp_starttls": "${SMTP_STARTTLS}",
                        "smtp_ssl": "${SMTP_SSL}",
                        "smtp_username": "${SMTP_USER}",
                        "smtp_password": "${SMTP_PASS}",
                    }
                ]
            }
        },
    )
    service = NotificationService(config=config)
    resolution = service.resolve_routes(event=EVENT_JOB_FAILED)
    assert resolution.errors == []
    route = resolution.routes[0]
    assert route.email_to == ["ops@example.com", "ml@example.com"]
    assert route.email_from == "noreply@example.com"
    assert route.smtp_host == "smtp.example.com"
    assert route.smtp_port == 1025
    assert route.smtp_starttls is False
    assert route.smtp_ssl is True
    assert route.smtp_username == "demo-user"
    assert route.smtp_password == "demo-pass"


def test_email_route_env_interpolation_missing_var(tmp_path, monkeypatch):
    """Missing env interpolation in email fields should produce route error."""
    monkeypatch.delenv("MISSING_SMTP_HOST", raising=False)
    config = _make_config(
        tmp_path,
        {
            "notifications": {
                "routes": [
                    {
                        "name": "mail",
                        "type": "email",
                        "to": "ops@example.com",
                        "from": "noreply@example.com",
                        "smtp_host": "${MISSING_SMTP_HOST}",
                    }
                ]
            }
        },
    )
    service = NotificationService(config=config)
    resolution = service.resolve_routes(event=EVENT_JOB_FAILED)
    assert len(resolution.routes) == 0
    assert len(resolution.errors) == 1
    assert "Missing environment variable" in resolution.errors[0]


def test_email_dispatch_dry_run_skips_smtp(tmp_path, monkeypatch):
    """Dry-run email dispatch should not call SMTP."""
    config = _make_config(
        tmp_path,
        {
            "notifications": {
                "routes": [
                    {
                        "name": "mail",
                        "type": "email",
                        "to": "ops@example.com",
                        "from": "noreply@example.com",
                        "smtp_host": "smtp.example.com",
                    }
                ]
            }
        },
    )
    service = NotificationService(config=config)
    routes = service.resolve_routes(event=None).routes
    payload = service.build_test_payload()

    class _FailSMTP:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("SMTP should not be called in dry-run mode")

    import slurmkit.notifications as notifications_module

    monkeypatch.setattr(notifications_module.smtplib, "SMTP", _FailSMTP)

    results = service.dispatch(payload=payload, routes=routes, dry_run=True)
    assert len(results) == 1
    assert results[0].success is True
    assert results[0].dry_run is True
    assert results[0].attempts == 0


def test_email_dispatch_smtp_success(tmp_path, monkeypatch):
    """Email dispatch should send through SMTP and mark success."""
    config = _make_config(
        tmp_path,
        {
            "notifications": {
                "routes": [
                    {
                        "name": "mail",
                        "type": "email",
                        "to": "ops@example.com",
                        "from": "noreply@example.com",
                        "smtp_host": "smtp.example.com",
                        "smtp_username": "user",
                        "smtp_password": "pass",
                        "smtp_starttls": True,
                    }
                ]
            }
        },
    )
    service = NotificationService(config=config)
    routes = service.resolve_routes(event=None).routes
    payload = service.build_test_payload()
    calls = {"starttls": 0, "login": 0, "send": 0}

    class _SMTP:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def ehlo(self):
            return None

        def starttls(self):
            calls["starttls"] += 1

        def login(self, *_args):
            calls["login"] += 1

        def send_message(self, *_args):
            calls["send"] += 1

    import slurmkit.notifications as notifications_module

    monkeypatch.setattr(notifications_module.smtplib, "SMTP", _SMTP)
    monkeypatch.setattr(notifications_module.time, "sleep", lambda *_args, **_kwargs: None)

    results = service.dispatch(payload=payload, routes=routes, dry_run=False)
    assert len(results) == 1
    assert results[0].success is True
    assert results[0].attempts == 1
    assert calls["starttls"] == 1
    assert calls["login"] == 1
    assert calls["send"] == 1


def test_email_dispatch_retries_then_succeeds(tmp_path, monkeypatch):
    """Transient email send failures should retry and eventually succeed."""
    config = _make_config(
        tmp_path,
        {
            "notifications": {
                "defaults": {"max_attempts": 3, "backoff_seconds": 0.01},
                "routes": [
                    {
                        "name": "mail",
                        "type": "email",
                        "to": "ops@example.com",
                        "from": "noreply@example.com",
                        "smtp_host": "smtp.example.com",
                    }
                ],
            }
        },
    )
    service = NotificationService(config=config)
    routes = service.resolve_routes(event=None).routes
    payload = service.build_test_payload()
    calls = {"send": 0}

    class _SMTP:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def ehlo(self):
            return None

        def starttls(self):
            return None

        def send_message(self, *_args):
            calls["send"] += 1
            if calls["send"] == 1:
                raise OSError("temporary network issue")

    import slurmkit.notifications as notifications_module

    monkeypatch.setattr(notifications_module.smtplib, "SMTP", _SMTP)
    monkeypatch.setattr(notifications_module.time, "sleep", lambda *_args, **_kwargs: None)

    results = service.dispatch(payload=payload, routes=routes, dry_run=False)
    assert len(results) == 1
    assert results[0].success is True
    assert results[0].attempts == 2


def test_email_dispatch_permanent_failure(tmp_path, monkeypatch):
    """Permanent SMTP failures should return failed DeliveryResult after retries."""
    config = _make_config(
        tmp_path,
        {
            "notifications": {
                "defaults": {"max_attempts": 2, "backoff_seconds": 0.01},
                "routes": [
                    {
                        "name": "mail",
                        "type": "email",
                        "to": "ops@example.com",
                        "from": "noreply@example.com",
                        "smtp_host": "smtp.example.com",
                    }
                ],
            }
        },
    )
    service = NotificationService(config=config)
    routes = service.resolve_routes(event=None).routes
    payload = service.build_test_payload()

    class _SMTP:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def ehlo(self):
            return None

        def starttls(self):
            return None

        def send_message(self, *_args):
            raise smtplib.SMTPException("permanent failure")

    import slurmkit.notifications as notifications_module

    monkeypatch.setattr(notifications_module.smtplib, "SMTP", _SMTP)
    monkeypatch.setattr(notifications_module.time, "sleep", lambda *_args, **_kwargs: None)

    results = service.dispatch(payload=payload, routes=routes, dry_run=False)
    assert len(results) == 1
    assert results[0].success is False
    assert results[0].attempts == 2
    assert "permanent failure" in (results[0].error or "")
