#!/usr/bin/env python3
"""Outcome-agnostic Shapley utilities for annual rail-event attribution."""

from __future__ import annotations

from collections.abc import Callable
from math import comb

import numpy as np


Array = np.ndarray


def exact_shapley(coalition_values: Array, n_packages: int) -> Array:
    """Return exact package contributions from values ordered by bit-mask."""
    values = np.asarray(coalition_values, dtype=np.float64)
    if values.shape[0] != 1 << n_packages:
        raise ValueError("first axis must contain exactly 2**n_packages coalitions")
    contributions = np.zeros((n_packages,) + values.shape[1:], dtype=np.float64)
    for package in range(n_packages):
        bit = 1 << package
        for mask in range(1 << n_packages):
            if mask & bit:
                continue
            size = mask.bit_count()
            weight = 1.0 / (n_packages * comb(n_packages - 1, size))
            contributions[package] += weight * (values[mask | bit] - values[mask])
    return contributions


def permutation_shapley(
    value_function: Callable[[int], Array],
    n_packages: int,
    n_permutations: int,
    seed: int,
    antithetic_pairs: bool = True,
) -> tuple[Array, Array]:
    """Estimate contributions using deterministic (optionally antithetic) orders."""
    if n_permutations <= 0:
        raise ValueError("n_permutations must be positive")
    if antithetic_pairs and n_permutations % 2:
        raise ValueError("antithetic sampling requires an even permutation count")
    baseline = np.asarray(value_function(0), dtype=np.float64)
    contributions = np.zeros((n_packages,) + baseline.shape, dtype=np.float64)
    rng = np.random.default_rng(seed)
    orders: list[Array] = []
    draws = n_permutations // 2 if antithetic_pairs else n_permutations
    for _ in range(draws):
        order = rng.permutation(n_packages)
        orders.append(order)
        if antithetic_pairs:
            orders.append(order[::-1])
    for order in orders:
        mask = 0
        previous = baseline
        for package_value in order:
            package = int(package_value)
            mask |= 1 << package
            current = np.asarray(value_function(mask), dtype=np.float64)
            contributions[package] += current - previous
            previous = current
    contributions /= len(orders)
    return contributions, np.stack(orders)


def closure_diagnostics(
    contributions: Array,
    empty_value: Array,
    full_value: Array,
    absolute_tolerance: float = 1e-8,
    relative_tolerance: float = 1e-8,
) -> dict[str, float | bool]:
    """Check package-sum closure against the full annual value change."""
    target = np.asarray(full_value, dtype=np.float64) - np.asarray(
        empty_value, dtype=np.float64
    )
    reconstructed = np.asarray(contributions, dtype=np.float64).sum(axis=0)
    absolute_error = np.abs(reconstructed - target)
    scale = np.maximum(np.abs(target), absolute_tolerance)
    relative_error = absolute_error / scale
    passed = np.all(
        (absolute_error <= absolute_tolerance)
        | (relative_error <= relative_tolerance)
    )
    return {
        "passed": bool(passed),
        "maximum_absolute_error": float(absolute_error.max(initial=0.0)),
        "maximum_relative_error": float(relative_error.max(initial=0.0)),
    }
