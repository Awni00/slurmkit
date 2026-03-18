---
task_id: t-20260314-002
task_name: dot-slurmkit-config
status: todo
date_created: '2026-03-14'
date_started: null
date_completed: null
priority: p1
effort: m
spec_readiness: rough
depends_on: []
blocked_by: []
owner: null
tags:
- config
---

## Summary
- CCurrently we use .slurm-kit/ for the hidden slurmkit dir (with config's etc). should it be .slurmkit for symmetry with package name.
- what do we envision including in .slurmkit/? only config.yaml, right now? if so perhaps .jobs-collections/ dir should be under .slurmkit/. Why need two seperate directories. Perhaps makes more sense to put under .slurmkit/job-collections, or similar. perhaps job-collections can be organized hierarchically under experiments, or similar? think carefully about how to design to make it make sense for multi-collection multi-experiment project workflows, etc.

## Acceptance Criteria
- TODO
