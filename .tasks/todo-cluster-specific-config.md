# Cluster-Specific Configuration

## Overview

Currently, slurmkit uses the same configuration across all clusters. This enhancement would allow cluster-specific settings that are automatically applied based on hostname.

## Proposed Feature

### Configuration Format

```yaml
# .slurm-kit/config.yaml

# Default settings (applied everywhere)
slurm_defaults:
  time: "24:00:00"
  mem: "16G"

# Cluster-specific overrides
clusters:
  cluster-a:
    hostname_pattern: "login-a*"  # Regex pattern for matching
    slurm_defaults:
      partition: gpu-a
      max_gpus: 8
      default_account: project-a

  cluster-b:
    hostname_pattern: "cluster-b-*"
    slurm_defaults:
      partition: compute
      max_gpus: 4
      default_account: project-b

  gpu-cluster:
    hostname_pattern: "gpu[0-9]+"
    slurm_defaults:
      partition: gpu
      gres: "gpu:a100:1"
```

### Automatic Detection

When slurmkit runs, it would:
1. Get current hostname
2. Match against `hostname_pattern` for each cluster
3. Merge cluster-specific settings with defaults

### CLI Override

```bash
# Force specific cluster settings
slurmkit --cluster gpu-cluster generate spec.yaml
```

## Implementation Notes

### Changes Required

1. **config.py**
   - Add `clusters` section to config schema
   - Add hostname matching logic
   - Implement config merging for matched cluster

2. **CLI**
   - Add `--cluster` global option
   - Add `slurmkit cluster list` command to show detected cluster

3. **Documentation**
   - Update configuration docs
   - Add cluster configuration examples

### Considerations

- Hostname patterns should use regex for flexibility
- Should support multiple hostname patterns per cluster
- Need fallback behavior when no cluster matches
- Consider caching matched cluster to avoid repeated regex matching

## Use Cases

1. **Different partitions**: GPU cluster vs CPU cluster
2. **Different accounts**: Project billing codes
3. **Different resource limits**: Memory, GPU types
4. **Different paths**: Scratch directories, module paths

## Priority

Medium - Useful for users working across multiple clusters, but current behavior (same config everywhere) works for most cases.

## Related

- Cross-cluster sync already tracks hostname
- Collections store hostname per job
