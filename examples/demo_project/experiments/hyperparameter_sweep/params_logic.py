"""
Parameter parsing and filtering logic for demo jobs.
"""


def parse_params(params: dict) -> list[dict]:
    """Expand each source experiment into multiple seeded trials."""
    parsed = []
    n_trials = int(params.get("n_trials", 1))
    for seed in range(n_trials):
        trial = dict(params)
        trial["seed"] = seed
        trial["profile"] = (
            f"{trial.get('algorithm', 'algo_a')}_"
            f"{trial.get('dataset', 'small')}_"
            f"{trial.get('config', 'default')}"
        )
        parsed.append(trial)
    return parsed


def include_params(params: dict) -> bool:
    """
    Return True to keep this parameter combination.

    Excludes: algorithm=algo_b with dataset=small, and keeps only one seed for
    the small dataset to demonstrate per-child filtering after parse expansion.
    """
    algorithm = params.get("algorithm")
    dataset = params.get("dataset")
    seed = params.get("seed", 0)

    if algorithm == "algo_b" and dataset == "small":
        return False
    if dataset == "small" and seed > 0:
        return False

    return True
