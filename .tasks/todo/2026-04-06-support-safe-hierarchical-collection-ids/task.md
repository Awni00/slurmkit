---
task_id: t-20260406-004
task_name: support-safe-hierarchical-collection-ids
status: todo
date_created: '2026-04-06'
date_started: null
date_completed: null
priority: p1
effort: l
spec_readiness: ready
depends_on: []
blocked_by: []
owner: null
tags:
- cli
- collections
---

## Summary
- Support slash-separated collection IDs (for example `experiment/group/run_20260406`) as true hierarchy under `.slurmkit/collections/`.
- Enforce strict path safety and simple identifier rules.

## Rules
- Allowed segment charset: `[A-Za-z0-9._-]` only.
- Segment separators: `/`.
- Disallow: spaces, empty segments, `.`/`..`, absolute paths, backslashes.

## Issue
- Current path logic does not safely support hierarchy and permits path escape behavior.
- `--into experiment/group/name` currently fails due to missing parent directories.
- `--into ../escape_collection` can escape collections dir.

## How To Replicate
1. `cd /tmp/slurmkit-repro-collection-clear-20260406-152627`
2. Hierarchy failure:
   - `slurmkit --config .slurmkit/config.yaml --nointeractive --ui plain generate spec_a.yaml --into experiment/group/name`
3. Escape behavior:
   - `slurmkit --config .slurmkit/config.yaml --nointeractive --ui plain generate spec_a.yaml --into ../escape_collection`
4. Observe:
   - `.slurmkit/escape_collection.yaml` created outside collections subdir.

## Hand-off Artifacts
- `/tmp/slurmkit-repro-collection-clear-20260406-152627/README_REPRO.md`
- `/tmp/slurmkit-repro-collection-clear-20260406-152627/.slurmkit/escape_collection.yaml`

## Scope
- Path normalization/validation utility for collection IDs.
- Save/load/delete/list support for nested paths.
- Recursive listing returns canonical IDs with `/` separators.
- Parent dir creation on save.
- Hard guarantee that resolved path stays within collections root.

## Testing
- Valid IDs with nested segments.
- Invalid IDs rejected with actionable errors.
- Escape attempts rejected.
- `collections list` includes nested collections as full IDs.

## Acceptance Criteria
- Hierarchical IDs work end-to-end.
- Escape and invalid names are blocked.
- Behavior remains simple and predictable.
