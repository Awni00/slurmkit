# Sync

Cross-cluster job state synchronization.

## Overview

The `SyncManager` class enables sharing job states across multiple compute clusters via git. This is useful when:

- Running experiments across multiple clusters
- Sharing job status with collaborators
- Maintaining a central record of all job states

## Classes

### SyncManager

::: slurmkit.sync.SyncManager
    options:
      members:
        - __init__
        - sync_collection
        - sync_all
        - push
        - write_sync_file
        - get_sync_file_path

## Usage Example

```python
from slurmkit.sync import SyncManager
from slurmkit import CollectionManager

# Initialize sync manager
sync = SyncManager()

# Get a collection
manager = CollectionManager()
collection = manager.get("my_experiment")

# Sync collection state to git-tracked file
sync.sync_collection(collection)

# Push changes to remote
sync.push(message="Update job states from cluster-a")
```

### CLI Usage

The sync functionality is typically used via the CLI:

```bash
# Sync all collections and push
slurmkit sync --push

# Sync specific collection
slurmkit sync --collection my_experiment

# On another cluster, pull and view
git pull
slurmkit collection show my_experiment
```
