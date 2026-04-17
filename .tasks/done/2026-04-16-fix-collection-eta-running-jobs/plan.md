# Fix Collection ETA for Running Jobs

## Summary
- Root cause is confirmed in `src/slurmkit/slurm.py`: `get_active_queue_timing()` still uses `squeue --start`, which implicitly filters output to `PENDING` jobs, so `RUNNING` rows never reach the ETA aggregation in `src/slurmkit/workflows/collections.py`.
- Leave the consumer and renderer unchanged. The per-state ETA math in `show_collection()` and the `"Collection Est. Completion"` formatting already match the intended behavior.
- No public API or schema changes. Existing JSON/report fields should simply start being populated for running jobs.

## Implementation Changes
- In `get_active_queue_timing()` in `src/slurmkit/slurm.py`, replace the `squeue` command with:
  - `squeue --states=PENDING,RUNNING --format=%i|%T|%S|%l|%L --noheader`
- Keep the existing `-j`, `-u`, and `--me` selection logic unchanged.
- Update the docstring so it describes querying active queue timing for pending/running jobs via `--states=PENDING,RUNNING` and no longer mentions `--start`.
- Add focused regression coverage in `tests/test_slurm.py`:
  - running job parses with `time_left_seconds == 40143`, `time_limit_seconds == 86400`, `state_raw == "RUNNING"`, and the expected ISO start time
  - pending job with backfill data still parses correctly
  - pending job with `N/A` / `UNLIMITED` yields `None` fields
  - mixed running + pending output returns both jobs in the timing map
  - captured command includes `--states=PENDING,RUNNING` and excludes `--start`
- Add one workflow-level regression in `tests/test_workflows_collections.py` because a harness already exists:
  - a running-only collection with mocked timing should produce non-null `estimated_completion_at`, `estimable_active_jobs == 1`, and `active_jobs == 1`

## Test Plan
- Run `pytest tests/test_slurm.py tests/test_workflows_collections.py`.
- Verify the new tests use the exact fixture lines from the bug report, including the running-job example that would have exposed the current bug.
- If cluster access is available after implementation, do the manual check in the target project by reinstalling this checkout and verifying:
  - `slurmkit status synthetic-pretrained-disentangled-from-entangled-v3`
  - `slurmkit collections show synthetic-pretrained-disentangled-from-entangled-v3 --json`
- If cluster access is not available, report that end-to-end validation remains pending and hand back the passing unit-test evidence.

## Assumptions
- The repo layout is `src/slurmkit/...`, so the user’s top-level file references map to those paths here.
- The new `dot-tasks` item should be created as:
  - task name: `fix-collection-eta-running-jobs`
  - summary: `Fix active queue timing so running jobs contribute to collection ETA in status/show output.`
  - priority: `p1`
  - effort: `m`
  - tags: `status`, `collections`
- Because this thread is still in Plan Mode, I have not mutated `.tasks/`. The first execution step should be `dot-tasks create`, then `dot-tasks start`, then writing this full plan into the new task’s `plan.md`.
