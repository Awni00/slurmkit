"""Mini callback examples for slurmkit parameter processing."""

from __future__ import annotations


def parse_params(params: dict) -> dict:
    """Example parse hook: attach derived metadata before rendering."""
    parsed = dict(params)
    parsed["run_group"] = f"lr{parsed['learning_rate']}_bs{parsed['batch_size']}"
    return parsed


def include_params(params: dict) -> bool:
    """Example filter hook: exclude intentionally unsupported combinations."""
    return not (params["batch_size"] == 64 and params["learning_rate"] == 0.001)
