# CLI Reference

Complete reference for all slurmkit commands.

## Global Options

```bash
slurmkit [--config PATH] [--version] <command>
```

| Option | Description |
|--------|-------------|
| `--config PATH` | Path to config file (default: `.slurm-kit/config.yaml`) |
| `-V, --version` | Show version and exit |

## Commands

### slurmkit init

Initialize project configuration.

```bash
slurmkit init [--force]
```

| Option | Description |
|--------|-------------|
| `--force` | Overwrite existing configuration |

Interactive prompts for:
- Jobs directory
- Default SLURM partition, time, memory
- W&B entity (optional)
- Notification route setup (optional)

---

### slurmkit status

Show job status for an experiment or all jobs.

```bash
slurmkit status [experiment] [options]
```

| Argument | Description |
|----------|-------------|
| `experiment` | Optional: Experiment subdirectory name. If not specified, shows all jobs. |

| Option | Description |
|--------|-------------|
| `--jobs-dir PATH` | Override jobs directory |
| `--collection NAME` | Filter to jobs in collection |
| `--state STATE` | Filter by state: `all`, `running`, `pending`, `completed`, `failed` |
| `--format FORMAT` | Output format: `table`, `json`, `csv` |

**Examples:**

```bash
slurmkit status                   # Show all jobs
slurmkit status exp1              # Show jobs in exp1
slurmkit status exp1 --state failed
slurmkit status --format json
```

---

### slurmkit find

Find job output file by job ID.

```bash
slurmkit find <job_id> [options]
```

| Argument | Description |
|----------|-------------|
| `job_id` | SLURM job ID |

| Option | Description |
|--------|-------------|
| `--jobs-dir PATH` | Override jobs directory |
| `--preview` | Show preview of output file |
| `--lines N` | Lines to show in preview (default: 50) |
| `--open` | Open file in `$EDITOR` or pager |

**Examples:**

```bash
slurmkit find 12345678
slurmkit find 12345678 --preview --lines 100
slurmkit find 12345678 --open
```

---

### slurmkit clean outputs

Clean failed job output files.

```bash
slurmkit clean outputs <experiment> [options]
```

| Argument | Description |
|----------|-------------|
| `experiment` | Experiment subdirectory name |

| Option | Description |
|--------|-------------|
| `--jobs-dir PATH` | Override jobs directory |
| `--threshold SECONDS` | Max runtime to delete (default: 300) |
| `--min-age DAYS` | Min age to consider (default: 3) |
| `--dry-run` | Show what would be deleted |
| `-y, --yes` | Skip confirmation |

**Examples:**

```bash
slurmkit clean outputs exp1
slurmkit clean outputs exp1 --dry-run
slurmkit clean outputs exp1 --threshold 600 --min-age 7 -y
```

---

### slurmkit clean wandb

Clean failed W&B runs.

```bash
slurmkit clean wandb [options]
```

| Option | Description |
|--------|-------------|
| `--projects PROJ...` | W&B projects to clean |
| `--entity ENTITY` | W&B entity |
| `--threshold SECONDS` | Max runtime to delete (default: 300) |
| `--min-age DAYS` | Min age to consider (default: 3) |
| `--dry-run` | Show what would be deleted |
| `-y, --yes` | Skip confirmation |

**Examples:**

```bash
slurmkit clean wandb --projects my-project
slurmkit clean wandb --entity myteam --projects proj1 proj2 --dry-run
```

---

### slurmkit generate

Generate job scripts from template.

```bash
slurmkit generate <spec_file> [options]
slurmkit generate --template FILE --params FILE [options]
```

| Argument | Description |
|----------|-------------|
| `spec_file` | Job spec YAML file |

| Option | Description |
|--------|-------------|
| `--template FILE` | Template file (alternative to spec) |
| `--params FILE` | Parameters YAML file |
| `--output-dir DIR` | Output directory for scripts |
| `--collection NAME` | Add jobs to collection |
| `--slurm-args-file FILE` | Python file with SLURM args logic |
| `--dry-run` | Show preview without writing |

**Examples:**

```bash
slurmkit generate job_spec.yaml
slurmkit generate job_spec.yaml --collection my_exp
slurmkit generate job_spec.yaml --dry-run
slurmkit generate --template train.j2 --params params.yaml --output-dir scripts/
```

---

### slurmkit submit

Submit job scripts.

```bash
slurmkit submit [paths...] [options]
slurmkit submit --collection NAME [options]
```

| Argument | Description |
|----------|-------------|
| `paths` | Job script(s) or directory |

| Option | Description |
|--------|-------------|
| `--collection NAME` | Submit from or add to collection |
| `--filter FILTER` | For collection: `pending` or `all` |
| `--delay SECONDS` | Delay between submissions |
| `--dry-run` | Show what would be submitted |
| `-y, --yes` | Skip confirmation |

**Examples:**

```bash
slurmkit submit jobs/exp1/scripts/
slurmkit submit train_lr0.01.job train_lr0.1.job
slurmkit submit --collection my_exp
slurmkit submit --collection my_exp --filter all --delay 1
```

---

### slurmkit resubmit

Resubmit failed jobs.

```bash
slurmkit resubmit [job_ids...] [options]
slurmkit resubmit --collection NAME [options]
```

| Argument | Description |
|----------|-------------|
| `job_ids` | Job ID(s) to resubmit |

