"""
Filter parameter combinations for demo jobs.

This function demonstrates how to exclude incompatible combinations
from a grid sweep.
"""


def include_params(params: dict) -> bool:
    """
    Return True to keep this parameter combination.

    Excludes: algorithm=algo_b with dataset=small
    """
    algorithm = params.get("algorithm")
    dataset = params.get("dataset")

    if algorithm == "algo_b" and dataset == "small":
        return False

    return True
