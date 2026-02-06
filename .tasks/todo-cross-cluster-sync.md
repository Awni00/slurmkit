# Cross-Cluster Sync Improvements

## Overview

Enhancements to the cross-cluster synchronization feature.

## Current Limitations

1. Sync is manual (requires running `slurmkit sync`)
2. No conflict detection between cluster files
3. No automatic git operations by default
4. No aggregate dashboard view

## Proposed Improvements

### 1. Automatic Sync Daemon

```bash
# Run background sync daemon
slurmkit sync --daemon --interval 300

# Or via systemd service
systemctl --user start slurmkit-sync
```

Configuration:
```yaml
sync:
  auto_sync: true
  interval_seconds: 300
  auto_push: false  # Requires explicit --push
```

### 2. Conflict Detection

When pulling sync files from git:
```bash
slurmkit sync pull
```

Should detect and report:
- Jobs submitted on multiple clusters
- State inconsistencies
- Missing collections

### 3. Aggregate Dashboard

```bash
slurmkit sync status
```

Output:
```
Cross-Cluster Status
====================

Last sync:
  cluster-a: 2025-01-15 14:00:00 (2 hours ago)
  cluster-b: 2025-01-15 15:30:00 (30 minutes ago)
  cluster-c: 2025-01-14 10:00:00 (1 day ago) ⚠️ stale

Collection: my_experiment (12 jobs)
  Cluster     Submitted  Running  Completed  Failed
  cluster-a          8        2          5       1
  cluster-b          4        0          4       0
  Overall           12        2          9       1

Jobs needing attention:
  - train_lr0.01: FAILED on cluster-a
  - train_lr0.1: RUNNING on cluster-a (24+ hours)
```

### 4. Selective Sync

```bash
# Sync only specific collections
slurmkit sync --collection exp1 exp2

# Sync from specific clusters
slurmkit sync pull --from cluster-a cluster-b
```

### 5. Merge Strategies

For jobs that exist on multiple clusters:
```yaml
sync:
  merge_strategy: latest_wins  # or: first_wins, ask
```

## Implementation Notes

### Daemon Mode

- Use `watchdog` or simple polling loop
- PID file for single-instance guarantee
- Graceful shutdown handling

### Aggregate View

- Parse all sync files in `.slurm-kit/sync/`
- Build unified job state map
- Highlight conflicts and issues

### Git Integration

```python
def sync_with_git(push: bool = False):
    # 1. Git pull (with conflict handling)
    # 2. Run local sync
    # 3. Git add sync file
    # 4. Git commit
    # 5. Git push (if push=True)
```

## Priority

Medium - Improves multi-cluster workflow significantly.

## Related

- Current sync implementation in `slurmkit/sync.py`
- Git operations for automatic push
