---
task_id: t-20260325-001
task_name: accept-extra-args-in-slurmkit-notify
status: todo
date_created: '2026-03-25'
date_started: null
date_completed: null
priority: p2
effort: m
spec_readiness: rough
depends_on: []
blocked_by: []
owner: null
tags:
- notify
---

## Summary
- Want to add support for main script to return diagnostic info (or write it to a file or directory) itself that can be included in the slurmkit notification (for example, wandb run link, etc.)
- How should this be implemented? Custom message-formatting callback together with extra_args_payload etc. Perhaps passed as path-to-json or raw json string, etc.

## Acceptance Criteria
- TODO
