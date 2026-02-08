"""
slurmkit - CLI tools for managing and generating SLURM jobs.

A toolkit for managing SLURM job workflows including:
- Auto-discovery and status tracking of SLURM jobs
- Job generation from templates with parameter grids
- Job collections for organizing related jobs
- Cross-cluster job synchronization
- Cleanup utilities for failed jobs and W&B runs
"""

from slurmkit._version import __version__
__author__ = "Awni Altabaa"

from slurmkit.config import Config, get_config
from slurmkit.collections import Collection, CollectionManager
from slurmkit.slurm import (
    get_job_status,
    get_sacct_info,
    get_pending_jobs,
    submit_job,
    find_job_output,
)
from slurmkit.generate import JobGenerator

__all__ = [
    # Version
    "__version__",
    # Config
    "Config",
    "get_config",
    # Collections
    "Collection",
    "CollectionManager",
    # SLURM utilities
    "get_job_status",
    "get_sacct_info",
    "get_pending_jobs",
    "submit_job",
    "find_job_output",
    # Generation
    "JobGenerator",
]
