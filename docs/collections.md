# Job Collections

Collections are groups of related jobs that are generated and submitted together. They provide:

- **Tracking** - Monitor job states across submissions
- **Organization** - Group related experiments
- **Resubmission** - Easily retry failed jobs
- **Cross-cluster sync** - Share status across clusters

## Collection Structure

Collections are stored as YAML files in `.job-collections/` (configurable):

```yaml
name: my_experiment
description: "Hyperparameter sweep for model training"
created_at: "2025-01-15T10:30:00"
updated_at: "2025-01-15T14:00:00"
cluster: cluster-a

# Generation parameters (for reference)
parameters:
  mode: grid
  values:
    learning_rate: [0.001, 0.01, 0.1]
    batch_size: [32, 64]

# List of jobs
jobs:
  - job_name: resnet18_lr0.001_bs32
    job_id: "12345678"
    script_path: jobs/exp1/job_scripts/resnet18_lr0.001_bs32.job
    output_path: jobs/exp1/logs/resnet18_lr0.001_bs32.12345678.out
    state: COMPLETED
    hostname: cluster-a
    parameters:
      learning_rate: 0.001
      batch_size: 32
    submitted_at: "2025-01-15T10:35:00"
    started_at: "2025-01-15T10:40:00"
    completed_at: "2025-01-15T14:20:00"
    resubmissions: []

  - job_name: resnet18_lr0.01_bs64
    job_id: "12345679"
    state: FAILED
    hostname: cluster-a
    # ... other fields ...
    resubmissions:
      - job_id: "12345700"
        state: RUNNING
        hostname: cluster-a
        submitted_at: "2025-01-15T15:00:00"
        extra_params:
          checkpoint: checkpoints/epoch_10.pt
```

## CLI Commands

### Create Collection

```bash
slurmkit collection create my_experiment --description "Training sweep"
```

### List Collections

```bash
slurmkit collection list
# Optional override to use primary submission state counts
slurmkit collection list --attempt-mode primary
```

`collection list` uses latest-attempt status counts by default.

Output:
```
Found 3 collection(s):

Name           Description                 Total  Completed  Failed  Pending  Running
my_experiment  Training sweep              12     8          2       0        2
exp2           Architecture comparison     6      6          0       0        0
default        (auto-created)              4      1          3       0        0
```

### Show Collection Details

```bash
slurmkit collection show my_experiment
```

Options:
- `--format json` - Output as JSON
- `--format yaml` - Output as YAML
- `--state failed` - Filter by effective state
- `--attempt-mode latest` - Effective attempt semantics (`latest` is default)
- `--submission-group retry_after_fix` - Restrict to jobs in a submission group
- `--show-primary` - Include primary submission state/id columns
- `--show-history` - Include compact attempt history in table mode

### Update Job States

Refresh job states from SLURM:

```bash
slurmkit collection update my_experiment
```

### Analyze Status by Parameter

Find patterns between parameter values and job outcomes:

```bash
slurmkit collection analyze my_experiment
```

Options:
- `--format json` - Output analysis as JSON
- `--no-refresh` - Skip SLURM refresh (analyze current YAML state)
- `--min-support N` - Minimum sample size for risky/stable summaries (default: 3)
- `--param KEY` - Restrict analysis to specific parameter keys (repeatable)
- `--attempt-mode latest` - Use latest resubmission state instead of primary job state
- `--submission-group NAME` - Analyze latest attempt within a specific submission group
- `--top-k N` - Number of entries in top risky/stable lists (default: 10)

Examples:

```bash
# Analyze specific parameters
slurmkit collection analyze my_experiment --param algo --param learning_rate

# Use latest retry outcome and stricter support threshold
slurmkit collection analyze my_experiment --attempt-mode latest --min-support 5

# Analyze a specific resubmission group
slurmkit collection analyze my_experiment --submission-group retry_after_fix

# Machine-readable output
slurmkit collection analyze my_experiment --format json
```

The report includes:
- Overall normalized state summary (`completed`, `failed`, `running`, `pending`, `unknown`)
- Per-parameter value tables with counts and failure/completion rates
- Top risky values (highest failure rates)
- Top stable values (highest completion rates)
- `Low N` marker for groups below `--min-support`

### Delete Collection

```bash
slurmkit collection delete my_experiment
```

Options:
- `--keep-scripts` - Don't delete job script files
- `--keep-outputs` - Don't delete output files
- `-y` - Skip confirmation

### Add Jobs to Collection

Add existing jobs by ID:

```bash
slurmkit collection add my_experiment 12345678 12345679
```

### Remove Jobs from Collection

```bash
slurmkit collection remove my_experiment 12345678
```

### List Submission Groups

```bash
slurmkit collection groups my_experiment
```

