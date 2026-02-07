"""UI mode resolution for CLI rendering."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any, Optional

from slurmkit.config import Config


UI_MODE_PLAIN = "plain"
UI_MODE_RICH = "rich"
UI_MODE_AUTO = "auto"
VALID_UI_MODES = {UI_MODE_PLAIN, UI_MODE_RICH, UI_MODE_AUTO}


class UIResolutionError(RuntimeError):
    """Raised when CLI UI mode cannot be resolved."""


@dataclass(frozen=True)
class UIContext:
    """Resolved UI execution context."""

    requested_mode: str
    configured_mode: str
    effective_mode: str
    is_tty: bool
    rich_available: bool
    plain_color_enabled: bool


def _normalize_mode(value: Optional[str], default: str) -> str:
    if not value:
        return default
    mode = value.strip().lower()
    if mode in VALID_UI_MODES:
        return mode
    return default


def _is_rich_available() -> bool:
    try:
        import rich  # noqa: F401

        return True
    except ImportError:
        return False


def _stdout_isatty() -> bool:
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


def resolve_ui_context(args: Any, config: Config) -> UIContext:
    """Resolve CLI UI context from CLI args + config + runtime capabilities."""
    requested_mode = _normalize_mode(getattr(args, "ui", None), "")
    config_get = getattr(config, "get", None)
    configured_raw = config_get("ui.mode", UI_MODE_PLAIN) if callable(config_get) else UI_MODE_PLAIN
    configured_mode = _normalize_mode(configured_raw, UI_MODE_PLAIN)
    selected_mode = requested_mode or configured_mode or UI_MODE_PLAIN

    is_tty = _stdout_isatty()
    rich_available = _is_rich_available()
    no_color = "NO_COLOR" in os.environ
    term = os.environ.get("TERM", "").lower()
    plain_color_enabled = is_tty and not no_color and term != "dumb"

    if selected_mode == UI_MODE_RICH and not rich_available:
        raise UIResolutionError(
            "Rich UI requested but the optional dependency is not installed. "
            "Install with: pip install slurmkit[ui]"
        )

    effective_mode = UI_MODE_PLAIN
    if selected_mode == UI_MODE_RICH:
        effective_mode = UI_MODE_RICH
    elif selected_mode == UI_MODE_AUTO:
        effective_mode = UI_MODE_RICH if (rich_available and is_tty) else UI_MODE_PLAIN

    return UIContext(
        requested_mode=selected_mode,
        configured_mode=configured_mode,
        effective_mode=effective_mode,
        is_tty=is_tty,
        rich_available=rich_available,
        plain_color_enabled=plain_color_enabled,
    )
