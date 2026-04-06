---
task_id: t-20260406-001
task_name: design-multi-spec-collection-schema-v3
status: todo
date_created: '2026-04-06'
date_started: null
date_completed: null
priority: p0
effort: l
spec_readiness: ready
depends_on: []
blocked_by:
- t-20260406-002
owner: null
tags:
- collections
- schema
---

## Summary
- Design a simple, minimal v3 collection schema that supports collections generated from multiple specs.
- v3 must store only per-source metadata (no single top-level `generation` summary).
- v2 compatibility policy: do not silently read/write as v2; fail with actionable error instructing user to run `slurmkit migrate`.

## Issue
- Current schema has one top-level `generation` block and one top-level `parameters` block.
- When a second spec is generated into an existing collection, jobs append but collection-level metadata is overwritten by the latest spec.
- This causes ambiguous provenance and incorrect behavior for regenerate flows.

## Triggers
- `slurmkit generate <spec_a> --into <collection>` then `slurmkit generate <spec_b> --into <collection>`.
- Any later logic that assumes one global generation context for all jobs.

## How To Replicate
1. Use repro workspace:
   - `cd /tmp/slurmkit-repro-collection-clear-20260406-152627`
2. Compare snapshots:
   - `snapshots/01_generate_a.yaml`
   - `snapshots/02_generate_b.yaml`
3. Observe jobs append while collection-level generation context changes from `spec_a` to `spec_b`.

## Hand-off Artifacts
- `/tmp/slurmkit-repro-collection-clear-20260406-152627/ANALYSIS_SUMMARY.md`
- `/tmp/slurmkit-repro-collection-clear-20260406-152627/README_REPRO.md`
- `/tmp/slurmkit-repro-collection-clear-20260406-152627/snapshots/01_generate_a.yaml`
- `/tmp/slurmkit-repro-collection-clear-20260406-152627/snapshots/02_generate_b.yaml`

## Design Constraints
- Keep schema minimal and consistent.
- Per-source metadata only.
- Every job must map to a source deterministically.
- Preserve safety and migration clarity over cleverness.

## Deliverables
- v3 schema proposal with example YAML.
- Clear field-level mapping from v2 -> v3.
- Explicit migration invariants and failure behavior.
- Test plan covering normal, mixed-spec, and invalid states.

## Acceptance Criteria
- Schema doc is explicit enough to implement without ambiguity.
- Includes concrete examples for single-source and multi-source collections.
- Includes migration contract and error messaging for v2 access before migration.
