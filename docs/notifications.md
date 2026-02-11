# Notifications

`slurmkit` supports webhook/chat and SMTP email notifications for job and collection lifecycle events.

Supported transport types:
- `webhook`
- `slack`
- `discord`
- `email` (SMTP)

Default behavior remains failure-first:
- `notify job` defaults to `--on failed`
- route event subscription defaults to `job_failed`

## Configuration

Add notification settings to `.slurm-kit/config.yaml`:

```yaml
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

  routes:
    - name: team_slack
      type: slack
      url: "${SLACK_WEBHOOK_URL}"
      events: [job_failed, collection_failed]

    - name: personal_discord
      type: discord
      url: "${DISCORD_WEBHOOK_URL}"
      events: [job_failed, job_completed]

    - name: custom_ops
      type: webhook
      url: "${OPS_WEBHOOK_URL}"
      headers:
        Authorization: "Bearer ${OPS_WEBHOOK_TOKEN}"
      events: [job_failed, collection_failed, collection_completed]

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
```

Route-level settings override `notifications.defaults`.

`url`, `headers`, and email fields support `${ENV_VAR}` interpolation. Missing env vars are reported as route configuration errors at runtime.

For `type: email`:
- required fields: `to`, `from`, `smtp_host`
- `to` supports string, comma-separated string, or list of strings
- `smtp_starttls` and `smtp_ssl` cannot both be `true`
- `smtp_username` and `smtp_password` must be set together (or both omitted)

### Collection-Specific Overrides from `spec.yaml`

When a collection was created via `slurmkit generate --spec-file ...`, slurmkit stores `meta.generation.spec_path` in the collection metadata.
`notify job` and `notify collection-final` use this precedence:

1. Top-level `notifications` in the collection's `spec.yaml`
2. Global `.slurm-kit/config.yaml` `notifications`

Merge semantics:
- Dictionary fields deep-merge (spec values override global values).
- List fields replace (not append), including `notifications.routes`.

If the spec file is missing, unreadable, or malformed, slurmkit prints a context warning and falls back to the global config.

Example `job_spec.yaml` override:

```yaml
notifications:
  defaults:
    output_tail_lines: 15
  job:
    ai:
      enabled: true
      callback: "collection_ai_callback:summarize_job_payload"
  collection_final:
    ai:
      enabled: true
      callback: "collection_ai_callback:summarize_collection_report"
```

See the runnable demo in `/Users/awni/Documents/project-code/slurmkit/examples/demo_project/README.md`.

## Commands

### Test routes

```bash
slurmkit notify test
slurmkit notify test --route team_slack
slurmkit notify test --dry-run
slurmkit notify test --route team_email --dry-run
# then run live (no --dry-run) once SMTP/env vars are configured
slurmkit notify test --route team_email
```

### Send job notification

```bash
slurmkit notify job --job-id 12345 --exit-code 1
slurmkit notify job --job-id 12345 --exit-code 0 --on always
slurmkit notify job --job-id 12345 --route team_slack --route custom_ops
slurmkit notify job --job-id 12345 --dry-run
```

### Send collection-final notification

```bash
slurmkit notify collection-final --job-id 12345
slurmkit notify collection-final --job-id 12345 --collection exp1
slurmkit notify collection-final --job-id 12345 --trigger-exit-code 0
slurmkit notify collection-final --job-id 12345 --route custom_ops --strict
slurmkit notify collection-final --job-id 12345 --no-refresh --dry-run
```

`notify collection-final` behavior:
- refreshes collection state before finality check (unless `--no-refresh`)
- uses latest-attempt semantics to classify each logical job
- sends `collection_completed` or `collection_failed` only when collection is terminal
- can treat collection as terminal when the only active effective row is the trigger job (`--job-id`)
- when that fallback path is used: `--trigger-exit-code 0` infers completed, non-zero infers failed
- if fallback is used without `--trigger-exit-code`, trigger state is inferred as `unknown` and a warning is printed
- deduplicates by terminal-state fingerprint (use `--force` to bypass)

## Job Script Integration

Recommended shell pattern to preserve original job exit code while triggering both job and collection-final notifications:

```bash
trap 'rc=$?; slurmkit notify job --job-id "${SLURM_JOB_ID}" --exit-code "${rc}"; slurmkit notify collection-final --job-id "${SLURM_JOB_ID}" --trigger-exit-code "${rc}"; exit "${rc}"' EXIT
```

If your script handles exits explicitly, use equivalent end-of-script flow:

```bash
rc=$?
slurmkit notify job --job-id "${SLURM_JOB_ID}" --exit-code "${rc}"
slurmkit notify collection-final --job-id "${SLURM_JOB_ID}" --trigger-exit-code "${rc}"
exit "${rc}"
```

## Event Model

`notify job` derives event from exit code:
- `exit_code != 0` -> `job_failed`
- `exit_code == 0` -> `job_completed`

`notify collection-final` emits:
- `collection_failed` when terminal and any effective job is failed/unknown
- `collection_completed` when terminal and all effective jobs are completed

By default (`--on failed`), completed job notifications are skipped.

## Canonical Webhook Payload

For `type: webhook`, slurmkit sends stable `schema_version: v1` JSON.

Job payload includes:
- `event`
- `generated_at`
- `context_source` (`collection_match`, `env_only`, `ambiguous_match`)
- `job`
- `collection` (when uniquely resolved)
- `ai_status`
- optional `ai_summary`
- `host`
- `meta` (route name/type)

Collection-final payload additionally includes:
- `collection_report` (summary counts, failed rows, risky/stable values, recommendations)
- `trigger_job_id`
- `ai_status`
- optional `ai_summary`

Test payload includes deterministic baseline fields and does not run AI callbacks.

For `slack`/`discord`, slurmkit sends a human-readable summary with key metadata.

For `email`, slurmkit sends plain-text emails through SMTP with built-in subject/body formatting.
