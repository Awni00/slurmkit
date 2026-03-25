# slurmkit

A CLI toolkit for generating, tracking, and resubmitting SLURM jobs with a collection-first workflow.

## What slurmkit does

- Generates SLURM job scripts from Jinja templates and YAML specs
- Organizes related jobs into named collections
- Tracks collection state across submissions and retries
- Sends job and collection-final notifications
- Writes per-host sync snapshots for multi-cluster repos
- Cleans up failed outputs and W&B runs

## Quick Start

### 1. Initialize a project

```bash
cd your-project
slurmkit init
```

This creates `.slurmkit/config.yaml` and the standard metadata layout:

```text
your-project/
├── .slurmkit/
│   ├── config.yaml
│   ├── collections/
│   ├── sync/
│   ├── locks/
│   │   └── collections/
│   └── backups/
└── .jobs/
```

### 2. Create a spec

```yaml
name: exp1
template: train.job.j2
job_subdir: sweeps/exp1

parameters:
  mode: grid
  values:
    learning_rate: [0.001, 0.01]
    batch_size: [32, 64]

slurm_args:
  defaults:
    partition: gpu
    time: "04:00:00"

job_name_pattern: "lr{{ learning_rate }}_bs{{ batch_size }}"
```

`job_subdir` is always relative to `jobs_dir`. With the default config, this spec writes:

- scripts to `.jobs/sweeps/exp1/job_scripts/`
- logs to `.jobs/sweeps/exp1/logs/`

### 3. Generate into a collection

```bash
slurmkit generate experiments/exp1/slurmkit/job_spec.yaml --into exp1
```

### 4. Submit and monitor

```bash
slurmkit submit exp1 --dry-run
slurmkit submit exp1
slurmkit status exp1
slurmkit collections show exp1
slurmkit collections analyze exp1
```

### 5. Retry failures

```bash
slurmkit resubmit exp1 --filter failed --dry-run
slurmkit resubmit exp1 --filter failed
slurmkit resubmit --job-id 123456 --no-regenerate -y
```

## Main commands

| Command | Purpose |
|---|---|
| `slurmkit` / `slurmkit home` | Open the interactive command picker |
| `slurmkit init` | Create `.slurmkit/config.yaml` |
| `slurmkit migrate` | Rewrite old `.slurm-kit/` and `.job-collections/` state |
| `slurmkit generate <spec> --into <collection>` | Generate job scripts into a collection |
| `slurmkit submit <collection>` | Submit jobs from a collection |
| `slurmkit resubmit [collection] [--job-id <id>]` | Retry failed/all jobs in a collection, or one tracked job by ID |
| `slurmkit status <collection>` | Compact live status view |
| `slurmkit collections ...` | List, inspect, analyze, refresh, cancel, delete |
| `slurmkit notify ...` | Send test, job, or collection-final notifications |
| `slurmkit sync` | Write per-host sync snapshot |
| `slurmkit clean ...` | Cleanup outputs or W&B runs |

## Filesystem model

`slurmkit` uses two roots:

- `.slurmkit/` for metadata and local state
- `.jobs/` for generated job scripts and logs

Collections are stored as YAML files under `.slurmkit/collections/`. Sync snapshots are derived per-host exports under `.slurmkit/sync/`. Collection-final locks live under `.slurmkit/locks/collections/`.

## Next steps

- [Getting Started](getting-started.md)
- [Configuration](configuration.md)
- [Job Generation](job-generation.md)
- [Collections](collections.md)
- [Notifications](notifications.md)
- [Cross-Cluster Sync](sync.md)
