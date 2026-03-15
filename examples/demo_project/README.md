# slurmkit Demo Project

This demo project is designed for two use cases:
- run realistic examples on a SLURM cluster
- run local dummy-data demos without submitting real SLURM jobs

## Project Structure

```text
demo_project/
├── README.md
├── quickstart.sh
├── collection_ai_callback.py
├── notification_formatter_callback.py
├── setup_dummy_jobs.py
├── templates/
│   ├── training.job.j2
│   └── evaluation.job.j2
├── experiments/
│   ├── hyperparameter_sweep/
│   │   ├── job_spec.yaml
│   │   ├── params_logic.py
│   │   └── slurm_logic.py
│   └── model_comparison/
│       └── job_spec.yaml
└── .slurm-kit/
    └── config.yaml
```

## Quick Setup

```bash
cd examples/demo_project
python -m venv .venv
source .venv/bin/activate
pip install -e ../..
```

Initialize config if needed:

```bash
slurmkit init
```

Run the guided quickstart (includes optional notification demos and lets you choose dry-run vs live delivery):

```bash
chmod +x quickstart.sh
./quickstart.sh
```

## Webhook Setup (Brief)

To test real notification delivery (without `--dry-run`):

1. Create an incoming webhook URL in your target system (Slack, Discord, or custom endpoint).
2. Export the URL in your shell.
3. Reference it from `.slurm-kit/config.yaml` notifications routes.
4. Validate with `slurmkit notify test` (first with `--dry-run`, then without).

Example:

```bash
export DEMO_WEBHOOK_URL="https://example.com/your-webhook"
```

```yaml
notifications:
  routes:
    - name: demo_webhook
      type: webhook
      url: "${DEMO_WEBHOOK_URL}"
      events: [job_failed, collection_failed, collection_completed]
```

## Email Setup (Local SMTP, No Real Provider Needed)

Use a local SMTP server for end-to-end email notification tests:

```bash
pip install aiosmtpd
python -m aiosmtpd -n -l 127.0.0.1:1025
```

In another terminal:

```bash
cd examples/demo_project
source /Users/awni/Documents/project-code/slurmkit/.venv/bin/activate

export TEST_EMAIL_TO="you@example.com"
export TEST_EMAIL_FROM="slurmkit@example.com"
export TEST_SMTP_HOST="127.0.0.1"
export TEST_SMTP_PORT="1025"
```

Add/enable an email route in `.slurm-kit/config.yaml`:

```yaml
notifications:
  routes:
    - name: local_email
      type: email
      enabled: true
      events: [test_notification, job_failed, collection_failed, collection_completed]
      to: "${TEST_EMAIL_TO}"
      from: "${TEST_EMAIL_FROM}"
      smtp_host: "${TEST_SMTP_HOST}"
      smtp_port: "${TEST_SMTP_PORT}"
      smtp_starttls: false
      smtp_ssl: false
```

Then verify route resolution and live delivery:

```bash
slurmkit notify test --route local_email --dry-run
slurmkit notify test --route local_email
```

## Local Dummy Setup (No SLURM Required)

Create deterministic dummy collections/logs:

```bash
./setup_dummy_jobs.py --include-non-terminal
```

## Collection-Specific Notification Overrides (`spec.yaml`)

This demo now includes both override modes:

- `experiments/hyperparameter_sweep/job_spec.yaml` defines a top-level `notifications` block.
  Collections linked to this spec use collection-specific notification config.
- `experiments/model_comparison/job_spec.yaml` intentionally has no `notifications` block.
  Collections linked to this spec fall back to global `.slurm-kit/config.yaml`.

Refresh dummy collections with embedded `meta.generation.spec_path` metadata:

```bash
./setup_dummy_jobs.py --include-non-terminal
export PYTHONPATH="$PWD:$PYTHONPATH"
```

Compare behavior:

```bash
# Uses spec override (hyperparameter_sweep spec has notifications.job.ai.enabled=true)
slurmkit notify job --collection demo_terminal_failed --job-id 990002 --exit-code 1 --dry-run

# Uses global fallback (model_comparison spec has no notifications block)
slurmkit notify job --collection demo_terminal_completed --job-id 990011 --exit-code 0 --on always --dry-run
```

