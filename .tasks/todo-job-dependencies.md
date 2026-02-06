# Job Dependencies

## Overview

Add support for defining and managing job dependencies in collections and during submission.

## Proposed Feature

### Dependency Specification in Collections

```yaml
# Collection with dependencies
jobs:
  - job_name: preprocess
    job_id: "12345"
    state: COMPLETED

  - job_name: train
    job_id: "12346"
    depends_on:
      - preprocess
    dependency_type: afterok  # SLURM dependency type

  - job_name: evaluate
    depends_on:
      - train
    dependency_type: afterok
```

### Job Spec Dependencies

```yaml
# job_spec.yaml with dependencies
parameters:
  mode: list
  values:
    - name: preprocess
      stage: 1
    - name: train
      stage: 2
      depends_on: preprocess
    - name: evaluate
      stage: 3
      depends_on: train
```

### CLI Support

```bash
# Submit with automatic dependency handling
slurmkit submit --collection my_exp --with-dependencies

# Show dependency graph
slurmkit collection show my_exp --dependencies

# Submit specific stages
slurmkit submit --collection my_exp --stage 2
```

### Dependency Types

Support SLURM dependency types:
- `after`: Start after jobs begin
- `afterok`: Start after jobs complete successfully
- `afternotok`: Start after jobs fail
- `afterany`: Start after jobs finish (any state)
- `aftercorr`: For array jobs

## Implementation Notes

### Changes Required

1. **collections.py**
   - Add `depends_on` and `dependency_type` to job schema
   - Add method to resolve dependency chain
   - Track dependency satisfaction status

2. **CLI submit**
   - Parse dependencies when submitting
   - Build `--dependency` string for sbatch
   - Handle submission order

3. **CLI status**
   - Show dependency graph
   - Indicate blocked jobs

### Considerations

- Handle circular dependency detection
- What happens when a dependency fails?
- Support for cross-collection dependencies?
- Visualization of dependency DAG

## Use Cases

1. **Pipeline stages**: preprocess → train → evaluate
2. **Ensemble training**: Multiple models → aggregation
3. **Hyperparameter sweeps**: Grid search → best model selection

## Priority

Medium-High - Common workflow pattern for ML experiments.

## Related

- SLURM `--dependency` flag documentation
- Job generation module for stage-based specs
