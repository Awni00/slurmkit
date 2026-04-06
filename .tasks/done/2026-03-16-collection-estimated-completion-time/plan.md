# Implementation plan

1. Add active queue timing helper in `src/slurmkit/slurm.py`.
- Implement `parse_slurm_duration_to_seconds(value)` for `%l` / `%L` parsing (`MM:SS`, `HH:MM:SS`, `D-HH:MM:SS`; unknown -> `None`).
- Implement `get_active_queue_timing(job_ids=None, user=None)` using `squeue --start --format=%i|%T|%S|%l|%L --noheader` and optional `-j` filter.
- Return machine-friendly values: `job_id`, `state_raw`, `estimated_start_at`, `time_limit_seconds`, `time_left_seconds`.

2. Enrich collection effective rows with ETA in `src/slurmkit/workflows/collections.py`.
- After `effective_jobs`/`effective_summary` are built, compute ETA for all active effective jobs (`pending`/`running`) ignoring row filter scope.
- ETA rules:
  - pending: require `estimated_start_at` + `time_limit_seconds`.
  - running: prefer `now + time_left_seconds`; fallback to `effective_started_at + time_limit_seconds`.
  - terminal/unsubmitted: ETA fields remain `None`.
- Attach per-row raw fields:
  - `effective_eta_start_at`
  - `effective_eta_completion_at`
  - `effective_eta_remaining_seconds`
- Compute collection aggregate:
  - `active_jobs`
  - `estimable_active_jobs`
  - `estimated_completion_at`
  - `estimated_remaining_seconds`
- Include aggregate in both compact status JSON (`payload["collection"]`) and full show JSON top-level; include row ETA fields in full jobs JSON rows.

3. Add UI/report support in `src/slurmkit/cli/ui/reports.py`.
- Add default column key `eta_completion` after `runtime`.
- Add renderer for `eta_completion` that formats `effective_eta_completion_at` as `YYYY-MM-DD HH:MM TZ (in ...)` with minute precision.
- Extend `build_collection_show_report(...)` to accept collection ETA aggregate inputs and append metadata line:
  - `Collection Est. Completion: ...` with coverage `(estimable/active estimable active jobs)`.

4. Wire report arguments in `src/slurmkit/workflows/collections.py`.
- Pass collection aggregate ETA fields into `build_collection_show_report(...)`.
- Reuse one `now` timestamp for deterministic calculations within the command execution.

5. Update defaults/docs.
- `src/slurmkit/config.py`: add `eta_completion` into default `ui.columns.collections_show` immediately after `runtime`.
- `docs/configuration.md` and `docs/getting-started.md`: mirror new default column snippet.

6. Add/adjust tests.
- `tests/test_slurm.py`: duration parser + queue timing parser tests including unknown tokens.
- `tests/test_workflows_collections.py`: ETA row enrichment and collection aggregate behavior.
- `tests/test_cli_ui.py`: new `eta_completion` column rendering and collection header metadata line (known and N/A with coverage).
- `tests/test_cli_app.py`: status text includes header line; status JSON has collection ETA keys; collections show JSON includes row ETA keys and collection aggregate keys.
- `tests/test_config.py`: default columns contain `eta_completion` immediately after `runtime`.

7. Verification and task lifecycle.
- Run targeted pytest for touched suites.
- Update task activity log as milestones complete.
- Complete dot-task when tests pass and changes are ready.
