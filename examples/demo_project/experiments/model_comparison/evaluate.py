#!/usr/bin/env python3
"""Dummy experiment entrypoint for the model comparison demo."""

from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser(description="Dummy evaluation script for slurmkit demos.")
    parser.add_argument("--algorithm", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--duration", type=int, default=10)
    args = parser.parse_args()

    print("model_comparison evaluate.py invoked")
    print(f"algorithm={args.algorithm}")
    print(f"dataset={args.dataset}")
    print(f"duration={args.duration}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
