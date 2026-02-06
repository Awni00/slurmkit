# slurmkit Demo Project

This is a simple, runnable example project demonstrating all features of slurmkit.

**Key features:**
- Jobs are simple "hello world" style demos that just echo parameters and sleep
- Can be actually submitted and run quickly for testing (10-30 seconds per job)
- Demonstrates all slurmkit features without needing real training code
- Uses minimal SLURM resources (1G memory, 1 CPU, 5 minute limit)

## Project Structure

```
demo_project/
├── README.md                          # This file
├── templates/                         # Jinja2 job templates
│   ├── training.job.j2               # Simple demo job template
│   └── evaluation.job.j2             # Simple evaluation demo
├── experiments/                       # Experiment configurations
│   ├── hyperparameter_sweep/
│   │   ├── job_spec.yaml             # Parameter grid specification (6 jobs after filter)
│   │   ├── params_filter.py          # Grid filter logic
│   │   └── slurm_logic.py            # Dynamic resource allocation
│   └── model_comparison/
│       └── job_spec.yaml             # Explicit parameter list (4 jobs)
└── .slurm-kit/                       # slurmkit configuration (created on init)
    └── config.yaml

After running jobs:
├── jobs/                              # Generated jobs and outputs
│   ├── hyperparameter_sweep/
│   │   ├── job_scripts/              # Generated .job files
│   │   └── logs/                     # Job output files
│   └── model_comparison/
│       ├── job_scripts/
│       └── logs/
└── .job-collections/                  # Job tracking
    ├── hp_sweep.yaml
    └── model_comp.yaml
```

## Quick Start

### 1. Initialize Configuration

```bash
cd examples/demo_project
slurmkit init
```

**Configure for your cluster:**
- Edit `.slurm-kit/config.yaml`
- Set the correct partition name
- Adjust default memory/time limits

### 2. Generate Jobs

**Hyperparameter sweep (grid mode):**
```bash
slurmkit generate experiments/hyperparameter_sweep/job_spec.yaml \
    --collection hp_sweep
```

This creates 6 jobs (8 combinations minus 2 filtered: algo_b + small).

**Model comparison (list mode):**
```bash
slurmkit generate experiments/model_comparison/job_spec.yaml \
    --collection model_comp
```

This creates 4 jobs with explicit parameter combinations.

### 3. Review Generated Scripts

```bash
# List generated scripts
ls jobs/hyperparameter_sweep/job_scripts/

# View a script
cat jobs/hyperparameter_sweep/job_scripts/demo_algo_a_small_default.job
```

### 4. Submit Jobs

**Dry run first:**
```bash
slurmkit submit --collection hp_sweep --dry-run
```

**Submit for real:**
```bash
slurmkit submit --collection hp_sweep --delay 2
```

### 5. Monitor Progress

**Check all jobs:**
```bash
slurmkit status
```

**Check specific experiment:**
```bash
slurmkit status hyperparameter_sweep
```

**Update collection from SLURM:**
```bash
slurmkit collection update hp_sweep
slurmkit collection show hp_sweep
```

**Filter by state:**
```bash
slurmkit collection show hp_sweep --state running
slurmkit collection show hp_sweep --state failed
```

### 5.5 Configure and Test Notifications (Optional)

Add a route in `.slurm-kit/config.yaml`:

```yaml
notifications:
  routes:
    - name: demo_webhook
      type: webhook
      url: "${DEMO_WEBHOOK_URL}"
      events: [job_failed]
```

Test route configuration:

```bash
slurmkit notify test --route demo_webhook
slurmkit notify test --dry-run
```

### 6. View Job Output

**Find output file:**
```bash
slurmkit find <JOB_ID> --preview
```

**View with more context:**
```bash
slurmkit find <JOB_ID> --preview --lines 100
```

### 7. Handle Failures

**Resubmit failed jobs:**
```bash
slurmkit resubmit --collection hp_sweep --filter failed
```

**Resubmit with checkpoint resume:**
```bash
slurmkit resubmit <JOB_ID> --extra-params "checkpoint=checkpoints/epoch_10.pt"
```

## Features Demonstrated

### 1. Template Variables

See `templates/training.job.j2` for:
- SLURM directives from config variables
- Parameter substitution using Jinja2
- Conditional logic based on parameters
- Creating output files with job results

### 2. Parameter Grids

`experiments/hyperparameter_sweep/job_spec.yaml` shows:
- **Grid mode**: automatically generates all combinations
- Job naming patterns using parameter values
- Multiple parameters (algorithm, dataset, config)
- Optional grid filtering via `params_filter.py`

### 3. Parameter Lists

`experiments/model_comparison/job_spec.yaml` shows:
- **List mode**: explicit parameter combinations
- Different parameters for different jobs
- Optional parameters (like extra_flag)