In dry-run payload preview, compare:
- `ai_status` / `ai_summary`
- output tail length behavior for failed jobs (`output_tail_lines`)

Collection-final behavior follows the same precedence:

```bash
slurmkit notify collection-final --collection demo_terminal_failed --job-id 990002 --no-refresh --dry-run
slurmkit notify collection-final --collection demo_terminal_completed --job-id 990011 --no-refresh --dry-run
```

If a collection references a missing/invalid spec, notify prints `[context-warning]` and falls back to global notifications.

Optional: force global AI callback behavior (for collections without spec overrides):

```bash
export PYTHONPATH="$PWD:$PYTHONPATH"
# then in .slurm-kit/config.yaml:
# notifications.job.ai.enabled: true
# notifications.collection_final.ai.enabled: true
```

Create generated job-script projects (still no real submission):

```bash
slurmkit generate experiments/hyperparameter_sweep/job_spec.yaml --into hp_sweep_demo
slurmkit generate experiments/model_comparison/job_spec.yaml --into model_comp_demo
```

## Command Coverage Matrix

| Command | Demo status in this project | How to demo quickly |
|---|---|---|
| `slurmkit init` | Demoed | `slurmkit init` |
| `slurmkit status` | Demoed | `slurmkit status demo_terminal_failed` |
| `slurmkit jobs status` | Partially demoed | Best with real submitted jobs; run after `submit` on cluster |
| `slurmkit jobs find` | Demoed (dummy + real) | `slurmkit jobs find 990002 --preview` |
| `slurmkit clean outputs` | Partially demoed | Collection-first; works best when tracked outputs exist |
| `slurmkit jobs clean outputs` | Partially demoed | Raw experiment cleanup after real failed jobs exist |
| `slurmkit clean wandb` | Not self-contained | Requires W&B setup/projects |
| `slurmkit generate` | Demoed | Use the two `generate` commands above |
| `slurmkit submit` | Demoed (`--dry-run` locally) | `slurmkit submit hp_sweep_demo --dry-run` |
| `slurmkit resubmit` | Demoed (`--dry-run`/fixture collections) | `slurmkit resubmit demo_terminal_failed --filter failed --dry-run` |
| `slurmkit collections create` | Demoed | `slurmkit collections create tmp_demo --description "tmp"` |
| `slurmkit collections list` | Demoed | `slurmkit collections list` |
| `slurmkit collections show` | Demoed | `slurmkit collections show demo_terminal_failed` |
| `slurmkit collections analyze` | Demoed | `slurmkit collections analyze demo_terminal_failed --attempt-mode latest` |
| `slurmkit collections refresh` | Partially demoed | Works best with real SLURM job IDs |
| `slurmkit collections delete` | Demoed | `slurmkit collections delete tmp_demo -y` |
| `slurmkit collections add` | Partially demoed | Best with discoverable job output files + IDs |
| `slurmkit collections remove` | Demoed | `slurmkit collections remove demo_terminal_failed 990001` |
| `slurmkit notify test` | Demoed | `slurmkit notify test --dry-run` |
| `slurmkit notify job` | Demoed (dummy context + dry-run) | `slurmkit notify job --job-id 990002 --exit-code 1 --dry-run` |
| `slurmkit notify collection-final` | Demoed | examples below |
| `slurmkit sync` | Partially demoed | `slurmkit sync`; `--push` needs git remote/workflow |

## Notification Demos (Dummy Data)

Use `setup_dummy_jobs.py` output collections:
- `demo_terminal_failed`
- `demo_terminal_completed`
- `demo_in_progress` (when `--include-non-terminal` is used)

### 1) Route sanity check

```bash
slurmkit notify test --dry-run
slurmkit notify test
slurmkit notify test --route local_email --dry-run
slurmkit notify test --route local_email
```

### 2) Job-level notification

```bash
slurmkit notify job --job-id 990002 --exit-code 1 --dry-run
slurmkit notify job --job-id 990001 --exit-code 0 --on always --dry-run
```

