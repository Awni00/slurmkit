## Plan

### Summary
- Mirror dot-tasks install-skill behavior in slurmkit with a top-level `install-skill` command, command-palette wiring, docs updates, and tests.
- Ship a single comprehensive `skills/slurmkit/SKILL.md` for agent workflows.

### Implementation
- Add `slurmkit install-skill [--nointeractive] [--yes]` in `src/slurmkit/cli/commands_maintenance.py`.
- Execute `npx skills add Awni00/slurmkit --skill slurmkit` via subprocess helper.
- Prompt for confirmation only when interactive and not `--yes`/`--nointeractive`.
- Surface actionable errors for missing `npx` and nonzero subprocess exits.
- Add `install-skill` to Setup palette and home dispatch map in `src/slurmkit/cli/app.py`.
- Update `docs/cli-reference.md` and `README.md` with command docs and quick usage.
- Add `skills/slurmkit/SKILL.md` with overview, project structure, command map, and workflow playbooks.

### Tests
- Add CLI tests in `tests/test_cli_app.py` for:
  - success path
  - missing `npx`
  - nonzero subprocess exit
  - confirmation cancel path
  - Setup palette includes `install-skill`
  - `home` dispatch path for `install-skill`

### Assumptions
- Install target is fixed to `Awni00/slurmkit` and skill name `slurmkit`.
- No init-time install prompt is added.
- No AGENTS snippet command is added.
