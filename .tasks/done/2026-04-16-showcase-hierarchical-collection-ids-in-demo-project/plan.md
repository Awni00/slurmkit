## Plan
TODO: Write complete plan generated during plan mode verbosely here.
# Demo Project Hierarchical Collection ID Showcase

## Summary
- Update the demo project so hierarchical collection IDs are visible in both generated quickstart flows and deterministic dummy fixture flows.
- Restore the richer dummy fixture set described by the README, but with hierarchical collection IDs that exercise the new feature directly.

## Key Changes
- Update `examples/demo_project/quickstart.sh` to use hierarchical generated collection IDs and display nested collection file paths in its summary/help text.
- Update `examples/demo_project/setup_dummy_jobs.py` to create four deterministic hierarchical collections for mixed-state, terminal-failed, terminal-completed, and in-progress notification demos.
- Refresh `examples/demo_project/README.md`, `examples/README.md`, and top-level demo references in `README.md` to use the new hierarchical IDs consistently.
- Add a demo smoke test that runs the dummy setup in a temporary demo-project copy and verifies the nested collection files plus expected `generation.spec_path` metadata.

## Verification
- Run targeted pytest coverage for the new demo smoke test and any affected related tests.
- Manually validate the documented dummy/demo commands against the hierarchical IDs used in the updated docs.

## Assumptions
- `--prefix` in `setup_dummy_jobs.py` is treated as a single safe top-level namespace segment.
- Existing experiment `job_subdir` values remain unchanged; this work showcases hierarchical collection IDs, not new job directory behavior.
