## Plan
TODO: Write complete plan generated during plan mode verbosely here.
# Support Safe Hierarchical Collection IDs

## Summary
- Implement canonical collection IDs as slash-separated safe identifiers stored under `.slurmkit/collections/` as nested YAML paths, with strict validation everywhere.
- Compatibility policy is strict: unsafe legacy names are unsupported for new and existing access paths in CLI/API usage.

## Key Changes
- Centralize collection ID validation and path resolution in `src/slurmkit/collections.py`.
- Update `CollectionManager` save/load/delete/list/exists/create/get_or_create/resolve_job_id` to use canonical nested paths, recursive listing, parent-dir creation, and empty-parent pruning.
- Update CLI prompt helpers and all collection-facing command paths so they resolve collection IDs through the manager instead of reconstructing flat filenames.
- Update docs/examples/tests to replace unsafe collection names with safe IDs and add hierarchical-ID coverage.

## Public Interface Changes
- Collection IDs are now canonical slash-separated safe IDs with segments matching `[A-Za-z0-9._-]+`.
- Rejected forms include spaces, `.`/`..`, backslashes, empty segments, leading/trailing slash, and absolute/escaping paths.
- `slurmkit collections list` returns nested collection IDs with `/` separators.

## Test Plan
- Add manager tests for nested save/load, recursive listing, parent creation, delete pruning, invalid IDs, and escape rejection.
- Add workflow/CLI-facing tests for `generate`, `status`, `show`, `submit`, and `resubmit` with hierarchical IDs.
- Update slug-templating tests to use a safe hierarchical ID and verify `collection_slug` remains predictable.

## Assumptions
- No compatibility layer for unsafe historical IDs.
- No silent normalization besides canonical POSIX `/` handling; invalid input is rejected.
- Stored YAML `name` remains the canonical slash-separated collection ID.
