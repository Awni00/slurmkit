# Task: Resubmit Callback Selection

## Goal
Allow callback-driven per-job resubmission decisions.

## Scope
- Add `--select-file FILE` and `--select-function NAME` (default `should_resubmit`).
- Callback contract: `should_resubmit(context: dict) -> bool | (bool, reason)`.
- Apply built-in `--filter` first, then callback gating.
- Show selected/skipped counts and optional reasons in preview output.
- Fail fast on callback exceptions and invalid return types.

## Acceptance Criteria
- Callback can skip jobs with optional reason text.
- Dry-run output includes skipped job reporting.