### 4. Dynamic SLURM Arguments

`experiments/hyperparameter_sweep/slurm_logic.py` demonstrates:
- Adjusting memory based on dataset size
- Allocating more CPUs for certain algorithms
- Conditional resource allocation

### 5. Collections

Track related jobs together:
```bash
slurmkit collection list
slurmkit collection show hp_sweep
slurmkit collection show hp_sweep --format yaml
```

### 6. Cross-Cluster Sync

Share status across clusters:
```bash
slurmkit sync --push
```

## Example Workflows

### Workflow 1: Basic Demo Run

```bash
# Generate 6 demo jobs (filter excludes algo_b + small)
slurmkit generate experiments/hyperparameter_sweep/job_spec.yaml --collection demo_run

# Preview what will be submitted
slurmkit submit --collection demo_run --dry-run

# Submit all jobs with 2 second delay between submissions
slurmkit submit --collection demo_run --delay 2

# Monitor progress
watch -n 10 'slurmkit collection show demo_run'

# When done, check results
ls results/
```

To notify from inside a job script while preserving original exit code:

```bash
trap 'rc=$?; slurmkit notify job --job-id "${SLURM_JOB_ID}" --exit-code "${rc}"; exit "${rc}"' EXIT
```

### Workflow 2: Iterative Template Development

```bash
# Edit template to customize output
vim templates/training.job.j2

# Regenerate with new template (creates new collection)
slurmkit generate experiments/hyperparameter_sweep/job_spec.yaml --collection test_v2

# Preview a generated script
cat jobs/hyperparameter_sweep/job_scripts/demo_algo_a_small_default.job

# Submit just one job for testing
slurmkit submit jobs/hyperparameter_sweep/job_scripts/demo_algo_a_small_default.job
```

### Workflow 3: Testing Collections and Resubmission

```bash
# Generate a small test collection
slurmkit generate experiments/model_comparison/job_spec.yaml --collection test_collection

# Submit all jobs
slurmkit submit --collection test_collection

# Check collection status
slurmkit collection show test_collection

# If any fail, resubmit them
slurmkit resubmit --collection test_collection --filter failed
```

## Tips

### Customize for Your Cluster

Before running, update these in your job specs:

1. **Partition name** - Change `partition: compute` to your cluster's partition:
   ```yaml
   slurm_args:
     defaults:
       partition: YOUR_PARTITION_NAME  # Update this!
   ```

2. **Time and memory** - Already set to minimal values (5 min, 1G) for demo

3. **Check available partitions:**
   ```bash
   sinfo  # See available partitions
   squeue -u $USER  # See your running jobs
   ```

### Job Naming Best Practices

Use descriptive patterns that include key parameters:
```yaml
job_name_pattern: "{{ algorithm }}_{{ dataset }}_{{ config }}"
```

For your own work, you might use:
```yaml
job_name_pattern: "{{ experiment }}_{{ model }}_lr{{ learning_rate }}_{{ timestamp }}"
```

### Using SLURM Logic Functions

The `slurm_logic.py` file shows how to dynamically allocate resources.
For your real work, you might want to:

```python
def get_slurm_args(params, defaults):
    args = defaults.copy()

    # Scale memory with data size
    if params['dataset_size'] == 'large':
        args['mem'] = '64G'

    # More GPUs for certain models
    if params['model'] in ['large_model', 'transformer']:
        args['gpus'] = 4

    return args
```

### Organize Experiments

Create subdirectories for different experiment types:
```
experiments/
├── baselines/
├── ablations/
├── hyperparameter_sweeps/
└── final_runs/
```

## Cleanup

### Remove Generated Jobs

```bash
# Delete collection and files
slurmkit collection delete hp_sweep

# Or manually
rm -rf jobs/hyperparameter_sweep/
```

### Reset Configuration

```bash
rm -rf .slurm-kit/ .job-collections/
slurmkit init
```

## Next Steps

1. **Read the full docs** in `../../docs/`
2. **Adapt templates** for your actual workflows
3. **Create job specs** for your experiments
4. **Set up cross-cluster sync** if using multiple clusters
5. **Integrate with wandb** for experiment tracking

## Troubleshooting

**Jobs not found:**
- Check `output_patterns` in `.slurm-kit/config.yaml`
- Verify files are in expected directory structure

**Template errors:**
- Validate Jinja2 syntax
- Ensure all variables are provided in parameters

**SLURM errors:**
- Check partition exists: `sinfo`
- Verify account/QoS if required
- Check resource limits: `sacctmgr show qos`

## Support

For issues or questions:
- Check main README: `../../README.md`
- Read documentation: `../../docs/`
- Open an issue on GitHub
