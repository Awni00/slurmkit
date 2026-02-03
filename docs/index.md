# slurmkit

A CLI toolkit for managing and generating SLURM jobs.

**slurmkit** provides tools for:

- Auto-discovering and tracking SLURM job status
- Generating job scripts from templates with parameter sweeps
- Organizing jobs into trackable collections
- Cross-cluster job synchronization
- Cleaning up failed jobs and W&B runs

## Installation

### From Source

```bash
pip install git+https://github.com/Awni00/slurmkit.git
```

### Dependencies

**Required:**

- Python 3.8+
- PyYAML
- Jinja2
- pandas
- tabulate

**Optional:**

- wandb (for W&B cleanup features)

## Quick Start

### 1. Initialize Project

```bash
cd your-project
slurmkit init
```

This creates `.slurm-kit/config.yaml` with your settings.

### 2. Check Job Status

```bash
slurmkit status my_experiment
```

### 3. Generate Jobs from Template

Create a template `templates/train.job.j2`:

```jinja2
#!/bin/bash
#SBATCH --job-name={{ job_name }}
#SBATCH --partition={{ slurm.partition }}
#SBATCH --time={{ slurm.time }}
#SBATCH --output={{ logs_dir }}/{{ job_name }}.%j.out

python train.py --lr {{ learning_rate }} --bs {{ batch_size }}
```

Create a job spec `experiments/exp1/job_spec.yaml`:

```yaml
name: exp1
template: ../../templates/train.job.j2
output_dir: job_scripts
logs_dir: logs

parameters:
  mode: grid
  values:
    learning_rate: [0.001, 0.01, 0.1]
    batch_size: [32, 64]

slurm_args:
  defaults:
    partition: gpu
    time: "24:00:00"

job_name_pattern: "lr{{ learning_rate }}_bs{{ batch_size }}"
```

Generate jobs:

```bash
slurmkit generate experiments/exp1/job_spec.yaml --collection exp1
```

### 4. Submit Jobs

```bash
slurmkit submit --collection exp1
```

### 5. Monitor and Resubmit

```bash
# Update job states
slurmkit collection update exp1

# View collection status
slurmkit collection show exp1

# Resubmit failed jobs
slurmkit resubmit --collection exp1 --filter failed
```

## Commands

| Command | Description |
|---------|-------------|
| `slurmkit init` | Initialize project configuration |
| `slurmkit status <exp>` | Show job status for experiment |
| `slurmkit find <job_id>` | Find output file for job ID |
| `slurmkit generate <spec>` | Generate job scripts from template |
| `slurmkit submit` | Submit job scripts |
| `slurmkit resubmit` | Resubmit failed jobs |
| `slurmkit collection` | Manage job collections |
| `slurmkit clean outputs` | Clean failed job outputs |
| `slurmkit clean wandb` | Clean failed W&B runs |
| `slurmkit sync` | Sync job states for cross-cluster |

Run `slurmkit <command> --help` for detailed usage.

## Configuration

Configuration is stored in `.slurm-kit/config.yaml`:

```yaml
jobs_dir: jobs/
collections_dir: .job-collections/

output_patterns:
  - "{job_name}.{job_id}.out"
  - "{job_name}.{job_id}.*.out"

slurm_defaults:
  partition: gpu
  time: "24:00:00"
  mem: "32G"

job_structure:
  scripts_subdir: job_scripts/
  logs_subdir: logs/
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `SLURMKIT_CONFIG` | Path to config file |
| `SLURMKIT_JOBS_DIR` | Jobs directory |
| `SLURMKIT_COLLECTIONS_DIR` | Collections directory |
| `SLURMKIT_WANDB_ENTITY` | W&B entity |
| `SLURMKIT_DRY_RUN` | Enable dry-run mode |

## Project Structure

```
your-project/
├── .slurm-kit/
│   ├── config.yaml          # Project configuration
│   └── sync/                 # Cross-cluster sync files
├── .job-collections/         # Collection YAML files
├── jobs/
│   └── experiment1/
│       ├── job_scripts/      # Generated job scripts
│       └── logs/             # Job output files
└── templates/                # Jinja2 job templates
```

## Features

### Job Collections

Track related jobs together:

```bash
# Create collection
slurmkit collection create my_exp --description "Training sweep"

# List collections
slurmkit collection list

# Show details
slurmkit collection show my_exp --state failed

# Update states from SLURM
slurmkit collection update my_exp
```

### Parameter Sweeps

Generate jobs from parameter grids:

```yaml
parameters:
  mode: grid
  values:
    learning_rate: [0.001, 0.01, 0.1]
    batch_size: [32, 64, 128]
    model: [resnet18, resnet50]
```

Or explicit lists:

```yaml
parameters:
  mode: list
  values:
    - {lr: 0.001, bs: 32}
    - {lr: 0.01, bs: 64}
```

### Dynamic SLURM Arguments

Use Python functions for complex resource logic:

```python
# slurm_logic.py
def get_slurm_args(params, defaults):
    args = defaults.copy()
    if params.get('model') == 'resnet50':
        args['mem'] = '64G'
        args['gpus'] = 2
    return args
```

### Cross-Cluster Sync

Share job status across clusters via git:

```bash
# On cluster A
slurmkit sync --push

# On cluster B
git pull
slurmkit collection show my_exp
```

## License

MIT License - see [LICENSE](https://github.com/Awni00/slurmkit/blob/main/LICENSE) for details.
