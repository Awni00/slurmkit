## Plan

### Summary
- Change interactive collection picker ordering from name-alphabetical to `created_at` descending (newest first).
- Apply this consistently to all collection picker flows that use shared prompt helpers.
- Keep behavior resilient for legacy/corrupt metadata by treating missing/invalid timestamps as undated and placing them last.

### Implementation Changes
- Update `src/slurmkit/cli/prompts.py` to replace `_collection_options()` ordering logic.
- Add internal helper logic that:
  - starts from `manager.list_collections()` so all collections remain selectable,
  - reads each collection YAML safely to extract `created_at` without hard-failing on malformed metadata,
  - normalizes parseable timestamps and sorts by: dated first, timestamp descending, then collection name ascending.
- Keep `pick_collection`, `pick_collections`, and `pick_or_create_collection` using the same `_collection_options()` path.
- Preserve `pick_or_create_collection` sentinel behavior so `+ create new collection (...)` remains the first option.
- Keep public CLI interfaces unchanged (behavior-only change in interactive ordering).

### Test Plan
- Add focused tests in `tests/test_cli_prompts.py` for:
  - newest-first ordering for valid timestamps,
  - tie-break by name when timestamps match,
  - missing/invalid/corrupt metadata sorted last without crashes,
  - `pick_or_create_collection` sentinel retained at index 0.
- Run targeted validation: `PYTHONPATH=src pytest tests/test_cli_prompts.py tests/test_cli_app.py`.

### Assumptions
- Sort direction is newest-first.
- Scope includes all interactive collection picker helpers.
- Missing/invalid `created_at` values should appear at the bottom.
- Non-interactive outputs (for example `slurmkit collections list`) are out of scope.
