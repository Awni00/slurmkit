# Job Generation

Template-based SLURM job script generation with parameter sweeps.

## Overview

The `JobGenerator` class generates SLURM job scripts from Jinja2 templates combined with parameter specifications. It supports:

- Grid-based parameter sweeps
- Explicit parameter lists
- Dynamic SLURM argument computation via Python functions
- Custom job naming patterns

## Classes

### JobGenerator

::: slurmkit.generate.JobGenerator
    options:
      members:
        - __init__
        - from_spec
        - generate

## Functions

::: slurmkit.generate.expand_grid

::: slurmkit.generate.expand_parameters

::: slurmkit.generate.load_job_spec

::: slurmkit.generate.generate_job_name

## Usage Example

```python
from slurmkit import JobGenerator

# Create generator from a job spec file
generator = JobGenerator.from_spec("experiments/exp1/job_spec.yaml")

# Generate all job scripts
jobs = generator.generate()

for job in jobs:
    print(f"Generated: {job['script_path']}")
    print(f"  Parameters: {job['params']}")
    print(f"  Job name: {job['job_name']}")
```

### Manual Configuration

```python
from slurmkit.generate import JobGenerator, expand_grid

# Expand parameter grid
params_list = expand_grid({
    "learning_rate": [0.001, 0.01, 0.1],
    "batch_size": [32, 64]
})

# Create generator manually
generator = JobGenerator(
    template_path="templates/train.job.j2",
    output_dir="jobs/exp1/job_scripts",
    parameters=params_list,
    slurm_defaults={"partition": "gpu", "time": "24:00:00"},
    job_name_pattern="lr{{ learning_rate }}_bs{{ batch_size }}"
)

# Generate scripts
jobs = generator.generate()
```