| Option | Description |
|--------|-------------|
| `--collection NAME` | Resubmit from collection |
| `--filter FILTER` | For collection: `failed` or `all` |
| `--template FILE` | Modified template for resubmission |
| `--extra-params K=V,...` | Extra template parameters |
| `--jobs-dir PATH` | Override jobs directory |
| `--dry-run` | Show what would be resubmitted |
| `-y, --yes` | Skip confirmation |

**Examples:**

```bash
slurmkit resubmit 12345678
slurmkit resubmit --collection my_exp --filter failed
slurmkit resubmit --collection my_exp --extra-params "checkpoint=last.pt"
```

---

### slurmkit collection

Manage job collections.

#### collection create

```bash
slurmkit collection create <name> [--description TEXT]
```

#### collection list

```bash
slurmkit collection list
```

#### collection show

```bash
slurmkit collection show <name> [--format FORMAT] [--state STATE]
```

| Option | Description |
|--------|-------------|
| `--format FORMAT` | Output: `table`, `json`, `yaml` |
| `--state STATE` | Filter: `all`, `pending`, `running`, `completed`, `failed` |

#### collection update

```bash
slurmkit collection update <name>
```

Refresh job states from SLURM.

#### collection analyze

```bash
slurmkit collection analyze <name> [options]
```

Analyze how job states vary across parameter values.

| Option | Description |
|--------|-------------|
| `--format FORMAT` | Output: `table`, `json` |
| `--no-refresh` | Skip SLURM refresh and analyze stored collection data |
| `--min-support N` | Minimum sample size for top risky/stable summaries (default: 3) |
| `--param KEY` | Analyze only selected parameter key(s); repeatable |
| `--attempt-mode MODE` | Use `primary` or `latest` attempt state (default: `primary`) |
| `--top-k N` | Number of rows in risky/stable summaries (default: 10) |

#### collection delete

```bash
slurmkit collection delete <name> [--keep-scripts] [--keep-outputs] [-y]
```

| Option | Description |
|--------|-------------|
| `--keep-scripts` | Don't delete script files |
| `--keep-outputs` | Don't delete output files |
| `-y, --yes` | Skip confirmation |

#### collection add

```bash
slurmkit collection add <name> <job_id> [job_id...]
```

#### collection remove

```bash
slurmkit collection remove <name> <job_id> [job_id...]
```

**Examples:**

```bash
slurmkit collection create my_exp --description "Training sweep"
slurmkit collection list
slurmkit collection show my_exp --state failed
slurmkit collection update my_exp
slurmkit collection analyze my_exp --min-support 5 --param algo --param learning_rate
slurmkit collection analyze my_exp --attempt-mode latest --format json
slurmkit collection delete my_exp --keep-outputs
slurmkit collection add my_exp 12345678 12345679
```

---

### slurmkit sync

Sync job states for cross-cluster tracking.

```bash
slurmkit sync [options]
```

| Option | Description |
|--------|-------------|
| `--collection NAME...` | Sync specific collections |
| `--output FILE` | Output file path |
| `--push` | Git commit and push sync file |

**Examples:**

```bash
slurmkit sync
slurmkit sync --collection exp1 exp2
slurmkit sync --push
```

---

### slurmkit notify

Send job and collection lifecycle notifications to configured webhook routes.

#### notify job

```bash
slurmkit notify job [options]
```

| Option | Description |
|--------|-------------|
| `--job-id JOB_ID` | SLURM job ID (defaults to `SLURM_JOB_ID`) |
| `--collection NAME` | Optional collection to narrow metadata lookup |
| `--exit-code N` | Exit code used to derive event (`0` => completed, nonzero => failed) |
| `--on MODE` | `failed` (default) or `always` |
| `--route NAME` | Route name filter (repeatable) |
| `--tail-lines N` | Override failure output tail line count |
| `--strict` | Require all attempted routes to succeed |
| `--dry-run` | Preview payload/routes without sending HTTP |

Examples:

```bash
slurmkit notify job --job-id 12345 --exit-code 1
slurmkit notify job --job-id 12345 --exit-code 0 --on always
slurmkit notify job --job-id 12345 --route team_slack --route custom_ops
slurmkit notify job --job-id 12345 --dry-run
```

#### notify test

```bash
slurmkit notify test [options]
```

| Option | Description |
|--------|-------------|
| `--route NAME` | Route name filter (repeatable) |
| `--strict` | Require all attempted routes to succeed |
| `--dry-run` | Preview payload/routes without sending HTTP |

Examples:

```bash
slurmkit notify test
slurmkit notify test --route team_slack
slurmkit notify test --dry-run
```

#### notify collection-final

```bash
slurmkit notify collection-final [options]
```

| Option | Description |
|--------|-------------|
| `--job-id JOB_ID` | Triggering SLURM job ID (defaults to `SLURM_JOB_ID`) |
| `--collection NAME` | Optional collection name (otherwise resolved by job ID) |
| `--route NAME` | Route name filter (repeatable) |
| `--strict` | Require all attempted routes to succeed |
| `--dry-run` | Preview payload/routes without sending HTTP |
| `--force` | Bypass deduplication for repeated terminal snapshots |
| `--no-refresh` | Skip SLURM refresh before finality check |

Examples:

```bash
slurmkit notify collection-final --job-id 12345
slurmkit notify collection-final --job-id 12345 --collection my_exp
slurmkit notify collection-final --job-id 12345 --route team_slack --strict
slurmkit notify collection-final --job-id 12345 --no-refresh --dry-run
```

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | File not found / ambiguous match |
| 130 | Interrupted (Ctrl+C) |
