---
task_id: t-20260406-002
task_name: implement-multi-spec-schema-and-migrate
status: todo
date_created: '2026-04-06'
date_started: null
date_completed: null
priority: p0
effort: xl
spec_readiness: ready
depends_on:
- t-20260406-001
blocked_by:
- t-20260406-003
owner: null
tags:
- collections
- generate
- migration
---

## Summary
- Implement schema v3 and explicit migration workflow.
- Loading or saving v2 collections in normal commands must fail with a clear message to run `slurmkit migrate`.

## Issue
- Current behavior supports append-only jobs but not native multi-spec provenance.
- Metadata overwrites produce semantic drift and downstream bugs.

## Triggers
- Any `generate` into existing collection from a different spec.
- Any command loading legacy v2 collection after v3 introduction.

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

## Implementation Scope
- Add v3 serialization/deserialization model in collections layer.
- Update generate workflow to append source records and link each job to source ID.
- Update any readers that currently consume top-level `generation`.
- Add explicit migration in `slurmkit migrate` from v2 -> v3.
- Reject v2 at load-time for normal workflows with actionable error:
  - "Collection schema version 2 is unsupported. Run `slurmkit migrate`."

## Testing
- Unit tests for v3 model and round-trip.
- Migration tests v2 -> v3 with backups.
- CLI tests for failure message on v2 before migration.
- End-to-end test for multi-spec append preserving per-source provenance.

## Acceptance Criteria
- Mixed-spec generate persists clean per-source metadata with stable job-source links.
- v2 collections trigger explicit migrate error in non-migrate commands.
- `slurmkit migrate` converts representative v2 files to valid v3.
