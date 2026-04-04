---
task_id: t-20260330-001
task_name: refactor-slurmkit-status-cmd
status: completed
date_created: '2026-03-30'
date_started: '2026-04-04'
date_completed: '2026-04-04'
priority: p1
effort: m
spec_readiness: rough
depends_on: []
blocked_by: []
owner: null
tags:
- status
---

## Summary
- Currently, `slurmkit status` will print a very long printout of the generation args for the collection, and the full list of all jobs (which can be very long)
- Think about how to design this command. E.g., link to spec file rather than printing generation params in console.
- Maybe what information to show can be chosen by user interactively and iteratively. Start with summary, and ask if user wants full printout. Should this be combined with `analyze` in some way, or at least provide option to show analysis?
- Maybe list of jobs can include hyperlinks to job output file? (or both job file and output file?). This allows user to quickly click through to inspect failed jobs etc.
- Include job runtime in `slurmkit status` job list
- Maybe omit hostname by default. Can perhaps include arguments about what columns to include in .slurmkit/config.yaml?

## Acceptance Criteria
- TODO
