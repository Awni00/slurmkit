## Plan
TODO: Write complete plan generated during plan mode verbosely here.
# Remove Redundant Demo Collection Prefix

## Summary
- Drop the `demo/` namespace from demo-project collection IDs while keeping the hierarchical grouping structure.
- Update helper output, quickstart defaults, docs, and smoke tests together so all demo references stay aligned.

## Key Changes
- Switch generated collection IDs to `generated/hyperparameter_sweep` and `generated/model_comparison`.
- Switch dummy fixture collection IDs to `fixtures/mixed_30`, `notifications/terminal_failed`, `notifications/terminal_completed`, and `notifications/in_progress`.
- Refresh README examples and demo smoke assertions to match the new IDs.

## Verification
- Run demo smoke coverage plus the full pytest suite after the rename.
