"""Lightweight shared experiment metadata for the demo project."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExperimentInfo:
    name: str
    entry_script: str
    spec_path: str
    job_subdir: str


EXPERIMENTS: dict[str, ExperimentInfo] = {
    "hyperparameter_sweep": ExperimentInfo(
        name="hyperparameter_sweep",
        entry_script="experiments/hyperparameter_sweep/train.py",
        spec_path="experiments/hyperparameter_sweep/slurmkit/job_spec.yaml",
        job_subdir="hyperparameter_sweep",
    ),
    "model_comparison": ExperimentInfo(
        name="model_comparison",
        entry_script="experiments/model_comparison/evaluate.py",
        spec_path="experiments/model_comparison/slurmkit/job_spec.yaml",
        job_subdir="comparisons/model_comparison",
    ),
}
