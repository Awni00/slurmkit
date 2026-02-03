# Collections

Job collection management for tracking related SLURM jobs.

## Overview

Collections allow you to group related jobs together, track their states, and perform batch operations. Each collection stores:

- Job metadata (parameters, script paths)
- Job IDs and submission history
- Current job states
- Timestamps

## Classes

### Collection

::: slurmkit.collections.Collection
    options:
      members:
        - __init__
        - add_job
        - get_job
        - update_job
        - add_resubmission
        - remove_job
        - filter_jobs
        - save
        - load
        - to_dict

### CollectionManager

::: slurmkit.collections.CollectionManager
    options:
      members:
        - __init__
        - create
        - get
        - list
        - exists
        - delete
        - load_all
        - get_collection_path

## Usage Example

```python
from slurmkit import Collection, CollectionManager

# Create a collection manager
manager = CollectionManager()

# Create a new collection
collection = manager.create("my_experiment", description="Training sweep")

# Add a job to the collection
collection.add_job(
    name="lr0.01_bs32",
    params={"learning_rate": 0.01, "batch_size": 32},
    script_path="jobs/exp1/job_scripts/lr0.01_bs32.sh"
)

# Submit and record job ID
collection.update_job("lr0.01_bs32", job_id="12345", state="PENDING")

# Filter jobs by state
failed_jobs = collection.filter_jobs(state="FAILED")

# Save collection
collection.save()
```
