# Getting Started

This guide walks through the current `slurmkit` workflow: initialize config, generate a collection, submit it, monitor it, and retry failures.

## Install

### From source

```bash
git clone https://github.com/Awni00/slurmkit.git
cd slurmkit
pip install -e ".[all]"
```

### From PyPI

```bash
pip install slurmkit
```

## Initialize a project

From your project root:

```bash
slurmkit init
```

This creates `.slurmkit/config.yaml` and the derived metadata directories:

- `.slurmkit/collections/`
- `.slurmkit/sync/`
- `.slurmkit/locks/collections/`

By default, generated job artifacts go under `.jobs/`.

## Minimal config

```yaml
jobs_dir: .jobs/

output_patterns:
  - "{job_name}.{job_id}.out"
  - "{job_name}.{job_id}.*.out"
  - "slurm-{job_id}.out"

slurm_defaults:
  partition: compute
  time: "24:00:00"
  mem: "16G"

ui:
  mode: auto
  interactive: true
  show_banner: true
```

`collections_dir`, `sync_dir`, and job subdirectory names are no longer user-configurable. They are fixed under `.slurmkit/` and `.jobs/`.

## Create a job spec

```yaml
name: my_experiment
description: "Hyperparameter sweep"

template: train.job.j2
job_subdir: experiments/my_experiment

parameters:
  mode: grid
  values:
    learning_rate: [0.001, 0.01]
    batch_size: [32, 64]

slurm_args:
  defaults:
    partition: gpu
    time: "08:00:00"
    mem: "32G"

job_name_pattern: "lr{{ learning_rate }}_bs{{ batch_size }}"
```

With this spec and the default config, `slurmkit` writes:

- scripts to `.jobs/experiments/my_experiment/job_scripts/`
- logs to `.jobs/experiments/my_experiment/logs/`

## Generate a collection

```bash
slurmkit generate experiments/my_experiment/slurmkit/job_spec.yaml --into my_experiment
```

Interactive mode helps when arguments are missing:

- `slurmkit`
- `slurmkit generate`
- `slurmkit submit`
- `slurmkit status`

In non-interactive mode or with `--nointeractive`, required args must be provided explicitly.

## Submit and inspect

```bash
slurmkit submit my_experiment --dry-run
slurmkit submit my_experiment

slurmkit status my_experiment
slurmkit collections show my_experiment
slurmkit collections analyze my_experiment
```

Refresh collection state from SLURM explicitly:

```bash
slurmkit collections refresh my_experiment
```

## Retry failures

```bash
slurmkit resubmit my_experiment --filter failed --dry-run
slurmkit resubmit my_experiment --filter failed
```

Collection resubmission regenerates scripts by default and stores retry attempts in the collection history.

## Notifications

```bash
slurmkit notify test --dry-run
slurmkit notify job --job-id 123456 --exit-code 1 --dry-run
slurmkit notify collection-final --collection my_experiment --job-id 123456 --dry-run
```

## Migrate old projects

If a repo still uses `.slurm-kit/`, `.job-collections/`, or specs with `output_dir` / `logs_dir`, run:

```bash
slurmkit migrate
```

Migration rewrites local state into the current `.slurmkit/` and `job_subdir` model and stores backups under `.slurmkit/backups/`.

## Demo project

The repo includes a runnable demo in [examples/demo_project](/Users/awni/.codex/worktrees/0586/slurmkit/examples/demo_project):

```bash
cd examples/demo_project
python -m venv .venv
source .venv/bin/activate
pip install -e ../..
slurmkit init
./quickstart.sh
```
