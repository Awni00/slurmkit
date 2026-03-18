---
task_id: t-20260315-001
task_name: slurmkit-skill-install-cmd
status: completed
date_created: '2026-03-15'
date_started: '2026-03-18'
date_completed: '2026-03-18'
priority: p2
effort: m
spec_readiness: rough
depends_on: []
blocked_by: []
owner: null
tags: []
---

## Summary
- add command to install slurmkit skill. skill is managed via repo. similar architecture to https://github.com/awni00/dot-tasks
- skill source found in github repo. installed via `npx skills`.
- skill should outline a few workflows. Describe how to use slurmkit package, and overview commands and workflows. how to organize project, how to create collections etc.
- workflow: generate a spec for given experiment (e.g., grid or list of jobs). directives: often based around a script. study and understand the script. favor being explicit about script arguments over hidden defaults. if in grid mode, list sweep values at top. organize arguments/parameters by logical categories, with comments. study project structure to understand where to place spec/template etc. A reasonable default if early project doesn't have clear structure yet is experiments/{experiment_name}/slurmkit/{collection_name}/spec.md|template.j2, where core experiment code lies in experiments/{experiment_name}, for example. [provide skill with some example project structure; core/, experiments/, .slurmkit/, experiments/experiment1/run_experiment.py, experiments/experiment1/slurmkit, etc]
- workflow: analyzing failure of collection. check spec for output dir, use slurmkit to probe failure/success and find list of failed jobs. then manually look at output files for failed jobs. systematically identify causes for failure and categorize. Come back with a concise report listing categories, identified causes, identified bugs in code and suggested fixes if simple or suggested course of action if not simple

## Acceptance Criteria
- TODO
