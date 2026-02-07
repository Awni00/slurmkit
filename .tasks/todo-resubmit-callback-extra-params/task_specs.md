# Task: Resubmit Callback Extra Params

## Goal
Allow per-job dynamic resubmission parameter generation via a Python callback file.

## Scope
- Add `--extra-params-file FILE` and `--extra-params-function NAME` (default `get_extra_params`).
- Callback contract: `get_extra_params(context: dict) -> dict`.
- Merge precedence: callback result first, then CLI `--extra-params` overrides.
- Fail fast on callback load/runtime/type errors.

## Acceptance Criteria
- Callback can add per-job metadata to resubmission records.
- CLI values override callback values on key collisions.
- Invalid callback behavior exits with an error.
