# Task: Collection Group Filter + Groups Command

## Goal
Support submission-group-aware analysis and expose submission group counts.

## Scope
- Add `--submission-group NAME` to `collection analyze`.
- In submission-group mode, analyze latest attempt within that group.
- Add `collection groups <name> [--format table|json|yaml]`.
- Report group fields: `submission_group`, `slurm_job_count`, `parent_job_count`, `first_submitted_at`, `last_submitted_at`.
- Bucket historical unlabeled resubmissions under `legacy_ungrouped`.

## Acceptance Criteria
- Group-filtered analyze output changes to group-latest semantics.
- `collection groups` returns deterministic per-group counts.
