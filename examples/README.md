# slurmkit Examples

This directory contains example projects and use cases for slurmkit.

## Available Examples

### demo_project/

A complete, runnable demonstration project showing all slurmkit features:

- **Simple demo jobs** - "Hello world" style jobs that can actually be submitted and run quickly
- **Job templates** - Jinja2 templates demonstrating parameter substitution and conditionals
- **Parameter grids** - Both grid mode (all combinations) and list mode (explicit combinations)
- **Dynamic SLURM args** - Resource allocation based on job parameters
- **Collections** - Tracking related jobs together
- **Minimal resources** - Jobs use 1G memory, 1 CPU, run for 10-30 seconds

**Quick start:**
```bash
cd demo_project
./quickstart.sh
```

Or follow the detailed README:
```bash
cd demo_project
cat README.md
```

## Using These Examples

### 1. As a Learning Resource

Browse the examples to understand how to:
- Structure your project
- Write Jinja2 templates
- Create job specifications
- Use dynamic SLURM argument logic
- Organize experiments

### 2. As a Testing Environment

Use `demo_project/` to test slurmkit features:

```bash
cd demo_project

# Initialize
slurmkit init

# Generate test jobs
slurmkit generate experiments/hyperparameter_sweep/job_spec.yaml --collection test

# View generated scripts
ls jobs/hyperparameter_sweep/job_scripts/

# Test without submitting
slurmkit status --dry-run
```

### 3. As a Template

Copy and adapt for your own projects:

```bash
# Create your project from the example
cp -r demo_project my_project
cd my_project

# Customize for your needs
vim templates/training.job.j2
vim experiments/my_experiment/job_spec.yaml

# Initialize and use
slurmkit init
slurmkit generate experiments/my_experiment/job_spec.yaml
```

## What Each Example Demonstrates

### demo_project/

| Feature | Location | What it Shows |
|---------|----------|---------------|
| Basic template | `templates/training.job.j2` | Jinja2 syntax, SLURM directives, parameter substitution, creating output files |
| Parameter grid | `experiments/hyperparameter_sweep/job_spec.yaml` | Grid mode for all combinations (8 jobs) |
| Parameter list | `experiments/model_comparison/job_spec.yaml` | List mode for explicit combinations (4 jobs) |
| Dynamic resources | `experiments/hyperparameter_sweep/slurm_logic.py` | Python function for SLURM args based on parameters |
| Job naming | Both job specs | Readable naming patterns using parameters |
| Simple execution | Both templates | Jobs that just echo and sleep, easy to test |

## Creating Your Own Example

If you want to contribute an example:

1. Create a new directory: `examples/my_example/`
2. Include:
   - `README.md` - Explain what it demonstrates
   - `templates/` - Job templates
   - `experiments/` - Job specifications
   - `.gitignore` - Exclude generated files
3. Document unique aspects or patterns
4. Test it works end-to-end

## Tips for Using Examples

### Customize for Your Cluster

Before running examples:

1. **Update partition names** in job specs
   ```yaml
   slurm_args:
     defaults:
       partition: YOUR_PARTITION  # Change this!
   ```

2. **Adjust resource limits** based on your cluster
   ```yaml
   mem: "16G"  # Check your limits
   time: "24:00:00"  # Check your QoS
   ```

3. **Check available resources**
   ```bash
   sinfo  # See partitions
   sacctmgr show qos  # See time/resource limits
   ```

### Start Small

1. **Test with one job first**
   ```bash
   # Modify job spec to have just one parameter combination
   slurmkit generate spec.yaml --collection test
   slurmkit submit --collection test
   ```

2. **Verify output patterns match**
   ```bash
   # Check your actual output file format
   ls jobs/experiment/logs/
   # Update .slurm-kit/config.yaml if needed
   ```

3. **Scale up gradually**
   ```bash
   # Once one job works, increase the parameter grid
   ```

## Common Modifications

### Change Training Script

Edit the template to call your script:

```jinja2
# Instead of:
python train.py ...

# Use:
python -m your_module.train ...
# or:
./your_script.sh ...
```

### Add More Parameters

Extend the parameter grid:

```yaml
parameters:
  mode: grid
  values:
    learning_rate: [0.001, 0.01, 0.1]
    batch_size: [32, 64]
    optimizer: [adam, sgd, adamw]  # New parameter
    dropout: [0.1, 0.3, 0.5]        # Another one
```

### Use Environment Modules

Add to template:

```bash
# Load required modules
module load python/3.9
module load cuda/11.8
module load gcc/11.2
```

### Add W&B Integration

In template:

```bash
# Set W&B environment
export WANDB_PROJECT="{{ wandb_project }}"
export WANDB_NAME="{{ job_name }}"

python train.py --use-wandb ...
```

In job spec:

```yaml
parameters:
  values:
    wandb_project: [my-project]  # Fixed param
    # ... other params
```

## Support

For questions or issues with examples:
- Check the main README: `../README.md`
- Read the documentation: `../docs/`
- Review the example README files
- Open an issue on GitHub
