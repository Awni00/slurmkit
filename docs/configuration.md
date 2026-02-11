# Configuration

slurmkit uses a layered configuration system with the following precedence (highest to lowest):

1. **CLI arguments** - Override everything
2. **Environment variables** - System-level defaults
3. **Project config file** - `.slurm-kit/config.yaml`
4. **Built-in defaults** - Fallback values

## Configuration File

The project configuration file is located at `.slurm-kit/config.yaml` relative to your project root.

### Creating Configuration

Initialize configuration interactively:

```bash
slurmkit init
```

Or create/edit `.slurm-kit/config.yaml` manually.

### Full Configuration Reference

```yaml
# =============================================================================
# Directory Structure
# =============================================================================

# Root directory for job files (scripts, outputs)
# Relative paths are resolved from project root
jobs_dir: jobs/

# Directory for collection YAML files
collections_dir: .job-collections/

# Directory for cross-cluster sync files
sync_dir: .slurm-kit/sync/

# =============================================================================
# Output File Patterns
# =============================================================================

# Patterns to match job output files
# Tried in order; first match wins
# Placeholders: {job_name}, {job_id}
output_patterns:
  - "{job_name}.{job_id}.out"
  - "{job_name}.{job_id}.*.out"
  - "slurm-{job_id}.out"

# =============================================================================
# Job Directory Structure
# =============================================================================

# Subdirectory names within each experiment directory
job_structure:
  scripts_subdir: job_scripts/   # Where job scripts are stored
  logs_subdir: logs/             # Where output files are stored

# =============================================================================
# Default SLURM Arguments
# =============================================================================

# These defaults are used when generating jobs
slurm_defaults:
  partition: compute
  time: "24:00:00"
  mem: "16G"
  nodes: 1
  ntasks: 1
  # Add any other SLURM directives here
  # gpus: 1
  # cpus-per-task: 4

# =============================================================================
# Cleanup Settings
# =============================================================================

cleanup:
  # Minimum runtime (seconds) for jobs to keep during cleanup
  # Jobs that failed faster than this are candidates for deletion
  threshold_seconds: 300

  # Minimum age (days) for jobs to consider during cleanup
  # Prevents deleting recent failures that might be retrying
  min_age_days: 3

# =============================================================================
# CLI UI Settings
# =============================================================================

ui:
  # plain: always plain tables
  # rich: require Rich rendering
  # auto: use Rich on interactive terminals when available, else plain
  mode: plain

# =============================================================================
# Notifications (Optional)
# =============================================================================

notifications:
  defaults:
    # Applied when route-level settings are not provided
    events: [job_failed]
    timeout_seconds: 5
    max_attempts: 3
    backoff_seconds: 0.5
    output_tail_lines: 40

  job:
    ai:
      enabled: false
      callback: null  # "module.path:function_name"

  collection_final:
    attempt_mode: latest
    min_support: 3
    top_k: 10
    include_failed_output_tail_lines: 20
    ai:
      enabled: false
      callback: null  # "module.path:function_name"

  routes:
    - name: team_slack
      type: slack            # slack | discord | webhook | email
      url: "${SLACK_WEBHOOK_URL}"
      enabled: true
      events: [job_failed, collection_failed]
      headers: {}
      timeout_seconds: 5
      max_attempts: 3
      backoff_seconds: 0.5

    - name: team_email
      type: email
      to: ["ops@example.com", "ml@example.com"]
      from: "${SLURMKIT_EMAIL_FROM}"
      smtp_host: "${SMTP_HOST}"
      smtp_port: 587
      smtp_username: "${SMTP_USER}"
      smtp_password: "${SMTP_PASSWORD}"
      smtp_starttls: true
      smtp_ssl: false
      events: [job_failed, collection_failed]

# =============================================================================
# W&B Settings (Optional)
# =============================================================================

wandb:
  # Your W&B username or team name
  entity: null

  # Default projects for cleanup commands
  default_projects: []
```

## Environment Variables

All settings can be overridden via environment variables:

| Variable | Description | Example |
|----------|-------------|---------|
| `SLURMKIT_CONFIG` | Path to config file | `/path/to/config.yaml` |
| `SLURMKIT_JOBS_DIR` | Jobs directory | `experiments/` |
| `SLURMKIT_COLLECTIONS_DIR` | Collections directory | `.collections/` |
| `SLURMKIT_SYNC_DIR` | Sync files directory | `.slurm-kit/sync/` |
| `SLURMKIT_WANDB_ENTITY` | W&B entity | `awni00` |
| `SLURMKIT_WANDB_PROJECT` | Default W&B project | `my-project` |
| `SLURMKIT_DRY_RUN` | Global dry-run mode | `1` or `true` |

### Example Usage

```bash
# Use different jobs directory
export SLURMKIT_JOBS_DIR=experiments/

# Enable dry-run mode globally
export SLURMKIT_DRY_RUN=1

# Run command with overrides
slurmkit status exp1
```

## CLI Overrides

Most commands accept arguments to override configuration:

```bash
# Override jobs directory
slurmkit status exp1 --jobs-dir /custom/path/

# Override config file
slurmkit --config /path/to/config.yaml status exp1

# Override UI mode for one command
slurmkit --ui rich collection analyze exp1
```

## UI Mode Resolution

UI mode is resolved in this order:

1. CLI override: `--ui {plain,rich,auto}`
2. Config value: `ui.mode`
3. Fallback: `plain`

If `--ui rich` is requested but Rich is not installed, slurmkit exits with an install hint:

```bash
pip install slurmkit[ui]
```

## Output File Patterns

