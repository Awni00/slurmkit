---
name: slurmkit
description: "Guide for AI agents working with slurmkit projects, including project structure, command workflows, spec authoring, collection analysis, failure triage, resubmission strategy, notifications, migration, sync, and cleanup."
---

# slurmkit Skill

Use this skill when working in repositories that manage SLURM experiments with `slurmkit`.

## Overview

`slurmkit` organizes experiment operations around this model:

- `job spec` + `template` define job generation.
- `collection` is the tracked unit of work.
- each collection job keeps an `attempts` history.
- operational loop is `generate -> submit -> status/show -> analyze -> resubmit`.

The canonical local state lives under `.slurmkit/` and generated job assets under `.jobs/`.

## Canonical Project Structure

A strong default for research repos:

```text
project/
├── core/                              # shared library code
├── experiments/
│   ├── <experiment_name>/
│   │   ├── run_experiment.py          # main experiment entrypoint
│   │   └── slurmkit/
│   │       ├── job_spec.yaml
│   │       ├── training.job.j2
│   │       ├── params_logic.py        # optional parse/filter hooks
│   │       └── slurm_logic.py         # optional dynamic SLURM args
├── .slurmkit/
│   ├── config.yaml
│   ├── collections/
│   ├── sync/
│   └── locks/
└── .jobs/
    └── <job_subdir>/
        ├── job_scripts/
        └── logs/
```

Placement default when no pattern exists yet:

- `experiments/{experiment_name}/slurmkit/job_spec.yaml`
- `experiments/{experiment_name}/slurmkit/<template>.job.j2`
- `job_subdir` in spec should match experiment intent, e.g. `experiments/{experiment_name}`.

## Command Cheat Sheet (By Goal)

- initialize project: `slurmkit init`
- inspect configuration: `slurmkit config show`
- scaffold starter spec: `slurmkit job-template` (equivalent workflow on current CLI: `slurmkit spec-template`)
- generate jobs into collection: `slurmkit generate <spec> --into <collection>`
- preview generation: `slurmkit generate <spec> --into <collection> --dry-run`
- submit: `slurmkit submit <collection>`
- preview submit: `slurmkit submit <collection> --dry-run`
- compact live status: `slurmkit status <collection>`
- detailed status: `slurmkit collections show <collection>`
- parameter outcome analysis: `slurmkit collections analyze <collection>`
- refresh collection states: `slurmkit collections refresh <collection>`
- retry failed jobs: `slurmkit resubmit <collection> --filter failed`
- cancel active jobs: `slurmkit collections cancel <collection> --dry-run`
- notification route test: `slurmkit notify test --dry-run`
- migration: `slurmkit migrate`
- cross-host sync snapshot: `slurmkit sync`
- cleanup failed outputs: `slurmkit clean outputs <collection> --dry-run`
- cleanup short failed W&B runs: `slurmkit clean wandb --project <name> --dry-run`

## References (Mini Examples)

- `references/mini_job_spec.yaml`: compact, copyable spec with `grid` parameters and optional callback hooks.
- `references/mini_template.job.j2`: minimal SLURM job template with core variables.
- `references/mini_params_logic.py`: parse/filter callback examples.
- `references/mini_slurm_logic.py`: dynamic SLURM resource callback example.

Start from these references when bootstrapping a new experiment; adapt paths and parameters rather than writing from scratch.

## Guardrails (Concise)

- Always run a dry run before mutating steps (`generate`, `submit`, `resubmit`, cleanup).
- Keep spec parameters explicit; do not hide major defaults in templates/scripts.
- In `grid` sweeps, ensure `job_name_pattern` includes every parameter with multiple values.
- Ensure every parameter in the spec is implemented by the template (or handled by callbacks).
- Use `collections show` or `status` before `resubmit` to verify true failure state.
- Prefer targeted retries (`--select-file`, `--extra-params`) over broad resubmits.
- Treat deletions as irreversible; verify thresholds and collection target first.

## Workflow Playbooks

### 1) Bootstrap and Structure Audit

1. Confirm repo root and check for `.slurmkit/config.yaml`.
2. If missing, run `slurmkit init` and inspect `slurmkit config show`.
3. Validate experiment layout: each experiment should have a dedicated `slurmkit/` subdir with spec/template.
4. Validate `job_subdir` is meaningful and stable (affects `.jobs/` paths and output lookup).

