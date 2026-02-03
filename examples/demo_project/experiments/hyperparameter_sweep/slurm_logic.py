"""
Dynamic SLURM argument allocation for demo jobs.

This function demonstrates how to customize resource requests based on job parameters.
For the demo, we keep resources minimal but show the pattern for customization.
"""


def get_slurm_args(params: dict, defaults: dict) -> dict:
    """
    Customize SLURM arguments based on job parameters.

    This is a simple demo showing how different parameter values
    can trigger different resource allocations.

    Args:
        params: Job parameters from the job spec
            - algorithm: Algorithm type (algo_a, algo_b, etc.)
            - dataset: Dataset size (small, large)
            - config: Configuration type (default, optimized)
            - duration: Job runtime in seconds

        defaults: Default SLURM arguments from job spec
            - partition, time, mem, cpus_per_task, etc.

    Returns:
        Dictionary of SLURM arguments to use for this job
    """
    # Start with defaults
    args = defaults.copy()

    # Get job parameters
    algorithm = params.get('algorithm', 'algo_a')
    dataset = params.get('dataset', 'small')
    config = params.get('config', 'default')

    # =========================================================================
    # Dataset-specific resources
    # =========================================================================

    if dataset == 'large':
        # Larger datasets need more memory and CPUs
        args['mem'] = '2G'
        args['cpus_per_task'] = 2

    # =========================================================================
    # Algorithm-specific resources
    # =========================================================================

    if algorithm == 'algo_b':
        # algo_b is more memory intensive
        current_mem = int(args['mem'].rstrip('G'))
        args['mem'] = f"{current_mem + 1}G"

    # =========================================================================
    # Configuration adjustments
    # =========================================================================

    if config == 'optimized':
        # Optimized config uses more CPUs for parallelization
        args['cpus_per_task'] = max(args.get('cpus_per_task', 1), 2)

    return args
