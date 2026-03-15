#!/usr/bin/env python3
"""Dummy experiment entrypoint for the hyperparameter sweep demo."""

from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser(description="Dummy training script for slurmkit demos.")
    parser.add_argument("--algorithm", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--duration", type=int, default=10)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    print("hyperparameter_sweep train.py invoked")
    print(f"algorithm={args.algorithm}")
    print(f"dataset={args.dataset}")
    print(f"config={args.config}")
    print(f"duration={args.duration}")
    print(f"seed={args.seed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
