"""Backend abstraction for CLI UI rendering."""

from __future__ import annotations

from typing import Protocol, Sequence, Tuple

from slurmkit.cli.ui.context import UI_MODE_PLAIN, UI_MODE_RICH, UIContext
from slurmkit.cli.ui.models import MetricItem


class UIBackend(Protocol):
    """Rendering API shared by plain and rich backends."""

    def heading(self, text: str) -> None:
        """Render a top-level heading."""

    def kv_block(self, rows: Sequence[Tuple[str, str]]) -> None:
        """Render a key-value block."""

    def section(self, title: str) -> None:
        """Render a section header."""

    def text(self, text: str = "") -> None:
        """Render a line of text."""

    def divider(self) -> None:
        """Render a section divider."""

    def metrics(self, title: str, metrics: Sequence[MetricItem]) -> None:
        """Render summary metrics."""

    def table(
        self,
        title: str,
        headers: Sequence[str],
        rows: Sequence[Sequence[str]],
        status_columns: Sequence[int] = (),
        empty_message: str = "  (no rows)",
    ) -> None:
        """Render a titled table."""

    def notes(self, lines: Sequence[str], title: str = "Notes:") -> None:
        """Render notes list."""

    def style_status(self, value: str) -> str:
        """Apply status style to a state label."""


def create_ui_backend(ctx: UIContext) -> UIBackend:
    """Create UI backend for the resolved mode."""
    if ctx.effective_mode == UI_MODE_RICH:
        from slurmkit.cli.ui.rich_backend import RichBackend

        return RichBackend()
    if ctx.effective_mode == UI_MODE_PLAIN:
        from slurmkit.cli.ui.plain import PlainBackend

        return PlainBackend(enable_color=ctx.plain_color_enabled)
    raise ValueError(f"Unsupported UI mode: {ctx.effective_mode}")