### 2) Spec Authoring From Experiment Scripts

1. Read the experiment entry script (`run_experiment.py`, `train.py`, etc.) first.
2. Enumerate all relevant CLI args and defaults explicitly.
3. Prefer explicit parameter blocks over hidden defaults.
4. Choose parameter mode:
   - `grid` for Cartesian sweeps.
   - `list` for curated combinations.
5. If needed, add `parse` hook for derived fields and `filter` hook for invalid combinations.
6. Keep parameters grouped by logical concern (model, data, optimization, runtime).
7. Ensure `job_name_pattern` includes at least all sweep dimensions (parameters with multiple grid values).

### 3) Sweep Design (`grid` / `list`, parse/filter)

- In `grid` mode, document sweep dimensions at the top of your notes.
- Keep sweep cardinality visible and estimate total jobs before generation.
- Use `filter` for incompatibilities; avoid encoding invalid pairs in template logic.
- Use `parse` when one param row should expand into multiple jobs (e.g., seeds).

### 4) Generation Validation (`--dry-run`, naming, collisions)

1. Run `slurmkit generate ... --dry-run` first.
2. Check rendered preview for command correctness and SLURM directives.
3. Ensure `job_name_pattern` produces readable, unique names.
4. If appending to existing collection, account for name collision suffixes (`-2`, `-3`, ...).
5. Run real generation only after preview is clean.

### 5) Submit / Monitor Loop

1. `slurmkit submit <collection> --dry-run`
2. `slurmkit submit <collection>`
3. `slurmkit status <collection>` for live compact view.
4. `slurmkit collections show <collection>` for detailed attempts/history.
5. `slurmkit collections refresh <collection>` when explicit sync from SLURM is needed.

### 6) Failure Analysis and Taxonomy Report

1. Start from collection state: `status`, `collections show`, and optionally `collections analyze`.
2. Gather failed job ids and output paths from latest failed attempts.
3. Inspect logs for each failed job; classify failures into categories.
4. Produce a concise report with:
   - failure categories with counts
   - root cause hypothesis per category
   - concrete code/spec/config bugs found
   - immediate fixes vs follow-up actions

Suggested categories:
- resource mismatch (OOM, timeout, wrong partition)
- environment/dependency failures
- data/input/path errors
- deterministic code exceptions
- transient cluster/scheduler issues
- mis-specified sweep/argument wiring

### 7) Resubmission Strategy

- default: `slurmkit resubmit <collection> --filter failed`
- use regeneration when template/logic changed.
- use `--no-regenerate` when scripts are already correct and only resubmit is needed.
- use `--extra-params`/`--extra-params-file` for targeted overrides.
- use `--select-file` to limit retries to a subset.
- use `--submission-group` to label retry campaigns.

### 8) Outcome Analysis (`collections analyze`)

1. Run `slurmkit collections analyze <collection>`.
2. Focus on high-support risky/stable parameter values.
3. Convert findings into next sweep edits:
   - prune low-value regions
   - increase trials in promising regions
   - split experiments by dominant risk factor

### 9) Notification Routing and Debug

1. Validate configuration with `slurmkit notify test --dry-run`.
2. Test specific route with `--route <name>`.
3. Validate job notifications from known IDs: `notify job ... --dry-run`.
4. Validate final collection report behavior: `notify collection-final ... --dry-run`.
5. If collections have `spec.yaml` notification overrides, verify precedence against global config.

### 10) Migration and Sync Troubleshooting

- run `slurmkit migrate` for legacy layouts (`.slurm-kit`, `.job-collections`, old spec keys).
- run `slurmkit sync` to write per-host status snapshots.
- use `slurmkit sync --push` only when repo git workflow permits writing/pushing from that environment.

### 11) Cleanup Workflows

- preview file cleanup first: `slurmkit clean outputs <collection> --dry-run`
- confirm thresholds (`--threshold`, `--min-age`) before deletion
- for W&B cleanup, always start with `--dry-run` and explicit `--project`

## Operating Guidance for Agents

- Prefer explicit commands/arguments over implicit interactive flows when reproducibility matters.
- Always dry-run before mutating submission or cleanup operations.
- Keep reports concise and decision-oriented: what failed, why, and what to change next.
- Treat collection metadata as source of truth for experiment state.
