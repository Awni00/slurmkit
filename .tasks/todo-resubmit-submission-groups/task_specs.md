# Task: Resubmit Submission Groups

## Goal
Track each `slurmkit resubmit` invocation in a submission group and persist group metadata on each resubmission entry.

## Scope
- Add `--submission-group NAME` to `slurmkit resubmit`.
- If omitted, auto-generate once per invocation: `resubmit_YYYYMMDD_HHMMSS`.
- Persist `submission_group` in `Collection.add_resubmission(...)` records.
- Keep backward compatibility for collection YAML files that do not include `submission_group`.

## Acceptance Criteria
- Resubmissions from `--collection` contain `submission_group` in YAML.
- Dry run prints selected submission group.
- Existing collections load without migration.
