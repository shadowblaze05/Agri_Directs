"""Criteria definition and AHP weight construction for crop recommendation."""

from __future__ import annotations

from typing import Dict, List

import numpy as np


def ahp_method(dataset, wd="mean"):
    """Compute AHP weights using the mean-normalized method without importing the full pyDecision package."""
    dataset = np.asarray(dataset, dtype=float)
    if dataset.ndim != 2:
        raise ValueError("AHP matrix must be 2D")

    if dataset.shape[0] != dataset.shape[1]:
        raise ValueError("AHP matrix must be square")

    if wd not in {"m", "mean"}:
        raise ValueError("This implementation supports the mean-normalized AHP method only")

    normalized = dataset / np.sum(dataset, axis=0, keepdims=True)
    weights = np.mean(normalized, axis=1)
    weights = weights / np.sum(weights)

    eigen_vector = np.sum(dataset * weights, axis=1) / weights
    lambda_max = float(np.mean(eigen_vector))
    ri_values = {1: 0.0, 2: 0.0, 3: 0.58, 4: 0.9, 5: 1.12, 6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49}
    n = dataset.shape[0]
    consistency_index = (lambda_max - n) / (n - 1) if n > 1 else 0.0
    consistency_ratio = consistency_index / ri_values.get(n, 1.12)
    return weights, consistency_ratio


CRITERIA = [
    "demand_strength",
    "supply_stability",
    "seasonal_fit",
    "price_opportunity",
    "risk_balance",
]


def build_pairwise_matrix():
    """Return the pairwise comparison matrix used for AHP weighting."""
    return np.array(
        [
            [1.0, 3.0, 5.0, 2.0, 4.0],
            [1 / 3, 1.0, 3.0, 1.0, 2.0],
            [1 / 5, 1 / 3, 1.0, 1 / 2, 1.0],
            [1 / 2, 1.0, 2.0, 1.0, 2.0],
            [1 / 4, 1 / 2, 1.0, 1 / 2, 1.0],
        ],
        dtype=float,
    )


class CriteriaBuilder:
    """Build and expose AHP criteria weights for downstream crop scoring."""

    def __init__(self):
        self.matrix = build_pairwise_matrix()
        self.weights, self.consistency_ratio = ahp_method(self.matrix, wd="mean")

    def as_dict(self) -> Dict[str, float]:
        return {criterion: round(float(weight), 4) for criterion, weight in zip(CRITERIA, self.weights)}

    def as_array(self):
        return self.weights

    @property
    def criterion_types(self):
        return ["max", "max", "max", "max", "max"]


def build_criteria_weights() -> Dict[str, float]:
    return CriteriaBuilder().as_dict()
