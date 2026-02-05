# Job Generation

slurmkit provides powerful tools for generating SLURM job scripts from templates and parameter specifications.

## Overview

Job generation combines:
- **Jinja2 templates** - Define the structure of your job scripts
- **Parameter specifications** - Define variations (grid or list)
- **SLURM argument logic** - Optionally customize resources per job
- **Collections** - Track generated jobs

## Quick Start

### 1. Create a Template

Create a Jinja2 template file `templates/train.job.j2`:

```jinja2
#!/bin/bash
#SBATCH --job-name={{ job_name }}
#SBATCH --partition={{ slurm.partition }}
#SBATCH --time={{ slurm.time }}
#SBATCH --mem={{ slurm.mem }}
#SBATCH --gres=gpu:{{ slurm.gpus }}
#SBATCH --output={{ logs_dir }}/{{ job_name }}.%j.out

# Load environment
source ~/.bashrc
conda activate myenv

# Run training
python train.py \
    --learning-rate {{ learning_rate }} \
    --batch-size {{ batch_size }} \
    --model {{ model }}
```

### 2. Create a Job Spec

Create `experiments/exp1/job_spec.yaml`:

```yaml
name: exp1_sweep
description: "Learning rate and batch size sweep"

template: ../../templates/train.job.j2
output_dir: job_scripts
logs_dir: logs

parameters:
  mode: grid
  values:
    learning_rate: [0.001, 0.01, 0.1]
    batch_size: [32, 64]
    model: [resnet18]

slurm_args:
  defaults:
    partition: gpu
    time: "24:00:00"
    mem: "32G"
    gpus: 1

job_name_pattern: "{{ model }}_lr{{ learning_rate }}_bs{{ batch_size }}"
```

### 3. Generate Jobs

```bash
cd experiments/exp1
slurmkit generate job_spec.yaml --collection exp1

# Preview without writing
slurmkit generate job_spec.yaml --dry-run
```

## Job Spec Reference

### Full Job Spec Format

```yaml
# Descriptive name for this job spec
name: my_experiment

# Human-readable description
description: "Hyperparameter sweep for ResNet training"

# Path to Jinja2 template (relative to spec file or absolute)
template: templates/train.job.j2

# Output directory for generated scripts
output_dir: job_scripts

# Directory for job outputs (used in templates)
logs_dir: logs

# Parameter specification
parameters:
  # Mode: "grid" for all combinations, "list" for explicit list
  mode: grid
  values:
    learning_rate: [0.001, 0.01, 0.1]
    batch_size: [32, 64]
    model: [resnet18, resnet50]
  # Optional filter for grid mode
  filter:
    file: params_filter.py
    function: include_params

# SLURM arguments
slurm_args:
  # Default values
  defaults:
    partition: gpu
    time: "24:00:00"
    mem: "32G"
    gpus: 1

  # Optional: Python function for dynamic logic
  logic:
    file: slurm_logic.py
    function: get_slurm_args

# Jinja2 pattern for job names
job_name_pattern: "{{ model }}_lr{{ learning_rate }}_bs{{ batch_size }}"
```

## Parameter Modes

### Grid Mode

All combinations of parameter values:

```yaml
parameters:
  mode: grid
  values:
    lr: [0.001, 0.01]
    bs: [32, 64]
```

Generates 4 jobs: `(0.001, 32), (0.001, 64), (0.01, 32), (0.01, 64)`

### Grid Filtering

For incompatible parameter combinations, add a filter function to trim the grid:

```yaml
parameters:
  mode: grid
  values:
    algorithm: [algo_a, algo_b]
    dataset: [small, large]
  filter:
    file: params_filter.py
    function: include_params  # Optional, defaults to "include_params"
```

```python
# params_filter.py
def include_params(params: dict) -> bool:
    # Exclude algo_b with small dataset
    return not (params.get("algorithm") == "algo_b" and params.get("dataset") == "small")
```

Filters only apply to grid mode; list mode ignores them.
Filter file paths are resolved relative to the job spec file.

### List Mode

Explicit list of parameter combinations:

```yaml
parameters:
  mode: list
  values:
    - {lr: 0.001, bs: 32, model: small}
    - {lr: 0.01, bs: 64, model: large}
    - {lr: 0.1, bs: 128, model: xlarge}
```

## Template Variables

