### Feature Plan: Templated `job_subdir` with Spec Variables

### Summary
Add a reusable spec interpolation layer and use it for `job_subdir` in v1. Support built-in context keys (`collection_name`, `collection_slug`, `spec_name`, `spec_stem`, `spec_dir`) plus a new optional spec key `variables:` exposed as `vars.<key>`. Rendering is strict: unresolved variables fail generation with a clear error.

### Implementation Changes
1. **Task tracking (`dot-tasks`)**
- Bind to a new task named `job-subdir-template-context`.
- Lifecycle for implementation phase: `create` -> `start` -> write full approved plan to `plan.md` -> periodic `log-activity` -> `complete` after acceptance tests pass.
- Include requirement in task notes: docs are updated only after implementation is tested and completed.

2. **Spec interpolation engine**
- Add a small helper module/function for rendering spec strings with Jinja2 using `StrictUndefined`.
- Input: raw string + context mapping; output: rendered string or structured error with missing key info.
- Keep it reusable for future fields, but in v1 only call it for `job_subdir`.

3. **Context contract for `job_subdir`**
- Provide these keys:
  - `collection_name`: exact `--into` value.
  - `collection_slug`: normalized filesystem-safe slug from collection name (lowercase, non-alnum to `-`, collapse repeats, trim ends).
  - `spec_name`: `name` from YAML.
  - `spec_stem`: spec file stem.
  - `spec_dir`: spec directory relative to project root.
  - `vars`: mapping from new optional `variables:` key in spec.
- `variables:` must be a mapping; non-mapping values fail validation with actionable error text.

4. **Wire-up points**
- Thread `collection_name` and spec-path-derived context into generation planning and `JobGenerator.from_spec(...)`.
- Render `job_subdir` before existing path validation.
- Keep existing safety validation unchanged after render (`relative`, no `..`, not absolute).
- Update dry-run/review output to show resolved `job_subdir` (and raw when templated) for transparency.

5. **Docs and spec template**
- Update docs for job generation to describe templated `job_subdir`, available built-ins, and `variables:` examples.
- Update starter spec template output to include a commented `variables:` block and a templated `job_subdir` example.
- Per requirement: apply doc updates after implementation is tested and completed.

### Test Plan
- Unit: `job_subdir` renders correctly with `collection_name` and `collection_slug`.
- Unit: `variables:` values render via `vars.<key>`.
- Unit: unresolved key in template hard-fails with clear message naming the missing key.
- Unit: rendered absolute path and rendered `..` path are rejected by existing validators.
- Integration/workflow: `plan_generate` and execution paths use resolved `job_subdir` consistently for scripts/logs and generation metadata.
- Snapshot/string tests: spec-template output includes new commented `variables:` guidance.
- Docs check: examples match implemented key names and behavior.

### Assumptions and Defaults
- v1 interpolation scope is **`job_subdir` only** (engine is reusable but not yet applied to template/callback paths).
- No CLI `--var` overrides in this first change.
- Strict rendering is required; no warn-and-continue fallback.
- `project_name` is intentionally excluded.
