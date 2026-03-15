"""Small shared path helpers for the demo project."""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS_DIR = PROJECT_ROOT / "experiments"
SLURMKIT_DIR = PROJECT_ROOT / ".slurmkit"
COLLECTIONS_DIR = SLURMKIT_DIR / "collections"
JOBS_DIR = PROJECT_ROOT / ".jobs"