### 3) Collection-final failed/completed/non-terminal

```bash
slurmkit notify collection-final \
  --collection demo_terminal_failed \
  --job-id 990002 \
  --no-refresh \
  --dry-run

slurmkit notify collection-final \
  --collection demo_terminal_completed \
  --job-id 990011 \
  --no-refresh \
  --dry-run

slurmkit notify collection-final \
  --collection demo_in_progress \
  --job-id 990020 \
  --no-refresh \
  --dry-run
```

### 4) Dedup and force behavior

```bash
slurmkit notify collection-final --collection demo_terminal_failed --job-id 990002 --no-refresh
slurmkit notify collection-final --collection demo_terminal_failed --job-id 990002 --no-refresh
slurmkit notify collection-final --collection demo_terminal_failed --job-id 990002 --no-refresh --force
```

### 5) AI callback demo

```bash
export PYTHONPATH="$PWD:$PYTHONPATH"
# Already enabled by spec override for demo_terminal_failed
slurmkit notify job --collection demo_terminal_failed --job-id 990002 --exit-code 1 --dry-run

# Also enabled by spec override for demo_terminal_failed
slurmkit notify collection-final --collection demo_terminal_failed --job-id 990002 --no-refresh --dry-run

# For fallback collection (model_comparison spec has no notifications block),
# enable global config keys if you want AI summary there too:
# notifications.job.ai.enabled: true
# notifications.collection_final.ai.enabled: true
slurmkit notify job --collection demo_terminal_completed --job-id 990011 --exit-code 0 --on always --dry-run
```

Look for `ai_status` and `ai_summary` in payload preview.

### 6) Formatter callback demo

This demo project includes a callback module at `notification_formatter_callback.py`.
Add callback settings to `.slurm-kit/config.yaml` like this:

- global callback: `notification_formatter_callback:format_notification`
- route override for `local_email`: `notification_formatter_callback:format_local_email`
- explicit global opt-out on `team_email` via `formatter_callback: null`

Run from the demo directory so callback modules resolve cleanly:

```bash
cd examples/demo_project
```

If you run notify from another working directory, set:

```bash
export PYTHONPATH="/Users/awni/Documents/project-code/slurmkit/examples/demo_project:$PYTHONPATH"
```

Dry-run still validates callback loading/shape:

```bash
slurmkit notify test --route local_email --dry-run
slurmkit notify job --collection demo_terminal_failed --job-id 990002 --exit-code 1 --route local_email --dry-run
```

To inspect formatted email subject/body, run live against local SMTP (`aiosmtpd` from setup above):

```bash
slurmkit notify test --route local_email
slurmkit notify job --collection demo_terminal_failed --job-id 990002 --exit-code 1 --route local_email
```

Use these edits to experiment with precedence behavior:

```yaml
notifications:
  formatter:
    callback: "notification_formatter_callback:format_notification"
  routes:
    - name: local_email
      formatter_callback: "notification_formatter_callback:format_local_email"
    - name: team_email
      formatter_callback: null
```

## End-to-End Cluster Workflow (Real SLURM)

```bash
slurmkit generate experiments/hyperparameter_sweep/job_spec.yaml --into hp_sweep
slurmkit submit hp_sweep --delay 2
slurmkit status hp_sweep
slurmkit jobs status hyperparameter_sweep
slurmkit collections refresh hp_sweep
slurmkit collections show hp_sweep
slurmkit resubmit hp_sweep --filter failed
```

If you want notification hooks in a real job script:

```bash
trap 'rc=$?; slurmkit notify job --job-id "${SLURM_JOB_ID}" --exit-code "${rc}"; slurmkit notify collection-final --job-id "${SLURM_JOB_ID}" --trigger-exit-code "${rc}"; exit "${rc}"' EXIT
```

## Notes

- `setup_dummy_jobs.py` is for local testing only. It creates synthetic job IDs/states/logs.
- `clean wandb`, full `status/update` behavior, and realistic `sync --push` are best validated in real environments.
- Notifications support webhook, Slack, Discord, and SMTP email routes; use `--dry-run` first before live sends.
