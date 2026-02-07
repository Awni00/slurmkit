"""CLI UI helpers and renderers for human-facing output."""

from slurmkit.cli.ui.backend import UIBackend, create_ui_backend
from slurmkit.cli.ui.context import UIContext, UIResolutionError, resolve_ui_context
from slurmkit.cli.ui.models import (
    CollectionAnalyzeReport,
    CollectionShowReport,
    MetricItem,
    TableSection,
)
from slurmkit.cli.ui.reports import (
    build_collection_analyze_report,
    build_collection_show_report,
    render_collection_analyze_report,
    render_collection_show_report,
)

__all__ = [
    "CollectionAnalyzeReport",
    "CollectionShowReport",
    "MetricItem",
    "TableSection",
    "UIBackend",
    "UIContext",
    "UIResolutionError",
    "build_collection_analyze_report",
    "build_collection_show_report",
    "create_ui_backend",
    "render_collection_analyze_report",
    "render_collection_show_report",
    "resolve_ui_context",
]
