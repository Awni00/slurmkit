## Refactor Plan: `status` Summary-Only + `collections show` Paginated Tables

### Summary
- Redefine `slurmkit status` as a compact, summary-only command (no job table in text or JSON).
- Keep all job-table inspection in `slurmkit collections show`, with config-driven columns and interactive paging.
- Remove spec-parameter YAML printout from both commands; replace with header file links.
- Add header links for `spec_path`, `collection_file`, `scripts_dir`, and `logs_dir` when available.

### Implementation Changes
- CLI behavior and contracts:
  - `slurmkit status`:
    - Remove `--state`.
    - Text output: collection metadata + summary metrics + header links only.
    - JSON output: compact payload only (no `jobs` table/list), including summary and links.
  - `slurmkit collections show`:
    - Keep detailed view with jobs table.
    - Add auto-pager behavior (`space`/`q`) when interactive and row count exceeds threshold.
- Config additions (defaults in `DEFAULT_CONFIG`):
  - `ui.columns.collections_show`: ordered list of column IDs used by `collections show`.
  - `ui.collections_show.pager`: `auto|always|never` (default `auto`).
  - `ui.collections_show.pager_row_threshold`: integer default `20`.
- Jobs table column system:
  - Introduce a column registry mapping column ID -> header + row extractor.
  - Include `hostname` as supported column but exclude it from default config.
  - Include runtime column (computed from effective attempt timestamps: `started_at`/`completed_at`, with running duration when `completed_at` absent).
  - Continue to support existing detailed fields (`attempt`, `submission_group`, `history`, etc.) through column IDs instead of hardcoded table layout.
- Report/model updates:
  - Replace hardcoded `build_collection_show_report` row/header composition with config-driven columns.
  - Remove `parameters_yaml` rendering from collection show/status report paths.
  - Add link metadata block generation in workflows layer using collection generation metadata and collection file path.
- Paging implementation:
  - Implement paging at render layer for `collections show` only.
  - In interactive mode with paging enabled and rows above threshold, route output through pager (`less`/system pager); otherwise render normally.
  - Non-interactive mode always renders directly without pager.

### Public Interface Changes
- `slurmkit status`:
  - Breaking: `--state` removed.
  - Breaking: `--json` payload no longer contains job rows.
- Config schema:
  - New keys under `ui.columns.collections_show` and `ui.collections_show.*`.
- `slurmkit collections show`:
  - Same command entrypoint, but table composition now controlled by config and paged in interactive large-output cases.

### Test Plan
- CLI behavior tests:
  - `status` no longer accepts `--state`.
  - `status` text output contains summary and header links, and does not render jobs table or generation-params YAML.
  - `status --json` omits jobs list and returns compact schema with summary + links.
- Report/config tests:
  - `collections show` respects `ui.columns.collections_show` ordering and inclusion.
  - `hostname` column works when configured and is absent in default rendering.
  - Runtime column formatting for completed, running, and missing timestamp cases.
- Paging tests:
  - Pager invoked when interactive + enabled + row threshold exceeded.
  - Pager not invoked when non-interactive, disabled, or below threshold.
- Regression tests:
  - Existing collection list/analyze behavior unchanged.
  - Existing summary metrics and status coloring still correct.

### Assumptions and Defaults
- Prior “columns for both commands” intent is superseded by the final decision: job tables live only in `collections show`.
- Hyperlinks are rendered as file path links in header metadata where terminal/backend supports it; plain text fallback is absolute path strings.
- No backward-compat bridge for `status --state` or legacy full `status --json`; this refactor intentionally changes those contracts now.
