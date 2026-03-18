"""Mini callback example for slurmkit dynamic SLURM args."""

from __future__ import annotations


def get_slurm_args(params: dict, defaults: dict) -> dict:
    """Increase memory for larger batch sizes."""
    args = dict(defaults)
    if params.get("batch_size", 0) >= 64:
        args["mem"] = "32G"
    return args