The `output_patterns` setting controls how slurmkit finds and parses job output files.

### Pattern Syntax

- `{job_name}` - Matches the job name (any characters)
- `{job_id}` - Matches the SLURM job ID (digits, optional underscore for arrays)
- `*` - Wildcard (any characters except dots)

### Common Patterns

```yaml
output_patterns:
  # Standard pattern: job_name.job_id.out
  - "{job_name}.{job_id}.out"

  # With extra suffix: job_name.job_id.hostname.out
  - "{job_name}.{job_id}.*.out"

  # SLURM default: slurm-job_id.out
  - "slurm-{job_id}.out"

  # Array jobs: job_name.job_id_index.out
  - "{job_name}.{job_id}.out"
```

### Priority

Patterns are tried in order. Use more specific patterns first:

```yaml
output_patterns:
  # More specific first
  - "{job_name}.{job_id}.node01.out"
  - "{job_name}.{job_id}.*.out"
  # Generic fallback last
  - "slurm-{job_id}.out"
```

## SLURM Defaults

The `slurm_defaults` section provides default values for job generation:

```yaml
slurm_defaults:
  partition: gpu
  time: "48:00:00"
  mem: "64G"
  nodes: 1
  ntasks: 1
  gpus: 2
  cpus-per-task: 8

  # Any valid SLURM directive
  mail-user: user@example.com
  mail-type: END,FAIL
```

These are passed to job templates as `{{ slurm.partition }}`, `{{ slurm.time }}`, etc.

## Notifications

Use `notifications.routes` to define where `slurmkit notify` sends events.

### Route Fields

- `name` - Unique route name used by `slurmkit notify --route ...`
- `type` - `webhook`, `slack`, `discord`, or `email`
- `url` - Destination URL for `webhook`/`slack`/`discord`; supports `${ENV_VAR}` interpolation
- `enabled` - Optional boolean (default: `true`)
- `events` - Optional list of subscribed events
- `headers` - Optional HTTP headers map for `webhook`; supports `${ENV_VAR}` interpolation
- `timeout_seconds` - Optional request timeout override
- `max_attempts` - Optional retry attempts override
- `backoff_seconds` - Optional retry backoff override

Email-specific route fields:
- `to` - Required recipient list (string, comma-separated string, or list)
- `from` - Required sender address
- `smtp_host` - Required SMTP host
- `smtp_port` - Optional SMTP port (default: `587`)
- `smtp_username` / `smtp_password` - Optional auth pair (must be set together)
- `smtp_starttls` - Optional boolean (default: `true`)
- `smtp_ssl` - Optional boolean (default: `false`)

Supported events:
- `job_failed`
- `job_completed`
- `collection_failed`
- `collection_completed`

### Defaults Behavior

- If `events` is omitted on a route, it defaults to `notifications.defaults.events`.
- If `notifications.defaults.events` is omitted, it defaults to `[job_failed]`.
- Retry and timeout values fall back from route settings to `notifications.defaults`.

### Job Notification AI Settings

`notifications.job.ai` controls optional callback enrichment for `slurmkit notify job`:
- `enabled` - Enable optional Python callback enrichment
- `callback` - Callback in `module.path:function_name` format

When job AI callback execution fails, deterministic notification delivery still proceeds and payload marks `ai_status: unavailable`.

### Collection Final Report Settings

`notifications.collection_final` controls `slurmkit notify collection-final` behavior:
- `attempt_mode` - `latest` (default) or `primary`
- `min_support` - Support threshold for risky/stable analysis tables
- `top_k` - Number of top risky/stable values included in report
- `include_failed_output_tail_lines` - Tail lines embedded per failed job
- `ai.enabled` - Enable optional Python callback enrichment
- `ai.callback` - Callback in `module.path:function_name` format

When AI callback execution fails, deterministic report delivery still proceeds and payload marks `ai_status: unavailable`.

### Collection Spec Notification Overrides

Collections generated from `job_spec.yaml` persist `meta.generation.spec_path`.
At notify-time, slurmkit loads that spec and checks for a top-level `notifications` block.

Precedence:
- `spec.yaml` top-level `notifications` (collection-specific override)
- `.slurm-kit/config.yaml` `notifications` (global fallback)

Merge behavior:
- Mapping values deep-merge recursively.
- List values replace global values (including `notifications.routes`).

Fallback behavior:
- If the spec file is missing/unreadable/malformed, slurmkit emits a context warning and falls back to global notifications.
- If the spec has no top-level `notifications` key, global notifications are used without warning.

### Environment Variable Interpolation

Webhook fields support `${VAR_NAME}` placeholders:

```yaml
notifications:
  routes:
    - name: secure_webhook
      type: webhook
      url: "${NOTIFY_WEBHOOK_URL}"
      headers:
        Authorization: "Bearer ${NOTIFY_WEBHOOK_TOKEN}"
```

Email SMTP fields support the same interpolation:

```yaml
notifications:
  routes:
    - name: mail_alerts
      type: email
      to: "${EMAIL_RECIPIENTS}"
      from: "${EMAIL_FROM}"
      smtp_host: "${SMTP_HOST}"
      smtp_username: "${SMTP_USER}"
      smtp_password: "${SMTP_PASSWORD}"
```

If any referenced variable is missing, that route is treated as a route-level configuration error at runtime.

## Programmatic Access

Access configuration from Python:

```python
from slurmkit import get_config

# Get global config
config = get_config()

# Access values
jobs_dir = config.get_path("jobs_dir")
partition = config.get("slurm_defaults.partition")
patterns = config.get_output_patterns()

# Get full config as dict
config_dict = config.as_dict()
```
