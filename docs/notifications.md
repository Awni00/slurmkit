# Notifications

`slurmkit` supports webhook-based notifications for job lifecycle events.

Phase 1 transport types:
- `webhook`
- `slack`
- `discord`

Default behavior is failure-only notifications.

## Configuration

Add notification routes to `.slurm-kit/config.yaml`:

```yaml
notifications:
  defaults:
    events: [job_failed]
    timeout_seconds: 5
    max_attempts: 3
    backoff_seconds: 0.5
    output_tail_lines: 40

  routes:
    - name: team_slack
      type: slack
      url: "${SLACK_WEBHOOK_URL}"
      events: [job_failed]

    - name: personal_discord
      type: discord
      url: "${DISCORD_WEBHOOK_URL}"
      events: [job_failed, job_completed]

    - name: custom_ops
      type: webhook
      url: "${OPS_WEBHOOK_URL}"
      headers:
        Authorization: "Bearer ${OPS_WEBHOOK_TOKEN}"
      events: [job_failed]
```

Route-level settings override `notifications.defaults`.

## Commands

### Test routes

```bash
slurmkit notify test
slurmkit notify test --route team_slack
slurmkit notify test --dry-run
```

### Send job notification

```bash
slurmkit notify job --job-id 12345 --exit-code 1
slurmkit notify job --job-id 12345 --exit-code 0 --on always
slurmkit notify job --job-id 12345 --route team_slack --route custom_ops
slurmkit notify job --job-id 12345 --dry-run
```

`notify job` options:
- `--job-id JOB_ID` (optional if `SLURM_JOB_ID` is set)
- `--collection NAME` (optional metadata narrowing)
- `--exit-code N` (default: `0`)
- `--on failed|always` (default: `failed`)
- `--route NAME` (repeatable)
- `--tail-lines N` (failure output tail override)
- `--strict` (require all selected routes to succeed)
- `--dry-run` (preview without HTTP requests)

## Job Script Integration

Recommended shell pattern to preserve the original job exit code:

```bash
trap 'rc=$?; slurmkit notify job --job-id "${SLURM_JOB_ID}" --exit-code "${rc}"; exit "${rc}"' EXIT
```

If your script already handles exits explicitly, use the equivalent end-of-script flow:

```bash
rc=$?
slurmkit notify job --job-id "${SLURM_JOB_ID}" --exit-code "${rc}"
exit "${rc}"
```

## Event Model

`notify job` derives event from exit code:
- `exit_code != 0` -> `job_failed`
- `exit_code == 0` -> `job_completed`

By default (`--on failed`), completed jobs are skipped.

## Canonical Webhook Payload

For `type: webhook`, slurmkit sends a stable `schema_version: v1` payload with:
- `event`
- `generated_at`
- `context_source` (`collection_match`, `env_only`, `ambiguous_match`)
- `job` object
- `collection` object (if uniquely resolved)
- `host` object
- `meta` object (route name/type)

For `slack`/`discord`, slurmkit sends a human-readable summary with key metadata.
