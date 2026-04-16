# Collections

Collections are the canonical unit of work in `slurmkit`. A collection groups related jobs, stores attempt history, and supports inspection, refresh, cancel, cleanup, and retry workflows.

## Storage location

Collections are stored as YAML files under:

```text
.slurmkit/collections/
```

Collection IDs are slash-separated safe identifiers. For example, the ID
`experiment/group/run_20260406` is stored at:

```text
.slurmkit/collections/experiment/group/run_20260406.yaml
```

Each segment must match `[A-Za-z0-9._-]+`. Spaces, backslashes, empty
segments, `.`/`..`, and absolute paths are rejected.

## Current schema

Collections use the v2 attempts-based schema. Each job has stable metadata plus an ordered `attempts` list.

```yaml
version: 2
name: experiment/group/run_20260406
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
        raw_state:
          rows:
            parent:
              job_id: "123456"
              state_raw: PREEMPTED
              state_base: PREEMPTED
            batch:
              job_id: "123456.batch"
              state_raw: COMPLETED
              state_base: COMPLETED
            extern: null
            others: []
          resolution:
            canonical_state: COMPLETED
            rule: batch_completed_exit_zero
            used_row: batch
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
slurmkit collections show experiment/group/run_20260406
slurmkit collections show experiment/group/run_20260406 --state failed
slurmkit collections show experiment/group/run_20260406 --json
```

### Analyze outcomes by parameter

```bash
slurmkit collections analyze experiment/group/run_20260406
slurmkit collections analyze experiment/group/run_20260406 --param learning_rate --param batch_size
slurmkit collections analyze experiment/group/run_20260406 --min-support 5 --top-k 20
slurmkit collections analyze experiment/group/run_20260406 --json
```

### Refresh from SLURM

```bash
slurmkit collections refresh experiment/group/run_20260406
slurmkit collections refresh --all
```

### Cancel active jobs

```bash
slurmkit collections cancel experiment/group/run_20260406 --dry-run
slurmkit collections cancel experiment/group/run_20260406 -y
```

### Delete a collection

```bash
slurmkit collections delete experiment/group/run_20260406 -y
```

## Workflow

Typical collection lifecycle:

```bash
slurmkit generate experiments/exp1/slurmkit/job_spec.yaml --into experiment/group/run_20260406
slurmkit submit experiment/group/run_20260406
slurmkit status experiment/group/run_20260406
slurmkit collections show experiment/group/run_20260406
slurmkit resubmit experiment/group/run_20260406 --filter failed
```

## Status semantics

- `slurmkit status <collection>` is the compact live entry point
- `slurmkit collections show <collection>` is the fuller collection view
- `slurmkit collections analyze <collection>` summarizes parameter-outcome patterns
- `attempt.state` is canonical (deterministic) state used for filtering, summaries, and resubmit behavior
- `attempt.raw_state` stores full `sacct` row diagnostics (`parent`, `.batch`, `.extern`, other rows) and resolution metadata

## Migration note

Older collection files from `.job-collections/` and the pre-v2 schema are rewritten by:

```bash
slurmkit migrate
```
