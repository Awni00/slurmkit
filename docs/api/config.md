# Config

Configuration management for slurmkit projects.

## Overview

The `Config` class manages configuration from multiple sources with the following priority (highest to lowest):

1. CLI arguments
2. Environment variables (`SLURMKIT_*`)
3. Config file (`.slurm-kit/config.yaml`)
4. Default values

## Classes

::: slurmkit.config.Config
    options:
      members:
        - __init__
        - get
        - get_path
        - get_output_patterns
        - get_slurm_defaults
        - as_dict
        - save

## Functions

::: slurmkit.config.get_config

::: slurmkit.config.init_config

## Usage Example

```python
from slurmkit import Config, get_config

# Get the global config instance
config = get_config()

# Access configuration values
jobs_dir = config.get("jobs_dir")
partition = config.get("slurm_defaults.partition")

# Get as Path object
jobs_path = config.get_path("jobs_dir")

# Get all SLURM defaults
slurm_defaults = config.get_slurm_defaults()
```