This reports:
- `submission_group`
- `slurm_job_count`
- `parent_job_count`
- `first_submitted_at`
- `last_submitted_at`

Historical resubmissions without explicit group labels are reported as `legacy_ungrouped`.

## Default Collection

When generating or submitting jobs without specifying a collection, slurmkit uses the `default` collection:

```bash
# Uses "default" collection
slurmkit generate job_spec.yaml
# Note: No collection specified. Using 'default' collection.
```

To use a specific collection:

```bash
slurmkit generate job_spec.yaml --collection my_experiment
```

## Collection Workflow

### 1. Generate Jobs

Jobs are automatically added to collection during generation:

```bash
slurmkit generate job_spec.yaml --collection my_experiment
```

### 2. Submit Jobs

Submit all unsubmitted jobs:

```bash
slurmkit submit --collection my_experiment
```

Submit all jobs (including already submitted):

```bash
slurmkit submit --collection my_experiment --filter all
```

### 3. Monitor Status

Check collection status:

```bash
slurmkit collection show my_experiment
```

Update states from SLURM:

```bash
slurmkit collection update my_experiment
```

### 4. Resubmit Failed Jobs

```bash
slurmkit resubmit --collection my_experiment --filter failed
```

With extra parameters (e.g., resume from checkpoint):

```bash
slurmkit resubmit --collection my_experiment --filter failed \
    --extra-params "checkpoint=checkpoints/last.pt"
```

Each resubmit invocation records a `submission_group`.
- Explicit: `--submission-group retry_after_fix`
- Default: auto-generated `resubmit_YYYYMMDD_HHMMSS`

You can also use Python callbacks:

```bash
slurmkit resubmit --collection my_experiment \
  --select-file callbacks.py \
  --select-function should_resubmit \
  --extra-params-file callbacks.py \
  --extra-params-function get_extra_params
```

## Notifications Integration

Collections are used by `slurmkit notify job` to enrich notifications with:
- Collection name/description
- Job metadata (name, state, timestamps)
- Output path and failure tail snippet (when available)

Collections also drive terminal collection reporting via `slurmkit notify collection-final`:
- evaluates finality with latest-attempt semantics
- sends `collection_completed` or `collection_failed` when terminal
- deduplicates repeated terminal snapshots via collection metadata

Typical end-of-job pattern:

```bash
rc=$?
slurmkit notify job --job-id "${SLURM_JOB_ID}" --exit-code "${rc}"
slurmkit notify collection-final --job-id "${SLURM_JOB_ID}"
exit "${rc}"
```

See [Notifications](notifications.md) for full route setup and command reference.

## Cross-Cluster Tracking

Jobs track the hostname where they were submitted:

```yaml
jobs:
  - job_name: train_model
    job_id: "12345"
    hostname: cluster-a
    # ...
```

This allows tracking the same experiment across multiple clusters. See [Cross-Cluster Sync](sync.md) for details.

## Resubmission Tracking

When jobs are resubmitted, the history is preserved:

```yaml
jobs:
  - job_name: train_model
    job_id: "12345"  # Original submission
    state: FAILED
    resubmissions:
      - job_id: "12346"  # First retry
        state: FAILED
        submitted_at: "2025-01-15T14:00:00"
      - job_id: "12347"  # Second retry
        state: COMPLETED
        submitted_at: "2025-01-15T15:00:00"
        extra_params:
          checkpoint: checkpoints/epoch_50.pt
```

## Programmatic Usage

```python
from slurmkit.collections import Collection, CollectionManager

# Create manager
manager = CollectionManager()

# Create collection
collection = manager.create(
    "my_experiment",
    description="Training sweep",
)

# Add jobs
collection.add_job(
    job_name="train_lr0.01",
    script_path="jobs/exp1/train_lr0.01.job",
    parameters={"learning_rate": 0.01},
)

# Save
manager.save(collection)

# Load existing
collection = manager.load("my_experiment")

# Update states from SLURM
updated_count = collection.refresh_states()

# Get summary
summary = collection.get_summary()
print(f"Completed: {summary['completed']}/{summary['total']}")

# Filter jobs
failed_jobs = collection.filter_jobs(state="failed")
pending_jobs = collection.filter_jobs(submitted=False)

# Record resubmission
collection.add_resubmission(
    "train_lr0.01",
    job_id="12346",
    extra_params={"checkpoint": "checkpoints/last.pt"},
)

manager.save(collection)
```

## Best Practices

1. **Use descriptive names** - Collection names should identify the experiment
2. **Add descriptions** - Help future you understand what the collection is for
3. **Update regularly** - Run `collection update` to keep states current
4. **Track parameters** - Include generation parameters for reproducibility
5. **Use for related jobs** - Don't mix unrelated experiments in one collection
