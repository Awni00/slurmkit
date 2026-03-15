"""Shared workflow utilities."""

from __future__ import annotations

import importlib.util
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence

from slurmkit.collections import Collection
from slurmkit.generate import JobGenerator


@dataclass(frozen=True)
class ReviewPlan:
    title: str
    lines: list[str]
    items: list[str]


def parse_key_value_pairs(raw: Optional[str]) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    if not raw:
        return parsed
    for item in raw.split(","):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        if key:
            parsed[key] = value.strip()
    return parsed


def load_python_callback(
    file_path: Optional[Path],
    function_name: str,
    *,
    callback_kind: str,
) -> Optional[Callable[[Dict[str, Any]], Any]]:
    if file_path is None:
        return None
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"{callback_kind} file not found: {path}")

    module_name = f"slurmkit_callback_{callback_kind}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module from {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    if not hasattr(module, function_name):
        raise AttributeError(
            f"{callback_kind} function '{function_name}' not found in {path}"
        )
    callback = getattr(module, function_name)
    if not callable(callback):
        raise TypeError(f"{callback_kind} '{function_name}' in {path} is not callable")
    return callback


def build_generation_metadata(
    *,
    generator: JobGenerator,
    output_dir: Path,
    spec_path: Optional[Path],
    project_root: Optional[Path],
) -> Dict[str, Any]:
    metadata = {
        "template_path": str(generator.template_path),
        "output_dir": str(output_dir),
        "job_name_pattern": generator.job_name_pattern,
        "logs_dir": str(generator.logs_dir) if generator.logs_dir else None,
        "slurm_defaults": generator.slurm_defaults,
        "slurm_logic_file": str(generator.slurm_logic_file) if generator.slurm_logic_file else None,
        "slurm_logic_function": generator.slurm_logic_function,
    }
    if spec_path is not None:
        resolved_spec = spec_path.expanduser()
        if not resolved_spec.is_absolute():
            resolved_spec = (Path.cwd() / resolved_spec).resolve()
        else:
            resolved_spec = resolved_spec.resolve()

        stored_spec = str(resolved_spec)
        if project_root is not None:
            try:
                stored_spec = str(resolved_spec.relative_to(project_root.resolve()))
            except ValueError:
                stored_spec = str(resolved_spec)
        metadata["spec_path"] = stored_spec
    return metadata


def resolve_generation_context(
    collection: Collection,
    *,
    template_override: Optional[Path] = None,
) -> Dict[str, Any]:
    generation_meta = collection.generation
    if not isinstance(generation_meta, dict) or not generation_meta:
        raise ValueError(
            "Collection is missing generation metadata required for regenerated resubmission. "
            "Run `slurmkit generate` again or migrate the collection first."
        )

    template_raw = template_override or generation_meta.get("template_path")
    output_dir_raw = generation_meta.get("output_dir")
    if not template_raw:
        raise ValueError("Generation metadata is missing 'template_path'.")
    if not output_dir_raw:
        raise ValueError("Generation metadata is missing 'output_dir'.")

    template_path = Path(str(template_raw))
    if not template_path.exists():
        raise ValueError(f"Template file not found for regeneration: {template_path}")

    slurm_defaults = generation_meta.get("slurm_defaults", {}) or {}
    if not isinstance(slurm_defaults, dict):
        raise ValueError("Generation metadata field 'slurm_defaults' must be a mapping.")

    slurm_logic_file = generation_meta.get("slurm_logic_file")
    if slurm_logic_file:
        slurm_logic_file = Path(str(slurm_logic_file))
        if not slurm_logic_file.exists():
            raise ValueError(
                f"SLURM logic file not found for regeneration: {slurm_logic_file}"
            )

    logs_dir = generation_meta.get("logs_dir")
    return {
        "template_path": template_path,
        "output_dir": Path(str(output_dir_raw)),
        "job_name_pattern": generation_meta.get("job_name_pattern"),
        "logs_dir": Path(str(logs_dir)) if logs_dir else None,
        "slurm_defaults": slurm_defaults,
        "slurm_logic_file": slurm_logic_file,
        "slurm_logic_function": generation_meta.get("slurm_logic_function", "get_slurm_args"),
    }


def resolve_output_dir_from_spec(
    spec_path: Path,
    spec_data: Dict[str, Any],
    output_dir: Optional[Path],
) -> Path:
    if output_dir is not None:
        return output_dir
    resolved = Path(str(spec_data.get("output_dir", ".")))
    if not resolved.is_absolute():
        resolved = spec_path.parent / resolved
    return resolved


def format_review(title: str, lines: Sequence[str], items: Optional[Sequence[str]] = None) -> ReviewPlan:
    return ReviewPlan(
        title=title,
        lines=[str(line) for line in lines],
        items=[str(item) for item in (items or [])],
    )
