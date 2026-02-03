# Getting Started with slurmkit

This guide will help you get started with slurmkit for managing SLURM jobs.

## Installation

### From Source (Development)

```bash
# Clone the repository
git clone https://github.com/Awni00/slurm-job-utils.git
cd slurm-job-utils

# Install in development mode
pip install -e .
```

### From PyPI (When Published)

```bash
pip install slurmkit
```

## Initial Setup

### Initialize Project Configuration

Navigate to your project directory and run:

```bash
slurmkit init
```

This interactive wizard will create `.slurm-kit/config.yaml` with your settings:

- Jobs directory path
- Default SLURM arguments (partition, time, memory)
- W&B entity (optional)

### Configuration File

The configuration file `.slurm-kit/config.yaml` controls slurmkit behavior:

```yaml
# Directory structure
jobs_dir: jobs/
collections_dir: .job-collections/
sync_dir: .slurm-kit/sync/

# Output file patterns (tried in order)
output_patterns:
  - "{job_name}.{job_id}.out"
  - "{job_name}.{job_id}.*.out"
  - "slurm-{job_id}.out"

# Default SLURM arguments
slurm_defaults:
  partition: gpu
  time: "24:00:00"
  mem: "32G"

# Job directory structure
job_structure:
  scripts_subdir: job_scripts/
  logs_subdir: logs/

# W&B settings (optional)
wandb:
  entity: your_username
  default_projects:
    - project-a
    - project-b
```

## Basic Workflow

### 1. Check Job Status

View the status of all jobs:

```bash
slurmkit status
```

Or view jobs in a specific experiment:

```bash
slurmkit status my_experiment
```

Options:
- `--state running` - Filter by state (running, pending, completed, failed)
- `--format json` - Output as JSON

### 2. Find Job Output

Locate output file for a specific job:

```bash
slurmkit find 12345678
```

Options:
- `--preview` - Show file preview
- `--open` - Open in editor

### 3. Generate Jobs

Create a job spec file `job_spec.yaml`:

```yaml
name: my_experiment
description: "Hyperparameter sweep"

template: templates/train.job.j2
output_dir: jobs/my_exp/job_scripts
logs_dir: jobs/my_exp/logs

parameters:
  mode: grid
  values:
    learning_rate: [0.001, 0.01, 0.1]
    batch_size: [32, 64]

slurm_args:
  defaults:
    partition: gpu
    time: "24:00:00"
    mem: "32G"
    gpus: 1

job_name_pattern: "{{ model }}_lr{{ learning_rate }}_bs{{ batch_size }}"
```

Generate scripts:

```bash
slurmkit generate job_spec.yaml --collection my_experiment
```

### 4. Submit Jobs

Submit all generated jobs:

```bash
slurmkit submit --collection my_experiment
```

Or submit specific scripts:

```bash
slurmkit submit jobs/my_exp/job_scripts/
```

### 5. Track Collection Status

View collection details:

```bash
slurmkit collection show my_experiment
```

Update job states:

```bash
slurmkit collection update my_experiment
```

### 6. Resubmit Failed Jobs

Resubmit failed jobs from a collection:

```bash
slurmkit resubmit --collection my_experiment --filter failed
```

### 7. Clean Up

Remove output files from failed jobs:

```bash
slurmkit clean outputs my_experiment --threshold 300 --min-age 3
```

## Next Steps

- See [Job Generation](job-generation.md) for advanced template usage
- See [Collections](collections.md) for collection management
- See [Configuration](configuration.md) for all config options
- See [Cross-Cluster Sync](sync.md) for multi-cluster workflows
