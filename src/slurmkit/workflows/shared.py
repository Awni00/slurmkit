"""Shared workflow utilities."""

from __future__ import annotations

import importlib.util
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence

from slurmkit.collections import Collection
from slurmkit.config import Config
from slurmkit.generate import JobGenerator, resolve_spec_job_paths
from slurmkit.spec_interpolation import build_job_subdir_context


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
    scripts_dir: Path,
    logs_dir: Path,
    job_subdir: str,
    spec_path: Optional[Path],
    project_root: Optional[Path],
) -> Dict[str, Any]:
    metadata = {
        "template_path": str(generator.template_path),
        "job_subdir": job_subdir,
        "scripts_dir": str(scripts_dir),
        "logs_dir": str(logs_dir),
        "job_name_pattern": generator.job_name_pattern,
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
    scripts_dir_raw = generation_meta.get("scripts_dir")
    logs_dir_raw = generation_meta.get("logs_dir")
    if not template_raw:
        raise ValueError("Generation metadata is missing 'template_path'.")
    if not scripts_dir_raw:
        raise ValueError("Generation metadata is missing 'scripts_dir'.")
    if not logs_dir_raw:
        raise ValueError("Generation metadata is missing 'logs_dir'.")

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

    return {
        "template_path": template_path,
        "job_subdir": str(generation_meta.get("job_subdir", "")),
        "scripts_dir": Path(str(scripts_dir_raw)),
        "job_name_pattern": generation_meta.get("job_name_pattern"),
        "logs_dir": Path(str(logs_dir_raw)),
        "slurm_defaults": slurm_defaults,
        "slurm_logic_file": slurm_logic_file,
        "slurm_logic_function": generation_meta.get("slurm_logic_function", "get_slurm_args"),
    }


def resolve_job_paths_from_spec(
    *,
    config: Config,
    spec_data: Dict[str, Any],
    spec_path: Path,
    collection_name: Optional[str] = None,
) -> Dict[str, Path | str]:
    context = build_job_subdir_context(
        spec_data=spec_data,
        spec_path=spec_path,
        collection_name=collection_name,
        project_root=getattr(config, "project_root", None),
    )
    resolved = resolve_spec_job_paths(spec_data, config, interpolation_context=context)
    scripts_dir = Path(str(resolved["scripts_dir"]))
    logs_dir = Path(str(resolved["logs_dir"]))
    return {
        "job_subdir": str(resolved["job_subdir"]),
        "scripts_dir": scripts_dir,
        "logs_dir": logs_dir,
    }


def format_review(title: str, lines: Sequence[str], items: Optional[Sequence[str]] = None) -> ReviewPlan:
    return ReviewPlan(
        title=title,
        lines=[str(line) for line in lines],
        items=[str(item) for item in (items or [])],
    )
