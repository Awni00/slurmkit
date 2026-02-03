# Cross-Cluster Synchronization

slurmkit supports working across multiple compute clusters within a shared repository. The sync feature allows you to:

- Track job states across different clusters
- Share status via git-tracked files
- View combined status from any cluster

## How It Works

1. **Local sync** - Each cluster writes its own sync file
2. **Git sharing** - Sync files are committed and pushed
3. **Combined view** - Read sync files from all clusters

```
.slurm-kit/sync/
├── cluster-a.yaml    # Sync file from cluster A
├── cluster-b.yaml    # Sync file from cluster B
└── cluster-c.yaml    # Sync file from cluster C
```

## Sync File Format

Each sync file contains the state of collections on that cluster:

```yaml
cluster: cluster-a
synced_at: "2025-01-15T16:00:00"
total_collections: 2
total_jobs_updated: 5

collections:
  my_experiment:
    name: my_experiment
    description: "Training sweep"
    updated_jobs: 3
    total: 12
    pending: 0
    running: 2
    completed: 8
    failed: 2
    jobs:
      - job_name: train_lr0.001
        job_id: "12345678"
        state: COMPLETED
        hostname: cluster-a
      - job_name: train_lr0.01
        job_id: "12345679"
        state: FAILED
        hostname: cluster-a
        resubmissions:
          - job_id: "12345700"
            state: RUNNING
            hostname: cluster-a

  exp2:
    # ... another collection
```

## Basic Workflow

### 1. Sync Local State

On each cluster, run:

```bash
slurmkit sync
```

This:
- Refreshes job states from SLURM
- Updates collection files
- Writes sync file for current cluster

### 2. Share via Git

Commit and push sync file:

```bash
slurmkit sync --push
```

Or manually:

```bash
git add .slurm-kit/sync/
git commit -m "Sync job states"
git push
```

### 3. Pull on Other Clusters

On other clusters:

```bash
git pull
slurmkit collection show my_experiment
```

## CLI Commands

### Basic Sync

```bash
# Sync all collections
slurmkit sync

# Sync specific collections
slurmkit sync --collection exp1 exp2

# Sync and push to git
slurmkit sync --push
```

### View Combined Status

From Python or by reading sync files:

```python
from slurmkit.sync import SyncManager

manager = SyncManager()

# List all sync files (all clusters)
clusters = manager.list_sync_files()
print(f"Clusters: {clusters}")

# Get combined status for a collection
status = manager.get_combined_status("my_experiment")

for job in status["jobs"]:
    print(f"{job['job_name']}: {job['overall_state']}")
    for sub in job["submissions"]:
        print(f"  - {sub['cluster']}: {sub['state']}")
```

## Multi-Cluster Experiment Workflow

### Setup

1. Clone repo on each cluster
2. Initialize slurmkit on each cluster
3. Generate jobs (can be done on any cluster)

### Running Jobs

On cluster A:
```bash
slurmkit submit --collection my_experiment
slurmkit sync --push
```

On cluster B:
```bash
git pull
slurmkit submit --collection my_experiment
slurmkit sync --push
```

### Monitoring

From any cluster:
```bash
git pull
slurmkit collection show my_experiment
```

### Resubmitting

On the cluster where jobs failed:
```bash
slurmkit resubmit --collection my_experiment --filter failed
slurmkit sync --push
```

## Hostname Identification

Clusters are identified by hostname. The hostname is recorded when:

- Collections are created
- Jobs are submitted
- Jobs are resubmitted

This allows tracking which cluster each job ran on.

## Best Practices

1. **Sync after changes** - Run `slurmkit sync` after submitting or resubmitting
2. **Pull before checking** - Run `git pull` before viewing cross-cluster status
3. **Use --push for updates** - Combine sync and push for convenience
4. **Commit messages** - The `--push` option creates descriptive commit messages

## Conflict Resolution

Sync files are per-cluster, so conflicts are rare. If they occur:

1. The conflict will be in `.slurm-kit/sync/<hostname>.yaml`
2. Keep the version from the cluster that owns the file
3. Re-sync on that cluster if needed

## Programmatic Usage

```python
from slurmkit.sync import SyncManager, sync_jobs

# Quick sync
result = sync_jobs(push=True)
print(f"Updated {result['total_jobs_updated']} jobs")

# Detailed usage
manager = SyncManager()

# Sync specific collections
result = manager.sync_all(collection_names=["exp1", "exp2"])

# Read sync files from all clusters
all_sync = manager.get_all_sync_data()
for hostname, data in all_sync.items():
    print(f"\n{hostname}:")
    print(f"  Last synced: {data['synced_at']}")
    for name, coll in data['collections'].items():
        print(f"  {name}: {coll['completed']}/{coll['total']} completed")

# Combined status
status = manager.get_combined_status("my_experiment")
for job in status["jobs"]:
    # Check if any submission succeeded
    if job["overall_state"] == "COMPLETED":
        print(f"✓ {job['job_name']}")
    else:
        print(f"✗ {job['job_name']}: {job['overall_state']}")
```

## Limitations

- Sync is manual (run `slurmkit sync` to update)
- Requires git for sharing (or manual file copying)
- Job IDs are cluster-specific
- States only update when sync is run on the cluster

## Future Enhancements

See `todo/cross-cluster-sync.md` for planned improvements.
