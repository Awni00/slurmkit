# SLURM Utilities

Functions for interacting with SLURM schedulers.

## Overview

This module provides wrapper functions for common SLURM operations:

- Querying job status via `sacct` and `squeue`
- Submitting jobs via `sbatch`
- Finding job output files
- Parsing SLURM output formats

## Functions

### Job Status

::: slurmkit.slurm.get_job_status

::: slurmkit.slurm.get_sacct_info

::: slurmkit.slurm.get_pending_jobs

### Job Submission

::: slurmkit.slurm.submit_job

### Job Output

::: slurmkit.slurm.find_job_output

::: slurmkit.slurm.get_job_script_path

## Usage Example

```python
from slurmkit import (
    get_job_status,
    get_sacct_info,
    get_pending_jobs,
    submit_job,
    find_job_output,
)

# Get status of specific jobs
statuses = get_job_status(["12345", "12346", "12347"])
for job_id, status in statuses.items():
    print(f"Job {job_id}: {status}")

# Get detailed accounting info
info = get_sacct_info(["12345"])
print(info)  # DataFrame with job details

# List pending/running jobs
pending = get_pending_jobs()
print(f"You have {len(pending)} jobs in the queue")

# Submit a job script
job_id = submit_job("jobs/exp1/job_scripts/train.sh")
print(f"Submitted job: {job_id}")

# Find output file for a job
output_path = find_job_output(
    job_id="12345",
    job_name="lr0.01_bs32",
    search_dirs=["jobs/exp1/logs"]
)
print(f"Output file: {output_path}")
```
