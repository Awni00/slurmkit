# Task: Collection Show Effective Latest

## Goal
Make `collection show` default to effective/latest attempt semantics while preserving optional primary provenance.

## Scope
- Add `--attempt-mode {primary,latest}` with default `latest`.
- Add `--submission-group NAME` filter for show.
- Add `--show-primary` and `--show-history` options.
- Use effective attempt data for default `Job ID` and `State` columns.
- Keep JSON/YAML output backward-compatible and additive via `effective_*` fields.

## Acceptance Criteria
- `collection show` defaults to latest attempt values.
- `--state` filtering applies to effective state.
- `--show-primary` and `--show-history` render extra table columns.
