# CLI Reference

## Global usage

```bash
slurmkit [--config PATH] [--ui plain|rich|auto] [--nointeractive] <command>
```

| Option | Description |
|---|---|
| `--config PATH` | Use a specific config file |
| `--ui plain|rich|auto` | Override UI mode |
| `--nointeractive` | Disable prompt fallback |
| `--version` | Show version |

Running `slurmkit` with no command opens the interactive command picker on interactive terminals.

## Top-level commands

### `slurmkit init`

Create `.slurmkit/config.yaml`.

```bash
slurmkit init [--force]
```

### `slurmkit install-skill`

Install the slurmkit Codex skill via `npx skills`.

```bash
slurmkit install-skill [--nointeractive] [--yes]
```

Example:

```bash
slurmkit install-skill --yes
```

### `slurmkit migrate`

Rewrite old local state into the current layout.

```bash
slurmkit migrate
```

Migrates:

- `.slurm-kit/` -> `.slurmkit/`
- `.job-collections/` -> `.slurmkit/collections/`
- old spec `output_dir` / `logs_dir` -> `job_subdir`

### `slurmkit generate`

Generate job scripts from a spec and bind them to a collection.

```bash
slurmkit generate [SPEC] [--into COLLECTION] [--dry-run]
```

Examples:

```bash
slurmkit generate experiments/exp1/slurmkit/job_spec.yaml --into exp1
slurmkit generate experiments/exp1/slurmkit/job_spec.yaml --into exp1 --dry-run
```

### `slurmkit spec-template`

Write a starter `job_spec.yaml` scaffold.

```bash
slurmkit spec-template [--output PATH] [--force]
```

Examples:

```bash
slurmkit spec-template
slurmkit spec-template --output experiments/exp1/slurmkit/job_spec.yaml
slurmkit spec-template --force
```

### `slurmkit submit`

Submit jobs from a collection.

```bash
slurmkit submit [COLLECTION] [--filter unsubmitted|all] [--delay SECONDS] [--dry-run] [-y]
```

Examples:

```bash
slurmkit submit exp1 --dry-run
slurmkit submit exp1 --filter all --delay 1
```

### `slurmkit resubmit`

Retry jobs from a collection.

```bash
slurmkit resubmit [COLLECTION] [--filter failed|all] [--dry-run] [-y]
```

Advanced regeneration controls are also available:

- `--template`
- `--extra-params`
- `--extra-params-file`
- `--extra-params-function`
- `--select-file`
- `--select-function`
- `--submission-group`
- `--regenerate / --no-regenerate`

Examples:

```bash
slurmkit resubmit exp1 --filter failed --dry-run
slurmkit resubmit exp1 --filter failed --submission-group retry_after_fix
```

### `slurmkit status`

Show the compact live status view for one collection.

```bash
slurmkit status [COLLECTION] [--state all|running|pending|completed|failed] [--json]
```

## `collections` commands

```bash
slurmkit collections <command>
```

Available commands:

- `list`
- `show`
- `analyze`
- `refresh`
- `cancel`
- `delete`

Examples:

```bash
slurmkit collections list
slurmkit collections show exp1
slurmkit collections analyze exp1 --param learning_rate --param batch_size
slurmkit collections refresh exp1
slurmkit collections refresh --all
slurmkit collections cancel exp1 --dry-run
slurmkit collections delete exp1 -y
```

Structured output is JSON-only where supported:

```bash
slurmkit collections show exp1 --json
slurmkit collections analyze exp1 --json
slurmkit status exp1 --json
```

## `notify` commands

```bash
slurmkit notify <command>
```

Available commands:

- `test`
- `job`
- `collection-final`

Examples:

```bash
slurmkit notify test --dry-run
slurmkit notify test --route team_slack --dry-run

slurmkit notify job --job-id 123456 --exit-code 1 --dry-run
slurmkit notify job --collection exp1 --job-id 123456 --exit-code 1 --route team_slack --dry-run

slurmkit notify collection-final --collection exp1 --job-id 123456 --dry-run
slurmkit notify collection-final --collection exp1 --job-id 123456 --force --dry-run
```

## `sync`

Write the per-host sync snapshot, optionally for one collection.

```bash
slurmkit sync [--collection NAME] [--push]
```

## `clean` commands

```bash
slurmkit clean outputs [COLLECTION] [--threshold SECONDS] [--min-age DAYS] [--dry-run] [-y]
slurmkit clean wandb [--project NAME] [--entity NAME] [--threshold SECONDS] [--min-age DAYS] [--dry-run] [-y]
```

## `config`

```bash
slurmkit config show
slurmkit config edit
slurmkit config wizard
```

## `home`

Open the interactive command picker explicitly:

```bash
slurmkit home
```
