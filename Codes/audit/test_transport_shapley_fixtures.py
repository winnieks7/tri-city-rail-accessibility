#!/usr/bin/env python3
"""Synthetic, outcome-blind numerical fixtures for rail-event Shapley code."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from Codes.analysis.transport_shapley import (  # noqa: E402
    closure_diagnostics,
    exact_shapley,
    permutation_shapley,
)


MODULE = ROOT / "Codes/analysis/transport_shapley.py"
OUTPUT = ROOT / "Results/pilots/transport_shapley_synthetic_fixtures.json"
ATOL = 1e-8
RTOL = 1e-8


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def values_from_game(n_packages: int, function) -> np.ndarray:
    return np.stack([function(mask) for mask in range(1 << n_packages)])


def main() -> int:
    additive = np.array(
        [
            [[10.0, 2.0, 0.0], [1.0, 0.0, 1.0]],
            [[-3.0, 4.0, 0.0], [2.0, 1.0, 0.0]],
            [[5.0, -1.0, 1.0], [0.0, 2.0, -1.0]],
        ]
    )
    base = np.array([[100.0, 40.0, 0.0], [20.0, 10.0, 0.0]])

    def additive_game(mask: int) -> np.ndarray:
        selected = [i for i in range(3) if mask & (1 << i)]
        return base + (additive[selected].sum(axis=0) if selected else 0.0)

    additive_values = values_from_game(3, additive_game)
    additive_phi = exact_shapley(additive_values, 3)
    additive_closure = closure_diagnostics(
        additive_phi, additive_values[0], additive_values[-1], ATOL, RTOL
    )

    main_effects = np.array([3.0, -2.0, 4.0])
    pair_effects = {(0, 1): 6.0, (0, 2): -3.0, (1, 2): 9.0}
    triple_effect = 12.0

    def interaction_game(mask: int) -> np.ndarray:
        selected = {i for i in range(3) if mask & (1 << i)}
        value = 7.0 + sum(main_effects[i] for i in selected)
        value += sum(
            effect for pair, effect in pair_effects.items() if set(pair) <= selected
        )
        if selected == {0, 1, 2}:
            value += triple_effect
        return np.array([value])

    interaction_values = values_from_game(3, interaction_game)
    interaction_phi = exact_shapley(interaction_values, 3).ravel()
    expected_interaction = main_effects.copy()
    for pair, effect in pair_effects.items():
        expected_interaction[list(pair)] += effect / 2
    expected_interaction += triple_effect / 3
    interaction_closure = closure_diagnostics(
        interaction_phi,
        interaction_values[0],
        interaction_values[-1],
        ATOL,
        RTOL,
    )

    coverage_values = np.array([0.0, 1.0, 1.0, 1.0])[:, None]
    coverage_phi = exact_shapley(coverage_values, 2).ravel()
    coverage_closure = closure_diagnostics(
        coverage_phi, coverage_values[0], coverage_values[-1], ATOL, RTOL
    )

    approx_coefficients = np.arange(1.0, 12.0)

    def large_additive_game(mask: int) -> np.ndarray:
        value = 50.0 + sum(
            approx_coefficients[i] for i in range(11) if mask & (1 << i)
        )
        return np.array([value, value * 2])

    approx_phi_1, orders_1 = permutation_shapley(
        large_additive_game, 11, 4096, 20260826, True
    )
    approx_phi_2, orders_2 = permutation_shapley(
        large_additive_game, 11, 4096, 20260826, True
    )
    approx_expected = np.column_stack(
        [approx_coefficients, 2 * approx_coefficients]
    )
    approx_closure = closure_diagnostics(
        approx_phi_1,
        large_additive_game(0),
        large_additive_game((1 << 11) - 1),
        ATOL,
        RTOL,
    )

    checks = {
        "exact_additive_recovers_coefficients": bool(
            np.allclose(additive_phi, additive, atol=ATOL, rtol=RTOL)
        ),
        "exact_additive_closes": additive_closure["passed"],
        "negative_event_is_retained": bool(np.any(additive_phi[1] < 0)),
        "exact_interactions_allocate_analytical_shares": bool(
            np.allclose(
                interaction_phi, expected_interaction, atol=ATOL, rtol=RTOL
            )
        ),
        "exact_interaction_game_closes": interaction_closure["passed"],
        "redundant_binary_coverage_splits_equally": bool(
            np.allclose(coverage_phi, [0.5, 0.5], atol=ATOL, rtol=RTOL)
        ),
        "binary_coverage_game_closes": coverage_closure["passed"],
        "approximation_is_seed_deterministic": bool(
            np.array_equal(orders_1, orders_2)
            and np.array_equal(approx_phi_1, approx_phi_2)
        ),
        "antithetic_orders_are_reversals": bool(
            np.array_equal(orders_1[0::2], orders_1[1::2, ::-1])
        ),
        "approximate_additive_recovers_coefficients": bool(
            np.allclose(approx_phi_1, approx_expected, atol=ATOL, rtol=RTOL)
        ),
        "approximate_additive_game_closes": approx_closure["passed"],
        "same_permutations_cover_every_output": approx_phi_1.shape == (11, 2),
    }
    result = {
        "audit": "transport_shapley_synthetic_fixtures",
        "passed": all(checks.values()),
        "n_checks": len(checks),
        "n_passed": sum(checks.values()),
        "accessibility_outcome_read": False,
        "module_sha256": sha256(MODULE),
        "tolerances": {"absolute": ATOL, "relative": RTOL},
        "diagnostics": {
            "additive": additive_closure,
            "interactions": interaction_closure,
            "binary_coverage": coverage_closure,
            "approximate_additive": approx_closure,
            "approximation_permutations": len(orders_1),
        },
        "checks": checks,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
