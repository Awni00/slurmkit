# Job Generation

`slurmkit generate` turns a YAML spec plus a Jinja template into job scripts and records the generated jobs in a collection.

## Core model

A spec controls:

- the template file
- the relative `job_subdir`
- parameter expansion (`grid` or `list`)
- optional parse/filter hooks
- default and dynamic SLURM args
- job naming
- optional collection-specific notification overrides

Generation is collection-bound:

```bash
slurmkit generate experiments/exp1/slurmkit/job_spec.yaml --into exp1
```

If the target collection already exists, generation is append-only. Name collisions are renamed with suffixes like `-2`, `-3`, and so on.

## Minimal spec

```yaml
name: exp1
description: "Example sweep"

template: train.job.j2
job_subdir: sweeps/exp1

parameters:
  mode: grid
  values:
    learning_rate: [0.001, 0.01]
    batch_size: [32, 64]

slurm_args:
  defaults:
    partition: gpu
    time: "04:00:00"
    mem: "16G"

job_name_pattern: "lr{{ learning_rate }}_bs{{ batch_size }}"
```

With default config, this writes:

- scripts to `.jobs/sweeps/exp1/job_scripts/`
- logs to `.jobs/sweeps/exp1/logs/`

## Template variables

Templates receive:

- `job_name`
- `slurm`
- `logs_dir`
- each parameter key from the effective parameter mapping

Example:

```jinja2
#!/bin/bash
#SBATCH --job-name={{ job_name }}
#SBATCH --partition={{ slurm.partition }}
#SBATCH --time={{ slurm.time }}
#SBATCH --output={{ logs_dir }}/{{ job_name }}.%j.out

python train.py --lr {{ learning_rate }} --bs {{ batch_size }}
```

## Parameter modes

### Grid mode

```yaml
parameters:
  mode: grid
  values:
    lr: [0.001, 0.01]
    bs: [32, 64]
```

This generates all combinations.

### List mode

```yaml
parameters:
  mode: list
  values:
    - {lr: 0.001, bs: 32}
    - {lr: 0.01, bs: 64}
```

This generates only the listed parameter sets.

## Parse and filter hooks

`parse` can derive effective parameter sets before naming, filtering, and rendering:

```yaml
parameters:
  mode: grid
  values:
    algorithm: [algo_a, algo_b]
    n_trials: [2]
  parse: params_logic.py:parse_params
```

```python
def parse_params(params: dict) -> list[dict]:
    return [
        {**params, "seed": seed, "profile": f"{params['algorithm']}_s{seed}"}
        for seed in range(params["n_trials"])
    ]
```

`filter` removes incompatible or unwanted effective parameter sets:

```yaml
parameters:
  mode: grid
  values:
    algorithm: [algo_a, algo_b]
    dataset: [small, large]
  filter: params_logic.py:include_params
```

```python
def include_params(params: dict) -> bool:
    return not (params["algorithm"] == "algo_b" and params["dataset"] == "small")
```

Hook file paths are resolved relative to the spec file.

## Dynamic SLURM args

Use a Python function to compute resources from parameters:

```yaml
slurm_args:
  defaults:
    partition: gpu
    time: "04:00:00"
    mem: "16G"
  logic: slurm_logic.py:get_slurm_args
```

```python
def get_slurm_args(params: dict, defaults: dict) -> dict:
    args = defaults.copy()
    if params.get("model") == "large":
        args["mem"] = "64G"
    return args
```

## Notification overrides in specs

Specs may define a top-level `notifications` block. These settings override global `.slurmkit/config.yaml` notifications for collections generated from that spec.

```yaml
notifications:
  defaults:
    output_tail_lines: 20
  job:
    ai:
      enabled: true
      callback: "utilities.slurmkit.ai_callbacks:summarize_job_payload"
  collection_final:
    ai:
      enabled: true
      callback: "utilities.slurmkit.ai_callbacks:summarize_collection_report"
```

## Dry run

Preview the generation plan without writing files:

```bash
slurmkit generate experiments/exp1/slurmkit/job_spec.yaml --into exp1 --dry-run
```
