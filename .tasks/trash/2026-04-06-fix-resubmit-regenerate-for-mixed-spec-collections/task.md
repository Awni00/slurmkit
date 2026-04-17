---
task_id: t-20260406-003
task_name: fix-resubmit-regenerate-for-mixed-spec-collections
status: todo
date_created: '2026-04-06'
date_started: null
date_completed: null
priority: p0
effort: l
spec_readiness: ready
depends_on:
- t-20260406-002
blocked_by: []
owner: null
tags:
- collections
- submission
---

## Summary
- Fix `slurmkit resubmit --regenerate` to use each job's source context (template, scripts dir, slurm logic/defaults), not one global collection context.

## Issue
- In mixed-spec collections, regenerate currently uses one collection-level generation context for all jobs.
- Older jobs from spec A can regenerate with spec B template and paths.

## Trigger
- Mixed-spec collection + `slurmkit resubmit <collection> --regenerate`.

## How To Replicate
1. `cd /tmp/slurmkit-repro-collection-clear-20260406-152627`
2. Ensure mixed collection exists (`demo_append`).
3. Run:
   - `slurmkit --config .slurmkit/config.yaml --nointeractive --ui plain resubmit demo_append --filter unknown --regenerate --yes`
4. Inspect:
   - `.jobs/repro/exp_b/job_scripts/a_lr0.01.resubmit-1.job`
   - The script incorrectly uses template B output (`echo "B "`).

## Hand-off Artifacts
- `/tmp/slurmkit-repro-collection-clear-20260406-152627/resubmit_cross_spec_demo.txt`
- `/tmp/slurmkit-repro-collection-clear-20260406-152627/.jobs/repro/exp_b/job_scripts/a_lr0.01.resubmit-1.job`

## Scope
- Resolve source metadata per job during resubmit planning.
- Group/route regenerated script writes by source scripts dir.
- Ensure template and slurm args logic are source-correct for each job.

## Testing
- End-to-end mixed-spec resubmit test verifying per-job source template usage.
- Ensure single-spec behavior remains unchanged.

## Acceptance Criteria
- Regenerated scripts for spec A jobs are rendered with spec A source context.
- No cross-source template/path leakage in mixed collections.
