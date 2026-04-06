### Fix `slurmkit resubmit --filter` State Handling

### Summary
- Root cause: `_resolve_resubmit_jobs` in workflows only special-cases `failed`; every other value silently falls back to all jobs.
- Validation gap: `resubmit_command` option parsing currently accepts arbitrary strings, so typos broaden scope instead of failing.
- Scope for this change: explicit, validated filter set; no silent broadening; help/docs aligned; plus `--job-id` state gating.

### Implementation Changes
- Add a single source of truth for resubmit filter values and matching rules in the resubmit workflow path.
- Support filters: `pending`, `running`, `completed`, `failed`, `unknown`, `preempted`, `timeout`, `cancelled`, `node_fail`, `out_of_memory`, `oom`, `all`.
- Implement deterministic filter matching against latest effective rows:
  - Canonical filters (`pending|running|completed|failed|unknown`) match normalized effective state.
  - Raw terminal filters (`preempted|timeout|cancelled|node_fail|out_of_memory|oom`) match effective raw/canonical terminal state from latest attempt diagnostics.
  - `all` is explicit-only and matches all.
- Remove implicit fallback-to-all behavior entirely.
- Enforce fail-fast validation:
  - Invalid `--filter` raises non-zero error with message listing allowed values.
  - Keep parser/help/selection behavior wired to the same allowed-values constant.
- Update `--job-id` semantics:
  - Allow non-default filters in `--job-id` mode.
  - Apply state gating to the targeted job.
  - If targeted job does not match filter, fail non-zero with clear mismatch message.
- Update CLI/help/docs text to reflect actual filter set and semantics, including explicit `all` and `--job-id` gating behavior in:
  - `src/slurmkit/cli/commands_jobs.py`
  - `docs/cli-reference.md`
  - `README.md`

### Test Plan
- Workflow tests (`tests/test_workflows_jobs.py`):
  - `filter_name="failed"` selects only failed effective jobs.
  - `filter_name="preempted"` selects only preempted effective jobs.
  - Add coverage for `timeout|cancelled|node_fail|out_of_memory|oom` mapping behavior.
  - Invalid filter raises with allowed-values message.
  - `all` selects all jobs only because explicitly supported.
- CLI tests:
  - `slurmkit resubmit <collection> --filter nonsense --dry-run` exits non-zero and lists supported filters.
  - `slurmkit resubmit <collection> --filter preempted --dry-run` only targets matching jobs.
  - `slurmkit resubmit --job-id <id> --filter <state>`:
    - matching state: proceeds
    - mismatching state: exits non-zero with mismatch error.
- Keep/adjust existing `--job-id` tests so they validate new gating behavior instead of old failed-only filter restriction.

### Assumptions
- `all` remains supported, but only as an explicit validated value.
- Filter input is normalized case-insensitively; help/docs present canonical lowercase values.
- `--job-id` filter mismatch is an error (non-zero), not a no-op.
