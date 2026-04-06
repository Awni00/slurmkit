"""Helpers for asserting CLI output in tests."""

from __future__ import annotations

import re


_ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def plain_cli_output(result: object) -> str:
    """Return stderr/stdout with ANSI formatting removed."""
    output = (getattr(result, "stderr", "") or getattr(result, "stdout", "")) or ""
    return _ANSI_ESCAPE_RE.sub("", output)
