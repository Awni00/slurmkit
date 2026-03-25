---
task_id: t-20260323-002
task_name: sort-collections-by-date-created
status: completed
date_created: '2026-03-23'
date_started: '2026-03-25'
date_completed: '2026-03-25'
priority: p1
effort: m
spec_readiness: ready
depends_on: []
blocked_by: []
owner: null
tags:
- collections
---

## Summary
- Sort interactive collection pickers by `created_at` in descending order (newest first).
- Keep ordering behavior centralized in shared prompt helpers so all collection selection flows are consistent.
- Treat missing/invalid/corrupt `created_at` metadata as undated and place those collections after dated entries.
- Add prompt-ordering tests to validate sorting, tie-breaks, and sentinel behavior.

## Acceptance Criteria
- Interactive collection pickers show dated collections first, newest to oldest.
- Collections with equal `created_at` values are tie-broken by collection name ascending.
- Missing/invalid/corrupt `created_at` entries are still selectable and appear after dated collections.
- `pick_or_create_collection` keeps the create sentinel at the top.
- Tests cover ordering behavior and pass for the targeted suite.
