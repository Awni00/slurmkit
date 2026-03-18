# Implementation Plan: slurmkit spec-template

## Goal
Add a top-level `slurmkit spec-template` command that writes a simple, educational `job_spec.yaml` scaffold.

## Changes
1. Add a helper in `src/slurmkit/generate.py` to render a scaffold string.
   - Active grid-mode example.
   - Commented list-mode alternative.
   - Commented advanced features (`parse`, `filter`, `slurm_args.logic`, `notifications`).
   - Include comments that show expected scripts/logs paths based on configured `jobs_dir` and template `job_subdir`.
2. Add `spec-template` command in `src/slurmkit/cli/commands_jobs.py`.
   - Default output path: `job_spec.yaml` in current working directory.
   - `--output/-o` for custom target path.
   - `--force` to allow overwrite.
   - Fail fast when target exists and `--force` is unset.
3. Add command picker wiring in `src/slurmkit/cli/app.py`.
4. Add tests:
   - Unit tests for helper output in `tests/test_generate.py`.
   - CLI tests for write/overwrite/custom output behavior in `tests/test_cli_app.py`.
5. Update command docs in `docs/cli-reference.md`.

## Verification
- Run focused pytest for `tests/test_generate.py` and `tests/test_cli_app.py`.
- Confirm command writes file and overwrite guards behave as expected.
