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
├── setup_dummy_jobs.py
├── templates/
│   ├── training.job.j2
│   └── evaluation.job.j2
├── experiments/
│   ├── hyperparameter_sweep/
│   │   ├── job_spec.yaml
│   │   ├── params_filter.py
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

Optional: enable AI callback demo for `notify collection-final` payloads:

```bash
export PYTHONPATH="$PWD:$PYTHONPATH"
# then in .slurm-kit/config.yaml:
# notifications.collection_final.ai.enabled: true
```

Create generated job-script projects (still no real submission):

```bash
slurmkit generate experiments/hyperparameter_sweep/job_spec.yaml --collection hp_sweep_demo
slurmkit generate experiments/model_comparison/job_spec.yaml --collection model_comp_demo
```

## Command Coverage Matrix

| Command | Demo status in this project | How to demo quickly |
|---|---|---|
| `slurmkit init` | Demoed | `slurmkit init` |
| `slurmkit status` | Partially demoed | Best with real submitted jobs; run after `submit` on cluster |
| `slurmkit find` | Demoed (dummy + real) | `slurmkit find 990002 --preview` |
| `slurmkit clean outputs` | Partially demoed | Works best after real failed jobs exist |
| `slurmkit clean wandb` | Not self-contained | Requires W&B setup/projects |
| `slurmkit generate` | Demoed | Use the two `generate` commands above |
| `slurmkit submit` | Demoed (`--dry-run` locally) | `slurmkit submit --collection hp_sweep_demo --dry-run` |
| `slurmkit resubmit` | Demoed (`--dry-run`/fixture collections) | `slurmkit resubmit --collection demo_terminal_failed --filter failed --dry-run` |
| `slurmkit collection create` | Demoed | `slurmkit collection create tmp_demo --description "tmp"` |
| `slurmkit collection list` | Demoed | `slurmkit collection list` |
| `slurmkit collection show` | Demoed | `slurmkit collection show demo_terminal_failed` |
| `slurmkit collection analyze` | Demoed | `slurmkit collection analyze demo_terminal_failed --attempt-mode latest` |
| `slurmkit collection update` | Partially demoed | Works best with real SLURM job IDs |
| `slurmkit collection delete` | Demoed | `slurmkit collection delete tmp_demo -y` |
| `slurmkit collection add` | Partially demoed | Best with discoverable job output files + IDs |
| `slurmkit collection remove` | Demoed | `slurmkit collection remove demo_terminal_failed 990001` |
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
# set notifications.collection_final.ai.enabled: true
slurmkit notify collection-final --collection demo_terminal_failed --job-id 990002 --no-refresh --dry-run
```

Look for `ai_status` and `ai_summary` in payload preview.

## End-to-End Cluster Workflow (Real SLURM)

```bash
slurmkit generate experiments/hyperparameter_sweep/job_spec.yaml --collection hp_sweep
slurmkit submit --collection hp_sweep --delay 2
slurmkit status hyperparameter_sweep
slurmkit collection update hp_sweep
slurmkit collection show hp_sweep
slurmkit resubmit --collection hp_sweep --filter failed
```

If you want notification hooks in a real job script:

```bash
trap 'rc=$?; slurmkit notify job --job-id "${SLURM_JOB_ID}" --exit-code "${rc}"; slurmkit notify collection-final --job-id "${SLURM_JOB_ID}"; exit "${rc}"' EXIT
```

## Notes

- `setup_dummy_jobs.py` is for local testing only. It creates synthetic job IDs/states/logs.
- `clean wandb`, full `status/update` behavior, and realistic `sync --push` are best validated in real environments.
- Notifications support webhook, Slack, Discord, and SMTP email routes; use `--dry-run` first before live sends.
