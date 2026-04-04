"""Rich backend for enhanced CLI rendering."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Tuple

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from slurmkit.cli.ui.models import MetricItem


class RichBackend:
    """Rich renderer for interactive terminals."""

    _STATUS_STYLES = {
        "completed": "bold green",
        "failed": "bold red",
        "running": "bold yellow",
        "pending": "bold cyan",
        "unknown": "bold magenta",
        "not submitted": "dim",
    }
    _HEADER_PATH_LABELS = {"spec", "collection file", "scripts dir", "logs dir"}

    def __init__(self, console: Console | None = None):
        self.console = console or Console()

    def heading(self, text: str) -> None:
        self.console.print(Panel.fit(text, border_style="cyan"))

    def kv_block(self, rows: Sequence[Tuple[str, str]]) -> None:
        if not rows:
            return
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold cyan", no_wrap=True)
        table.add_column(style="white")
        for label, value in rows:
            table.add_row(label, self._render_kv_value(label, value))
        self.console.print(table)

    def section(self, title: str) -> None:
        self.console.print()
        self.console.print(f"[bold]{title}[/bold]")

    def text(self, text: str = "") -> None:
        self.console.print(text)

    def divider(self) -> None:
        self.console.rule(style="grey42")

    def metrics(self, title: str, metrics: Sequence[MetricItem]) -> None:
        self.section(title)
        table = Table(show_header=False, box=None, pad_edge=False)
        table.add_column("Metric", style="white")
        table.add_column("Value", style="bold")
        for item in metrics:
            label = item.label
            if item.state:
                label = self.style_status(label)
            value = item.value
            if item.percent is not None:
                value = f"{value} ({item.percent:.1f}%)"
            table.add_row(label, value)
            if item.details:
                table.add_row(f"[dim]  {item.details}[/dim]", "")
        self.console.print(table)

    def table(
        self,
        title: str,
        headers: Sequence[str],
        rows: Sequence[Sequence[str]],
        status_columns: Sequence[int] = (),
        empty_message: str = "  (no rows)",
    ) -> None:
        self.section(title)
        if not rows:
            self.console.print(empty_message)
            return

        table = Table(show_lines=False, header_style="bold cyan")
        for header in headers:
            table.add_column(header, overflow="fold")

        output_path_indexes = {
            idx for idx, header in enumerate(headers) if str(header).strip().lower() == "output path"
        }

        for row in rows:
            rendered = []
            for idx, value in enumerate(row):
                text: str | Text = value
                if idx in output_path_indexes:
                    text = self._render_output_link(value)
                if idx in status_columns:
                    text = self.style_status(value)
                rendered.append(text)
            table.add_row(*rendered)
        self.console.print(table)

    def notes(self, lines: Sequence[str], title: str = "Notes:") -> None:
        if not lines:
            return
        self.section(title)
        for line in lines:
            self.console.print(f"  [dim]-[/dim] {line}")

    def style_status(self, value: str) -> str:
        style = self._STATUS_STYLES.get(value.strip().lower())
        if not style:
            return value
        return f"[{style}]{value}[/{style}]"

    def _render_output_link(self, value: str) -> str | Text:
        target = str(value or "").strip()
        if not target:
            return ""
        path = Path(target).expanduser()
        try:
            if not path.is_absolute():
                path = (Path.cwd() / path).resolve()
            uri = path.as_uri()
        except ValueError:
            return target
        return Text("OUTPUT", style=f"link {uri}")

    def _render_kv_value(self, label: str, value: str) -> str | Text:
        if str(label).strip().lower() not in self._HEADER_PATH_LABELS:
            return value
        target = str(value or "").strip()
        if not target:
            return ""
        path = Path(target).expanduser()
        try:
            if not path.is_absolute():
                path = (Path.cwd() / path).resolve()
            uri = path.as_uri()
        except ValueError:
            return target
        return Text(target, style=f"link {uri}")
