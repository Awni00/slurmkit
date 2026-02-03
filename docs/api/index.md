# API Reference

This section provides detailed API documentation for the slurmkit Python library.

## Overview

slurmkit exposes the following main components:

| Module | Description |
|--------|-------------|
| [Config](config.md) | Configuration management |
| [Collections](collections.md) | Job collection tracking |
| [Job Generation](generate.md) | Template-based job generation |
| [SLURM Utilities](slurm.md) | SLURM interaction functions |
| [Sync](sync.md) | Cross-cluster synchronization |

## Quick Import

```python
from slurmkit import (
    # Configuration
    Config,
    get_config,
    # Collections
    Collection,
    CollectionManager,
    # SLURM utilities
    get_job_status,
    get_sacct_info,
    get_pending_jobs,
    submit_job,
    find_job_output,
    # Job generation
    JobGenerator,
)
```

## Module Organization

```
slurmkit/
├── config.py       # Config class and utilities
├── collections.py  # Collection and CollectionManager
├── generate.py     # JobGenerator and parameter expansion
├── slurm.py        # SLURM command wrappers
├── sync.py         # SyncManager for cross-cluster sync
├── wandb_utils.py  # W&B integration utilities
└── cli/            # Command-line interface
```
