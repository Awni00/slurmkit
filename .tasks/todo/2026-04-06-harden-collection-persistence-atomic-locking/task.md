---
task_id: t-20260406-005
task_name: harden-collection-persistence-atomic-locking
status: todo
date_created: '2026-04-06'
date_started: null
date_completed: null
priority: p0
effort: l
spec_readiness: ready
depends_on: []
blocked_by: []
owner: null
tags:
- collections
- reliability
---

## Summary
- Make collection persistence robust under concurrency/interruption using atomic writes and lock discipline.

## Issue
- Current collection save uses truncate-and-write (`open(..., "w")`) with no general collection lock.
- Concurrent writers can expose transient empty files and produce persistent YAML corruption.

## Triggers
- Parallel runs of commands that write collections (`generate`, `status`, `collections show/analyze/refresh`, etc.).
- Process interruption during write window.

## How To Replicate
1. `cd /tmp/slurmkit-repro-collection-clear-20260406-152627`
2. Run stress probe:
   - `bash race_probe.sh`
3. Check outputs:
   - `race_monitor_*.log` often show `0` byte samples.
   - Some runs produce parse failures (`parse_ok=0`).

## Hand-off Artifacts
- `/tmp/slurmkit-repro-collection-clear-20260406-152627/race_probe.sh`
- `/tmp/slurmkit-repro-collection-clear-20260406-152627/race_monitor_race_demo_20260406_153342.log`
- `/tmp/slurmkit-repro-collection-clear-20260406-152627/.slurmkit/collections/race_demo_20260406_153342.yaml`
- `/tmp/slurmkit-repro-collection-clear-20260406-152627/ANALYSIS_SUMMARY.md`

## Scope
- Atomic write pattern: write temp file in same directory, fsync, `os.replace`.
- Use locking around read-modify-write sequences for collection files.
- Reuse existing lock conventions where practical.
- Ensure lock coverage for commands that refresh+save.

## Testing
- Concurrency stress test for repeated writers.
- Interruption/failure simulation during save.
- Verify no partial/corrupt YAML and no persistent empty file post-write.

## Acceptance Criteria
- No reproducible persistent corruption under race probe.
- Save path is atomic and lock-protected.
- Existing command behavior remains functionally intact.
