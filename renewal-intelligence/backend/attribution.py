"""
Driver attribution (FR-300): rolls per-feature logit contributions up to the
5-category taxonomy in config.py and picks a dominant driver per policy.

Only the contribution actually pushing a policy TOWARD lapsing counts toward
a driver's share (a bucket that is net-protective for a given policy is not
"why" that policy is at risk). If no taxonomy bucket has positive
attributable risk once baseline/noise is accounted for, the policy is
labelled "unattributed" rather than forced into a spurious dominant driver —
this is what FR-301's "classify the dominant driver" should mean in
practice: a driver is only assigned when there is something to point to.
"""
from __future__ import annotations

import pandas as pd

from .config import DRIVER_TAXONOMY, FEATURE_TO_DRIVER

ACTIVE_DRIVERS = [d for d, spec in DRIVER_TAXONOMY.items() if spec["status"] == "active"]


def attribute(policy_ids: pd.Series, contrib: pd.DataFrame) -> list[dict]:
    results = []
    for pos, policy_id in enumerate(policy_ids):
        row = contrib.iloc[pos]
        driver_sum = {}
        for driver in ACTIVE_DRIVERS:
            feats = DRIVER_TAXONOMY[driver]["features"]
            driver_sum[driver] = float(sum(row[f] for f in feats))

        positive_mass = {d: max(0.0, v) for d, v in driver_sum.items()}
        total_positive = sum(positive_mass.values())

        entry = {"policy_id": policy_id, "drivers": {}}
        if total_positive <= 1e-9:
            entry["dominant_driver"] = "unattributed"
            for d in ACTIVE_DRIVERS:
                entry["drivers"][d] = {"contribution_pct": 0.0, "status": "active"}
        else:
            for d in ACTIVE_DRIVERS:
                entry["drivers"][d] = {
                    "contribution_pct": round(100 * positive_mass[d] / total_positive, 1),
                    "status": "active",
                }
            entry["dominant_driver"] = max(positive_mass, key=positive_mass.get)

        # Competitive gap always reported, always flagged as blocked (§8.1/FR-105).
        entry["drivers"]["competitive_gap"] = {"contribution_pct": None, "status": "insufficient_data"}
        results.append(entry)
    return results


def feature_contribution_row(policy_row_contrib: pd.Series) -> dict:
    """Full per-feature breakdown for a single policy, for underwriter drill-down (FR-204)."""
    out = {}
    for feature, value in policy_row_contrib.items():
        driver = FEATURE_TO_DRIVER.get(feature, "other/baseline")
        out[feature] = {"logit_contribution": round(float(value), 4), "driver": driver}
    return out
