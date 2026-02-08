![slurmkit header](https://raw.githubusercontent.com/Awni00/slurmkit/main/docs/assets/slurmkit-header-landscape.png)

<p align="center">
  <a href="https://github.com/Awni00/slurmkit/actions/workflows/tests.yml"><img src="https://github.com/Awni00/slurmkit/actions/workflows/tests.yml/badge.svg" alt="Unit Tests"></a>
  <a href="https://github.com/Awni00/slurmkit/actions/workflows/docs.yml"><img src="https://github.com/Awni00/slurmkit/actions/workflows/docs.yml/badge.svg" alt="Docs"></a>
  <a href="https://github.com/Awni00/slurmkit/actions/workflows/publish.yml"><img src="https://github.com/Awni00/slurmkit/actions/workflows/publish.yml/badge.svg" alt="Publish"></a>
  <a href="https://pypi.org/project/slurmkit/"><img src="https://img.shields.io/pypi/v/slurmkit" alt="PyPI version"></a>
  <!-- <img src="https://img.shields.io/pypi/pyversions/slurmkit" alt="PyPI - Python Version"> -->
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
</p>

<p align="center">
  <a href="#installation">Install</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#features">Features</a> •
  <a href="https://awni00.github.io/slurmkit">Docs</a> •
  <a href="https://deepwiki.com/Awni00/slurmkit">DeepWiki</a>
</p>

---

<!-- # slurmkit -->

A CLI toolkit for managing and generating SLURM jobs.



`slurmkit` provides tools for:
- Auto-discovering and tracking SLURM job status
- Generating job scripts from templates with parameter sweeps
- Organizing jobs into trackable collections
- Cross-cluster job synchronization
- Cleaning up failed jobs and W&B runs

## Installation

### Install via pip

```bash
pip install slurmkit
```

### Install Latest from GitHub

```bash
pip install git+https://github.com/Awni00/slurmkit.git
# include all optional extras (ui + dev + docs)
pip install "slurmkit[all] @ git+https://github.com/Awni00/slurmkit.git"
```

### Clone and Install (Recommended for Development)

```bash
git clone https://github.com/Awni00/slurmkit.git
cd slurmkit
pip install -e ".[all]"
```

### Dependencies

**Required:**
- Python 3.8+
- PyYAML
- Jinja2
- pandas
- tabulate
- requests

**Optional:**
- wandb (for W&B cleanup features)
- rich (enhanced CLI UI; install with `pip install "slurmkit[ui]"`)
- `all` extra for optional groups (`ui`, `dev`, `docs`)

## Quick Start

### 1. Initialize Project

```bash
cd your-project
slurmkit init
```

This creates `.slurm-kit/config.yaml` with your settings.

### 2. Check Job Status

```bash
slurmkit status my_experiment
```

### 3. Generate Jobs from Template

Create a template `templates/train.job.j2`:

```jinja2
#!/bin/bash
#SBATCH --job-name={{ job_name }}
#SBATCH --partition={{ slurm.partition }}
#SBATCH --time={{ slurm.time }}
#SBATCH --output={{ logs_dir }}/{{ job_name }}.%j.out

python train.py --lr {{ learning_rate }} --bs {{ batch_size }}
```

Create a job spec `experiments/exp1/job_spec.yaml`:

```yaml
name: exp1
template: ../../templates/train.job.j2
output_dir: job_scripts
logs_dir: logs

parameters:
  mode: grid
  values:
    learning_rate: [0.001, 0.01, 0.1]
    batch_size: [32, 64]
  # Optional: exclude incompatible combinations
  filter:
    file: params_filter.py
    function: include_params

slurm_args:
  defaults:
    partition: gpu
    time: "24:00:00"

job_name_pattern: "lr{{ learning_rate }}_bs{{ batch_size }}"
```

Generate jobs:

```bash
slurmkit generate experiments/exp1/job_spec.yaml --collection exp1
```

### 4. Submit Jobs

```bash
# Preview before actual submission
slurmkit submit --collection exp1 --dry-run

# Submit to SLURM
slurmkit submit --collection exp1
```

### 5. Monitor and Resubmit

```bash
# Update job states
slurmkit collection update exp1

# View collection status
slurmkit collection show exp1

# View latest effective attempts with primary/history context
slurmkit collection show exp1 --show-primary --show-history

# Rich UI (if installed)
slurmkit --ui rich collection analyze exp1

# Resubmit failed jobs
slurmkit resubmit --collection exp1 --filter failed

# Group-aware retry
slurmkit resubmit --collection exp1 --filter failed --submission-group retry_after_fix
```

## Testing and Showcase Workflows

### A) Local Demo (No SLURM Required)

Use the bundled demo project for a deterministic feature showcase:

```bash
cd examples/demo_project
python -m venv .venv
source .venv/bin/activate
pip install -e ../..
./setup_dummy_jobs.py --include-non-terminal
```

Then run:

```bash
slurmkit collection list
slurmkit collection show demo_terminal_failed
slurmkit collection analyze demo_terminal_failed
# Optional richer formatting (requires rich extra):
slurmkit --ui rich collection analyze demo_terminal_failed
slurmkit notify test --dry-run
slurmkit notify collection-final --collection demo_terminal_failed --job-id 990002 --no-refresh --dry-run
```

### B) Real Cluster Workflow

```bash
slurmkit generate experiments/exp1/job_spec.yaml --collection exp1
slurmkit submit --collection exp1 --dry-run
slurmkit submit --collection exp1
slurmkit status exp1
slurmkit collection update exp1
slurmkit collection show exp1
slurmkit collection analyze exp1 --attempt-mode latest
slurmkit collection groups exp1
slurmkit resubmit --collection exp1 --filter failed --dry-run
```

### C) Feature Checklist

| Goal | Command | Success signal |
|------|---------|----------------|
| Initialize config | `slurmkit init` | `.slurm-kit/config.yaml` created |
| Generate scripts | `slurmkit generate ... --collection exp1` | Job scripts written and collection updated |
| Preview submission | `slurmkit submit --collection exp1 --dry-run` | Candidate jobs listed with no submit |
| Inspect collection | `slurmkit collection show exp1` | Summary + jobs table rendered |
| Analyze outcomes | `slurmkit collection analyze exp1` | Parameter tables and risky/stable sections shown |
| Validate notifications | `slurmkit notify test --dry-run` | Route resolution and payload preview |

## Commands

| Command | Description |
|---------|-------------|
| `slurmkit init` | Initialize project configuration |
| `slurmkit status <exp>` | Show job status for experiment |
| `slurmkit find <job_id>` | Find output file for job ID |
| `slurmkit generate <spec>` | Generate job scripts from template |
| `slurmkit submit` | Submit job scripts |
| `slurmkit resubmit` | Resubmit failed jobs |
| `slurmkit notify` | Send job lifecycle notifications |
| `slurmkit collection` | Manage job collections |
| `slurmkit clean outputs` | Clean failed job outputs |
| `slurmkit clean wandb` | Clean failed W&B runs |
| `slurmkit sync` | Sync job states for cross-cluster |

Run `slurmkit <command> --help` for detailed usage.

## Configuration

Configuration is stored in `.slurm-kit/config.yaml`:

```yaml
jobs_dir: jobs/
collections_dir: .job-collections/
sync_dir: .slurm-kit/sync/

output_patterns:
  - "{job_name}.{job_id}.out"
  - "{job_name}.{job_id}.*.out"
  - "slurm-{job_id}.out"

slurm_defaults:
  partition: gpu
  time: "24:00:00"
  mem: "32G"

job_structure:
  scripts_subdir: job_scripts/
  logs_subdir: logs/

ui:
  mode: plain  # plain | rich | auto

notifications:
  defaults:
    events: [job_failed]
    timeout_seconds: 5
    max_attempts: 3
    backoff_seconds: 0.5
    output_tail_lines: 40
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

### Environment Variables

| Variable | Description |
|----------|-------------|
| `SLURMKIT_CONFIG` | Path to config file |
| `SLURMKIT_JOBS_DIR` | Jobs directory |
| `SLURMKIT_COLLECTIONS_DIR` | Collections directory |
| `SLURMKIT_WANDB_ENTITY` | W&B entity |
| `SLURMKIT_DRY_RUN` | Enable dry-run mode |

## Documentation

Full documentation is available at [https://awni00.github.io/slurmkit/](https://awni00.github.io/slurmkit/)

- [Getting Started](docs/getting-started.md)
- [Configuration](docs/configuration.md)
- [Job Generation](docs/job-generation.md)
- [Collections](docs/collections.md)
- [Notifications](docs/notifications.md)
- [Cross-Cluster Sync](docs/sync.md)
- [CLI Reference](docs/cli-reference.md)

## Project Structure

```
your-project/
├── .slurm-kit/
│   ├── config.yaml          # Project configuration
│   └── sync/                 # Cross-cluster sync files
├── .job-collections/         # Collection YAML files
├── jobs/
│   └── experiment1/
│       ├── job_scripts/      # Generated job scripts
│       └── logs/             # Job output files
└── templates/                # Jinja2 job templates
```

## Features

Key features at a glance:

**1) Job Creation**

- Generate parameterized job scripts and attach them to a collection: `slurmkit generate job_spec.yaml --collection exp1`
- Preview generation and submission safely: `slurmkit generate ... --dry-run`, `slurmkit submit ... --dry-run`
- Submit only unsubmitted collection jobs (default): `slurmkit submit --collection exp1 --filter unsubmitted`

**2) Collection Tracking and Analysis**

- Create, inspect, and refresh collections: `slurmkit collection create exp1`, `slurmkit collection show exp1`, `slurmkit collection update exp1`
- Analyze outcomes by parameter values and latest attempts: `slurmkit collection analyze exp1 --attempt-mode latest --top-k 10`
- Inspect resubmission waves and attempt history: `slurmkit collection groups exp1`, `slurmkit collection show exp1 --show-history`
- Resubmit failed jobs with optional selection and parameter callbacks to programatically specify which jobs are submitted and whether to include additional parameters in resubmission (e.g., checkpoint dir): `slurmkit resubmit --collection exp1 --filter failed --select-file callbacks.py --extra-params-file extra.py`

**3) Notifications and Cross-Cluster Sync**

- Validate routes and send job notifications: `slurmkit notify test`, `slurmkit notify job ...`
- Send one final collection-level summary when a collection reaches terminal state: `slurmkit notify collection-final ...`
- Sync collection/job state across clusters via git-backed files: `slurmkit sync --push`

### Job Collections

Track related jobs together:

```bash
# Create collection
slurmkit collection create my_exp --description "Training sweep"

# List collections
slurmkit collection list

# Show details
slurmkit collection show my_exp --state failed
slurmkit collection show my_exp --attempt-mode latest --show-primary

# Update states from SLURM
slurmkit collection update my_exp

# Submission-group summary
slurmkit collection groups my_exp
```

### Notifications

Send job lifecycle notifications to Slack, Discord, email, or generic webhooks:

```bash
# Validate route setup
slurmkit notify test
slurmkit notify test --route team_email --dry-run

# Typical end-of-job call from script (default: notify only on failure)
slurmkit notify job --job-id "$SLURM_JOB_ID" --exit-code "$rc"

# Collection-final summary notification (emits only when collection is terminal)
slurmkit notify collection-final --job-id "$SLURM_JOB_ID"
```

Recommended trap snippet inside a job script:

```bash
rc=$?
slurmkit notify job --job-id "${SLURM_JOB_ID}" --exit-code "${rc}"
slurmkit notify collection-final --job-id "${SLURM_JOB_ID}"
exit "${rc}"
```

### Parameter Sweeps

Generate jobs from parameter grids:

```yaml
parameters:
  mode: grid
  values:
    learning_rate: [0.001, 0.01, 0.1]
    batch_size: [32, 64, 128]
    model: [resnet18, resnet50]
```

Or explicit lists:

```yaml
parameters:
  mode: list
  values:
    - {lr: 0.001, bs: 32}
    - {lr: 0.01, bs: 64}
```

### Dynamic SLURM Arguments

Use Python functions for complex resource logic:

```python
# slurm_logic.py
def get_slurm_args(params, defaults):
    args = defaults.copy()
    if params.get('model') == 'resnet50':
        args['mem'] = '64G'
        args['gpus'] = 2
    return args
```

### Cross-Cluster Sync

Share job status across clusters via git:

```bash
# On cluster A
slurmkit sync --push

# On cluster B
git pull
slurmkit collection show my_exp
```

## Development

### Setup

We recommend using [uv](https://github.com/astral-sh/uv) to manage the development environment.

```bash
# Clone the repository
git clone https://github.com/Awni00/slurmkit.git
cd slurmkit

# Create a virtual environment and install dependencies in editable mode
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

### Running Tests

```bash
pytest
```

## License

MIT License - see [LICENSE](LICENSE) for details.
