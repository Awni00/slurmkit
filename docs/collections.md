# Collections

Collections are the canonical unit of work in `slurmkit`. A collection groups related jobs, stores attempt history, and supports inspection, refresh, cancel, cleanup, and retry workflows.

## Storage location

Collections are stored as YAML files under:

```text
.slurmkit/collections/
```

## Current schema

Collections use the v2 attempts-based schema. Each job has stable metadata plus an ordered `attempts` list.

```yaml
version: 2
name: my_experiment
description: "Example sweep"
created_at: "2026-03-15T10:30:00"
updated_at: "2026-03-15T14:00:00"
cluster: cluster-a

parameters:
  source: job_spec.yaml

generation:
  spec_path: experiments/exp1/slurmkit/job_spec.yaml
  job_subdir: sweeps/exp1
  scripts_dir: /abs/path/to/.jobs/sweeps/exp1/job_scripts
  logs_dir: /abs/path/to/.jobs/sweeps/exp1/logs

notifications: {}

jobs:
  - job_name: lr0.001_bs32
    parameters:
      learning_rate: 0.001
      batch_size: 32
    attempts:
      - kind: primary
        job_id: "123456"
        state: COMPLETED
        script_path: /abs/path/to/.jobs/sweeps/exp1/job_scripts/lr0.001_bs32.job
        output_path: /abs/path/to/.jobs/sweeps/exp1/logs/lr0.001_bs32.123456.out
        submitted_at: "2026-03-15T10:35:00"
        completed_at: "2026-03-15T11:12:00"
        submission_group: null
        regenerated: false
        extra_params: {}

  - job_name: lr0.01_bs64
    parameters:
      learning_rate: 0.01
      batch_size: 64
    attempts:
      - kind: primary
        job_id: "123457"
        state: FAILED
      - kind: resubmission
        job_id: "123500"
        state: RUNNING
        submission_group: resubmit_20260315_141500
        regenerated: true
        extra_params:
          checkpoint: checkpoints/last.pt
```

## Main commands

### List collections

```bash
slurmkit collections list
```

### Show one collection

```bash
slurmkit collections show exp1
slurmkit collections show exp1 --state failed
slurmkit collections show exp1 --json
```

### Analyze outcomes by parameter

```bash
slurmkit collections analyze exp1
slurmkit collections analyze exp1 --param learning_rate --param batch_size
slurmkit collections analyze exp1 --min-support 5 --top-k 20
slurmkit collections analyze exp1 --json
```

### Refresh from SLURM

```bash
slurmkit collections refresh exp1
slurmkit collections refresh --all
```

### Cancel active jobs

```bash
slurmkit collections cancel exp1 --dry-run
slurmkit collections cancel exp1 -y
```

### Delete a collection

```bash
slurmkit collections delete exp1 -y
```

## Workflow

Typical collection lifecycle:

```bash
slurmkit generate experiments/exp1/slurmkit/job_spec.yaml --into exp1
slurmkit submit exp1
slurmkit status exp1
slurmkit collections show exp1
slurmkit resubmit exp1 --filter failed
```

## Status semantics

- `slurmkit status <collection>` is the compact live entry point
- `slurmkit collections show <collection>` is the fuller collection view
- `slurmkit collections analyze <collection>` summarizes parameter-outcome patterns

## Migration note

Older collection files from `.job-collections/` and the pre-v2 schema are rewritten by:

```bash
slurmkit migrate
```
