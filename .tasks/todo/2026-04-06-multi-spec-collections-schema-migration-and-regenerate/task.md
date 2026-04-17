---
task_id: t-20260406-002
task_name: multi-spec-collections-schema-migration-and-regenerate
status: todo
date_created: '2026-04-06'
date_started: null
date_completed: null
priority: p0
effort: xl
spec_readiness: ready
depends_on: []
blocked_by: []
owner: null
tags:
- collections
- generate
- migration
- schema
- submission
---

## Summary
- Design and implement schema v3 for mixed-spec collections, including explicit migration from v2.
- Fix `slurmkit resubmit --regenerate` so each job uses its own source context instead of one collection-wide context.
- Loading or saving v2 collections in normal commands must fail with a clear message to run `slurmkit migrate`.

## Issue
- Current behavior supports append-only jobs but not native multi-spec provenance.
- Collection-level metadata is overwritten by the latest spec, which produces semantic drift and downstream bugs.
- `resubmit --regenerate` can render older jobs with the wrong template, scripts dir, and slurm defaults in mixed-spec collections.

## Triggers
- Any `generate` into existing collection from a different spec.
- Any command loading legacy v2 collection after v3 introduction.
- Mixed-spec collection + `slurmkit resubmit <collection> --regenerate`.

## How To Replicate
1. Baseline mixed-spec append in repro workspace:
   - `cd /tmp/slurmkit-repro-collection-clear-20260406-152627`
   - `slurmkit --config .slurmkit/config.yaml --nointeractive --ui plain generate spec_a.yaml --into demo_append`
   - `slurmkit --config .slurmkit/config.yaml --nointeractive --ui plain generate spec_b.yaml --into demo_append`
2. Confirm legacy overwrite behavior via snapshots and JSON show output.

## Hand-off Artifacts
- `/tmp/slurmkit-repro-collection-clear-20260406-152627/snapshots/01_generate_a.yaml`
- `/tmp/slurmkit-repro-collection-clear-20260406-152627/snapshots/02_generate_b.yaml`
- `/tmp/slurmkit-repro-collection-clear-20260406-152627/repro.log`
- `/tmp/slurmkit-repro-collection-clear-20260406-152627/resubmit_cross_spec_demo.txt`
- `/tmp/slurmkit-repro-collection-clear-20260406-152627/.jobs/repro/exp_b/job_scripts/a_lr0.01.resubmit-1.job`

## Implementation Scope
- Finalize a simple, minimal v3 schema with per-source metadata only and deterministic job-to-source links.
- Add v3 serialization/deserialization model in collections layer.
- Update generate workflow to append source records and link each job to source ID.
- Update any readers that currently consume top-level `generation`.
- Resolve source metadata per job during resubmit planning.
- Route regenerated script writes by the correct source scripts dir and template context.
- Add explicit migration in `slurmkit migrate` from v2 -> v3.
- Reject v2 at load-time for normal workflows with actionable error:
  - "Collection schema version 2 is unsupported. Run `slurmkit migrate`."

## Deliverables
- v3 schema contract with concrete single-source and multi-source examples.
- Clear field-level mapping from v2 -> v3 and migration invariants.
- Implementation updates for generate, load, migrate, and resubmit-regenerate flows.
- Tests covering mixed-spec append, migration, invalid legacy access, and source-correct regeneration.

## Testing
- Unit tests for v3 model and round-trip.
- Migration tests v2 -> v3 with backups.
- CLI tests for failure message on v2 before migration.
- End-to-end test for multi-spec append preserving per-source provenance.
- End-to-end mixed-spec resubmit test verifying per-job source template usage.

## Acceptance Criteria
- Mixed-spec generate persists clean per-source metadata with stable job-source links.
- v2 collections trigger explicit migrate error in non-migrate commands.
- `slurmkit migrate` converts representative v2 files to valid v3.
- Regenerated scripts for jobs from spec A use spec A source context, with no cross-source template/path leakage.
