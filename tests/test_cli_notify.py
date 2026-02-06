"""Tests for notify CLI parser and command handlers."""

from argparse import Namespace

from slurmkit.cli import commands
from slurmkit.cli.main import create_parser
from slurmkit.notifications import DeliveryResult, RouteResolution


class _FakeService:
    def __init__(self):
        self.called_build = 0
        self.called_resolve = 0
        self.called_dispatch = 0
        self.route_resolution = RouteResolution(routes=[], errors=[], skipped=[])
        self.delivery_results = []

    def build_job_payload(self, **_kwargs):
        self.called_build += 1
        return {"event": "job_failed", "job": {"job_id": "1"}}, []

    def build_test_payload(self):
        return {"event": "test_notification"}

    def resolve_routes(self, **_kwargs):
        self.called_resolve += 1
        return self.route_resolution

    def dispatch(self, **_kwargs):
        self.called_dispatch += 1
        return list(self.delivery_results)


def test_notify_parser_job_args():
    """Parser accepts notify job options."""
    parser = create_parser()
    args = parser.parse_args(
        [
            "notify",
            "job",
            "--job-id",
            "123",
            "--collection",
            "exp",
            "--exit-code",
            "2",
            "--on",
            "always",
            "--route",
            "r1",
            "--route",
            "r2",
            "--tail-lines",
            "50",
            "--strict",
            "--dry-run",
        ]
    )
    assert args.command == "notify"
    assert args.notify_action == "job"
    assert args.job_id == "123"
    assert args.collection == "exp"
    assert args.exit_code == 2
    assert args.on == "always"
    assert args.route == ["r1", "r2"]
    assert args.tail_lines == 50
    assert args.strict is True
    assert args.dry_run is True


def test_notify_parser_test_args():
    """Parser accepts notify test options."""
    parser = create_parser()
    args = parser.parse_args(["notify", "test", "--route", "r1", "--strict", "--dry-run"])
    assert args.command == "notify"
    assert args.notify_action == "test"
    assert args.route == ["r1"]
    assert args.strict is True
    assert args.dry_run is True


def test_cmd_notify_job_skip_on_success_when_failed_only(monkeypatch, capsys):
    """Completed jobs should be skipped by default --on failed gate."""
    fake_service = _FakeService()
    monkeypatch.setattr(commands, "get_configured_config", lambda _args: object())
    monkeypatch.setattr(commands, "NotificationService", lambda config=None: fake_service)

    args = Namespace(
        job_id="123",
        collection=None,
        exit_code=0,
        on="failed",
        route=None,
        tail_lines=None,
        strict=False,
        dry_run=False,
    )
    exit_code = commands.cmd_notify_job(args)
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "Skipping notification" in out
    assert fake_service.called_build == 0
    assert fake_service.called_resolve == 0


def test_cmd_notify_job_no_matching_routes_is_success(monkeypatch, capsys):
    """No matching routes should produce a skip message and exit 0."""
    fake_service = _FakeService()
    fake_service.route_resolution = RouteResolution(routes=[], errors=[], skipped=["route_a"])

    monkeypatch.setattr(commands, "get_configured_config", lambda _args: object())
    monkeypatch.setattr(commands, "NotificationService", lambda config=None: fake_service)

    args = Namespace(
        job_id="123",
        collection=None,
        exit_code=1,
        on="failed",
        route=None,
        tail_lines=None,
        strict=False,
        dry_run=False,
    )
    exit_code = commands.cmd_notify_job(args)
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "No notification routes matched" in out


def test_cmd_notify_job_partial_success_strict_behavior(monkeypatch):
    """Strict mode should fail when any attempted route fails."""
    fake_service = _FakeService()
    fake_service.route_resolution = RouteResolution(
        routes=[Namespace(name="a", route_type="webhook"), Namespace(name="b", route_type="webhook")],
        errors=[],
        skipped=[],
    )
    fake_service.delivery_results = [
        DeliveryResult(route_name="a", route_type="webhook", success=True, attempts=1),
        DeliveryResult(route_name="b", route_type="webhook", success=False, attempts=1, error="boom"),
    ]

    monkeypatch.setattr(commands, "get_configured_config", lambda _args: object())
    monkeypatch.setattr(commands, "NotificationService", lambda config=None: fake_service)

    common = {
        "job_id": "123",
        "collection": None,
        "exit_code": 1,
        "on": "failed",
        "route": None,
        "tail_lines": None,
        "dry_run": False,
    }

    exit_non_strict = commands.cmd_notify_job(Namespace(strict=False, **common))
    exit_strict = commands.cmd_notify_job(Namespace(strict=True, **common))

    assert exit_non_strict == 0
    assert exit_strict == 1


def test_cmd_notify_job_route_errors_fail_if_no_success(monkeypatch):
    """Route resolution errors should count as failed attempts."""
    fake_service = _FakeService()
    fake_service.route_resolution = RouteResolution(routes=[], errors=["Unknown notification route 'x'."], skipped=[])
    fake_service.delivery_results = []

    monkeypatch.setattr(commands, "get_configured_config", lambda _args: object())
    monkeypatch.setattr(commands, "NotificationService", lambda config=None: fake_service)

    args = Namespace(
        job_id="123",
        collection=None,
        exit_code=1,
        on="failed",
        route=["x"],
        tail_lines=None,
        strict=False,
        dry_run=False,
    )
    exit_code = commands.cmd_notify_job(args)
    assert exit_code == 1


def test_cmd_notify_test_dry_run_success(monkeypatch):
    """notify test should support dry run and return success with valid routes."""
    fake_service = _FakeService()
    fake_service.route_resolution = RouteResolution(
        routes=[Namespace(name="a", route_type="webhook")],
        errors=[],
        skipped=[],
    )
    fake_service.delivery_results = [
        DeliveryResult(route_name="a", route_type="webhook", success=True, attempts=0, dry_run=True)
    ]

    monkeypatch.setattr(commands, "get_configured_config", lambda _args: object())
    monkeypatch.setattr(commands, "NotificationService", lambda config=None: fake_service)

    args = Namespace(route=None, strict=False, dry_run=True)
    assert commands.cmd_notify_test(args) == 0
