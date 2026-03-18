---
task_id: t-20260314-001
task_name: ensure-nested-job-dir-support-in-status-etc
status: completed
date_created: '2026-03-14'
date_started: '2026-03-14'
date_completed: '2026-03-18'
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
- Does `slurmkit status` support finding jobs in nested directories?
- Currently, spec contains output_dir and logs_dir for job file and log file directory. Should it instead rely on .slurmkit/config.yaml for jobs_dir? and supported nested subdir. slurmkit status, etc should look for location with respect to jobs_dir for where to find output jobs, etc.

## Acceptance Criteria
- TODO
