"""Tests for CLI UI context and rendering primitives."""

from argparse import Namespace

import pytest

from slurmkit.cli.ui.context import UIResolutionError, resolve_ui_context
from slurmkit.cli.ui.plain import PlainBackend


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