Templates have access to these variables:

| Variable | Description |
|----------|-------------|
| `job_name` | Generated job name |
| `slurm` | Dictionary of SLURM arguments |
| `logs_dir` | Logs directory path |
| `<param>` | Each parameter from your specification |

### Example Template

```jinja2
#!/bin/bash
#SBATCH --job-name={{ job_name }}
#SBATCH --partition={{ slurm.partition }}
#SBATCH --time={{ slurm.time }}
#SBATCH --mem={{ slurm.mem }}
{% if slurm.gpus is defined %}
#SBATCH --gres=gpu:{{ slurm.gpus }}
{% endif %}
#SBATCH --output={{ logs_dir }}/{{ job_name }}.%j.out
#SBATCH --error={{ logs_dir }}/{{ job_name }}.%j.err

echo "Job: {{ job_name }}"
echo "Learning rate: {{ learning_rate }}"
echo "Batch size: {{ batch_size }}"

python train.py \
    --lr {{ learning_rate }} \
    --bs {{ batch_size }} \
    {% if epochs is defined %}--epochs {{ epochs }}{% endif %}
```

## Dynamic SLURM Arguments

For complex resource requirements, use a Python function:

### slurm_logic.py

```python
def get_slurm_args(params: dict, defaults: dict) -> dict:
    """
    Customize SLURM arguments based on job parameters.

    Args:
        params: Job parameters (learning_rate, batch_size, etc.)
        defaults: Default SLURM args from job spec

    Returns:
        Final SLURM arguments dictionary
    """
    args = defaults.copy()

    # Larger models need more memory
    model = params.get('model', 'resnet18')
    if model == 'resnet50':
        args['mem'] = '64G'
        args['gpus'] = 2
    elif model == 'resnet101':
        args['mem'] = '128G'
        args['gpus'] = 4

    # Larger batch sizes need more memory
    batch_size = params.get('batch_size', 32)
    if batch_size >= 128:
        args['mem'] = '64G'

    # Long training needs more time
    epochs = params.get('epochs', 100)
    if epochs > 500:
        args['time'] = '72:00:00'

    return args
```

### Reference in Job Spec

```yaml
slurm_args:
  defaults:
    partition: gpu
    time: "24:00:00"
    mem: "32G"
    gpus: 1

  logic:
    file: slurm_logic.py
    function: get_slurm_args  # Optional, defaults to "get_slurm_args"
```

## Job Naming

### Default Naming

Without a pattern, job names are parameter key-value pairs:

```
learning_rate0.001_batch_size32_modelresnet18
```

### Custom Pattern

Use Jinja2 for readable names:

```yaml
job_name_pattern: "{{ model }}_lr{{ learning_rate }}_bs{{ batch_size }}"
```

Produces:

```
resnet18_lr0.001_bs32
```

### Tips

- Keep names short (SLURM limits job name length)
- Include key distinguishing parameters
- Avoid spaces and special characters

## CLI Commands

### Generate from Spec File

```bash
slurmkit generate job_spec.yaml
slurmkit generate job_spec.yaml --collection my_exp
slurmkit generate job_spec.yaml --dry-run
```

### Generate with CLI Arguments

```bash
slurmkit generate \
    --template templates/train.job.j2 \
    --params params.yaml \
    --output-dir jobs/exp1/scripts \
    --collection exp1
```

## Programmatic Usage

```python
from slurmkit.generate import JobGenerator, generate_jobs_from_spec
from slurmkit.collections import CollectionManager

# From spec file
results = generate_jobs_from_spec(
    "job_spec.yaml",
    collection_name="my_experiment",
)

# Programmatically
generator = JobGenerator(
    template_path="templates/train.job.j2",
    parameters={
        "mode": "grid",
        "values": {
            "learning_rate": [0.001, 0.01],
            "batch_size": [32, 64],
        }
    },
    slurm_defaults={"partition": "gpu", "time": "24:00:00"},
    job_name_pattern="{{ learning_rate }}_{{ batch_size }}",
)

# Preview
print(generator.preview(0))
print(f"Will generate {generator.count_jobs()} jobs")

# Generate
manager = CollectionManager()
collection = manager.get_or_create("my_experiment")

results = generator.generate(
    output_dir="jobs/exp1/scripts",
    collection=collection,
)

manager.save(collection)
```
