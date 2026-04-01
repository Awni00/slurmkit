# Configuration

`slurmkit` loads configuration in this order:

1. CLI flags
2. Environment variables
3. Project config file at `.slurmkit/config.yaml`
4. Built-in defaults

## Config file location

The project config file lives at:

```text
.slurmkit/config.yaml
```

Create it with:

```bash
slurmkit init
```

## Current config shape

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
  nodes: 1
  ntasks: 1

cleanup:
  threshold_seconds: 300
  min_age_days: 3

ui:
  mode: auto
  interactive: true
  show_banner: true

notifications:
  defaults:
    events: [job_failed]
    timeout_seconds: 5
    max_attempts: 3
    backoff_seconds: 0.5
    output_tail_lines: 40
  job:
    ai:
      enabled: false
      callback: null
  collection_final:
    attempt_mode: latest
    min_support: 3
    top_k: 10
    include_failed_output_tail_lines: 20
    ai:
      enabled: false
      callback: null
  routes: []

wandb:
  entity: null
  default_projects: []
```

## Derived directories

These paths are fixed and derived from the project root. They are not public config keys:

- `.slurmkit/collections/`
- `.slurmkit/sync/`
- `.slurmkit/locks/collections/`
- `.slurmkit/backups/`

`jobs_dir` is the only top-level path root you configure directly.

## Jobs layout

Specs define a relative `job_subdir` (including templated values that resolve to a relative path). `slurmkit` then derives:

- `{jobs_dir}/{job_subdir}/job_scripts/`
- `{jobs_dir}/{job_subdir}/logs/`

Example:

```yaml
jobs_dir: .jobs/
```

```yaml
job_subdir: comparisons/model_a
```

or

```yaml
job_subdir: comparisons/{{ collection_slug }}/{{ vars.variant }}
variables:
  variant: model_a
```

This yields:

- `.jobs/comparisons/model_a/job_scripts/`
- `.jobs/comparisons/model_a/logs/`

## Environment variables

| Variable | Description |
|---|---|
| `SLURMKIT_CONFIG` | Override config file path |
| `SLURMKIT_JOBS_DIR` | Override `jobs_dir` |
| `SLURMKIT_WANDB_ENTITY` | Override `wandb.entity` |
| `SLURMKIT_WANDB_PROJECT` | Override `wandb.default_project` |
| `SLURMKIT_DRY_RUN` | Enable global dry-run mode |

## UI settings

`ui.mode` controls human-readable rendering:

- `plain`
- `rich`
- `auto`

`ui.interactive` enables prompt fallback and the command picker when the terminal supports it.

## Notifications

Global notification settings live under `notifications`. Collection-specific overrides can also be stored at the top level of a job spec. At notify-time, spec-level notifications override the global config via deep merge.

See [Notifications](notifications.md) for the route schema and callback examples.
