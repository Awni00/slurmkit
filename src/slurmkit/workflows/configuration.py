"""Configuration workflows."""

from __future__ import annotations

import os
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from slurmkit.config import DEFAULT_CONFIG


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def load_config_data(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def normalize_config_data(raw: Dict[str, Any]) -> Dict[str, Any]:
    return deep_merge(DEFAULT_CONFIG, raw)


def write_config_data(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        yaml.dump(data, handle, default_flow_style=False, sort_keys=False)


def open_config_in_editor(path: Path) -> None:
    editor = os.environ.get("EDITOR")
    if not editor:
        raise RuntimeError("EDITOR is not set.")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        write_config_data(path, normalize_config_data({}))
    subprocess.run([editor, str(path)], check=False)


def build_config_summary(data: Dict[str, Any]) -> list[str]:
    return [
        f"Jobs dir: {data['jobs_dir']}",
        f"Default partition: {data['slurm_defaults']['partition']}",
        f"Default time: {data['slurm_defaults']['time']}",
        f"Default memory: {data['slurm_defaults']['mem']}",
        f"UI mode: {data['ui']['mode']}",
        f"Interactive UI: {'enabled' if data['ui'].get('interactive', True) else 'disabled'}",
        f"Notifications routes: {len(data.get('notifications', {}).get('routes', []))}",
    ]
