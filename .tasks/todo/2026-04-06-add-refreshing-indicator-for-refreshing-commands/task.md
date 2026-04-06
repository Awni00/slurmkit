---
task_id: t-20260406-006
task_name: add-refreshing-indicator-for-refreshing-commands
status: todo
date_created: '2026-04-06'
date_started: null
date_completed: null
priority: p2
effort: m
spec_readiness: ready
depends_on: []
blocked_by: []
owner: null
tags:
- cli
- status
---

## Summary
- Add a brief user-visible refresh indicator for commands that refresh collection state before rendering output.

## Context
- Keep current refresh behavior.
- Improve UX by signaling when refresh is in progress.

## Trigger
- Commands that call refresh before output (status/show/analyze and explicit refresh flows).

## Scope
- `--ui plain`: print concise line like `Refreshing collection state...` before refresh; avoid noisy multi-line chatter.
- `--ui rich`: show temporary spinner/status while refresh executes; clear/replace on completion.
- Keep output deterministic for `--json` (avoid contaminating JSON payload stream).

## Hand-off Artifacts
- Reference command paths:
  - `src/slurmkit/cli/commands_jobs.py` (`status`)
  - `src/slurmkit/cli/commands_collections.py` (`show`, `analyze`, `refresh`)
  - `src/slurmkit/workflows/collections.py` (refresh hooks)

## Testing
- Manual checks in plain and rich modes.
- Ensure `--json` remains machine-parseable.

## Acceptance Criteria
- Users receive clear, brief indication that refresh is happening.
- Indicator is temporary/minimal and does not pollute structured output.
