"""Plain-text backend with optional ANSI status coloring."""

from __future__ import annotations

from typing import Sequence, Tuple

from tabulate import tabulate

from slurmkit.cli.ui.models import MetricItem


class PlainBackend:
    """Plain text renderer with improved formatting."""

    _STATUS_STYLES = {
        "completed": "\033[32m",
        "failed": "\033[31m",
        "running": "\033[33m",
        "pending": "\033[36m",
        "unknown": "\033[35m",
        "not submitted": "\033[90m",
    }
    _RESET = "\033[0m"

    def __init__(self, enable_color: bool = False, width: int = 80):
        self.enable_color = enable_color
        self.width = width

    def heading(self, text: str) -> None:
        print(text)
        self.divider()

    def kv_block(self, rows: Sequence[Tuple[str, str]]) -> None:
        if not rows:
            return
        label_width = max(len(label) for label, _ in rows)
        for label, value in rows:
            print(f"{label:<{label_width}}  {value}")

    def section(self, title: str) -> None:
        print()
        print(title)

    def text(self, text: str = "") -> None:
        print(text)

    def divider(self) -> None:
        print("-" * self.width)

    def metrics(self, title: str, metrics: Sequence[MetricItem]) -> None:
        self.section(title)
        for item in metrics:
            label = item.label
            if item.state:
                label = self.style_status(label)
            if item.percent is None:
                print(f"  {label}: {item.value}")
            else:
                print(f"  {label}: {item.value} ({item.percent:.1f}%)")

    def table(
        self,
        title: str,
        headers: Sequence[str],
        rows: Sequence[Sequence[str]],
        status_columns: Sequence[int] = (),
        empty_message: str = "  (no rows)",
    ) -> None:
        self.section(title)
        self.divider()
        if not rows:
            print(empty_message)
            return

        rendered_rows = []
        for row in rows:
            rendered = list(row)
            for idx in status_columns:
                if 0 <= idx < len(rendered):
                    rendered[idx] = self.style_status(rendered[idx])
            rendered_rows.append(rendered)
        print(tabulate(rendered_rows, headers=headers, tablefmt="simple"))

    def notes(self, lines: Sequence[str], title: str = "Notes:") -> None:
        if not lines:
            return
        self.section(title)
        for line in lines:
            print(f"  - {line}")

    def style_status(self, value: str) -> str:
        if not self.enable_color:
            return value
        style = self._STATUS_STYLES.get(value.strip().lower())
        if not style:
            return value
        return f"{style}{value}{self._RESET}"
