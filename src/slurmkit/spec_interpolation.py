"""Helpers for rendering templated spec fields."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from jinja2 import Environment, StrictUndefined, TemplateError, UndefinedError


_ENV = Environment(undefined=StrictUndefined, autoescape=False)


def has_template_syntax(value: str) -> bool:
    """Return True when a string appears to contain Jinja syntax."""
    return "{{" in value or "{%" in value or "{#" in value


def slugify_collection_name(collection_name: str) -> str:
    """Convert an arbitrary collection name into a filesystem-safe slug."""
    lowered = collection_name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "collection"


def validate_spec_variables(spec_data: Mapping[str, Any]) -> Dict[str, Any]:
    """Return validated `variables` mapping from the spec."""
    if "variables" not in spec_data:
        return {}

    raw_variables = spec_data.get("variables")
    if not isinstance(raw_variables, Mapping):
        raise ValueError("Spec field 'variables' must be a mapping.")
    return dict(raw_variables)


def _resolve_spec_path(spec_path: Path) -> Path:
    resolved = spec_path.expanduser()
    if not resolved.is_absolute():
        resolved = (Path.cwd() / resolved).resolve()
    else:
        resolved = resolved.resolve()
    return resolved


def build_job_subdir_context(
    *,
    spec_data: Mapping[str, Any],
    spec_path: Path,
    collection_name: Optional[str],
    project_root: Optional[Path],
) -> Dict[str, Any]:
    """Build the interpolation context used for resolving `job_subdir`."""
    resolved_spec_path = _resolve_spec_path(spec_path)
    spec_dir_value = resolved_spec_path.parent.as_posix()
    if project_root is not None:
        try:
            rel_dir = resolved_spec_path.parent.relative_to(project_root.resolve())
            spec_dir_value = rel_dir.as_posix() if rel_dir.parts else "."
        except ValueError:
            pass

    context: Dict[str, Any] = {
        "spec_stem": resolved_spec_path.stem,
        "spec_dir": spec_dir_value,
        "vars": validate_spec_variables(spec_data),
    }

    raw_spec_name = spec_data.get("name")
    spec_name = str(raw_spec_name).strip() if raw_spec_name is not None else ""
    if spec_name:
        context["spec_name"] = spec_name

    normalized_collection_name = str(collection_name).strip() if collection_name is not None else ""
    if normalized_collection_name:
        context["collection_name"] = normalized_collection_name
        context["collection_slug"] = slugify_collection_name(normalized_collection_name)

    return context


def render_spec_string(
    value: Any,
    *,
    field_name: str,
    context: Mapping[str, Any],
) -> str:
    """Render a spec string with strict undefined-variable handling."""
    raw_value = str(value)
    try:
        return _ENV.from_string(raw_value).render(**context)
    except UndefinedError as exc:
        available = ", ".join(sorted(context.keys())) or "(none)"
        raise ValueError(
            f"Spec field '{field_name}' references an undefined template variable: {exc}. "
            f"Available top-level keys: {available}"
        ) from exc
    except TemplateError as exc:
        raise ValueError(f"Spec field '{field_name}' contains invalid template syntax: {exc}") from exc
