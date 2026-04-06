---
task_id: t-20260316-001
task_name: collection-estimated-completion-time
status: completed
date_created: '2026-03-16'
date_started: '2026-04-06'
date_completed: '2026-04-06'
priority: p2
effort: m
spec_readiness: rough
depends_on: []
blocked_by: []
owner: null
tags:
- status
---

## Summary
- Do we currently have "estimated time to start" and "estimated time to completion" at the level of jobs?
- We should included "estimated time to completion" for collections, perhaps calculated as max("estimated time to completion" over running jobs in that collection);
- Naively: "estimated time to completion" = "estimated time to start" + "job duration" (although if job duration is too long or too short (necessitating re-runs), this will be inaccurate.

## Acceptance Criteria
- TODO
