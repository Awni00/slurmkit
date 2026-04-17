---
task_id: t-20260416-004
task_name: collection-picker-last-updated-indicator
status: completed
date_created: '2026-04-16'
date_started: '2026-04-16'
date_completed: '2026-04-16'
priority: p1
effort: m
spec_readiness: unspecified
depends_on: []
blocked_by: []
owner: null
tags:
- cli
- collections
---

## Summary
- Add last-updated recency labels and updated_at-based ordering to shared interactive collection pickers.

## Acceptance Criteria
- Interactive collection pickers sort collections by valid `updated_at` descending, with name ascending as the tie-break.
- Collections with missing, invalid, or corrupt `updated_at` remain selectable, display `unknown`, and sort after dated collections.
- Picker labels show compact relative freshness text like `2h ago`, with future timestamps clamped to `0m ago`.
- `pick_or_create_collection` keeps the create-new sentinel as the first option.
- Prompt helper tests cover ordering, unknown timestamps, label formatting, and timestamp parsing fallbacks.
