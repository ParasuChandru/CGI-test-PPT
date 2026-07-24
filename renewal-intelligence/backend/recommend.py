"""
Recommendation engine (FR-400).

For every at-risk policy: pick an action by dominant driver (non-price
unless the driver is genuinely premium shock — FR-402), apply a concession
ceiling (FR-404), suppress anything that would duplicate an automatic
discount already on the policy (FR-405), assign an A/B holdout group
(FR-408), and attach save-probability / expected-value estimates (FR-403).
Nothing here is auto-released — every row starts life as 'pending' and only
moves via the approval workflow (FR-406/FR-407).
"""
from __future__ import annotations

import time
import uuid
from typing import Optional

import numpy as np
import pandas as pd

from . import db
from .config import (
    ACTION_BY_DRIVER,
    ASSUMED_TREATMENT_UPLIFT,
    AT_RISK_THRESHOLD,
    CONCESSION_CEILINGS,
    DEFAULT_CEILING,
    HOLDOUT_FRACTION,
)

ACCEPTABLE_PREMIUM_INCREASE = 0.08


def _ceiling_for(line: str, segment: str) -> float:
    return CONCESSION_CEILINGS.get((line, segment), DEFAULT_CEILING)


def build_recommendations(
    df: pd.DataFrame, scores: np.ndarray, attributions: list[dict], seed: int = 11
) -> list[dict]:
    rng = np.random.default_rng(seed)
    df = df.reset_index(drop=True)
    attr_by_policy = {a["policy_id"]: a for a in attributions}

    recs = []
    for i, row in df.iterrows():
        score = float(scores[i])
        if score < AT_RISK_THRESHOLD:
            continue

        policy_id = row["policy_id"]
        attr = attr_by_policy[policy_id]
        driver = attr["dominant_driver"]
        driver_key = driver if driver in ACTION_BY_DRIVER else "premium_shock"
        action_meta = ACTION_BY_DRIVER.get(driver_key, {
            "action": "Route to underwriter for manual review (no dominant driver identified)",
            "is_price_action": False,
        })

        is_price_action = bool(action_meta["is_price_action"])
        concession_value = 0.0
        suppressed = False
        suppressed_reason = None
        action_text = action_meta["action"]

        if is_price_action:
            needed_pct = max(0.0, float(row["premium_change_pct"]) - ACCEPTABLE_PREMIUM_INCREASE)
            ceiling = _ceiling_for(row["line"], row["segment"])
            concession_pct = min(needed_pct, ceiling)
            concession_value = round(concession_pct * float(row["renewal_quote"]), 2)

            if bool(row["discount_applied"]):
                suppressed = True
                suppressed_reason = (
                    f"Automatic '{row['discount_source']}' discount already applied to this "
                    "policy; a further price concession would duplicate it (FR-405)."
                )
                concession_value = 0.0
                action_text = (
                    "No additional concession — automatic discount already applied. "
                    "Escalate to underwriter if premium shock persists."
                )

        uplift = ASSUMED_TREATMENT_UPLIFT.get(driver_key, 0.1)
        save_probability = round(score * uplift, 4) if not suppressed else 0.0
        expected_value = round(save_probability * float(row["renewal_quote"]) - concession_value, 2)

        # A/B holdout (FR-408)
        holdout_group = "control" if rng.random() < HOLDOUT_FRACTION else "treatment"

        # Demo-only simulated outcome to illustrate uplift measurement.
        if holdout_group == "control" or suppressed:
            simulated_outcome_renewed = int(row["outcome_renewed"])
        else:
            treated_lapse_prob = score * (1 - uplift)
            simulated_outcome_renewed = int(rng.random() > treated_lapse_prob)

        recs.append(
            {
                "rec_id": f"REC-{policy_id}-{uuid.uuid4().hex[:6]}",
                "policy_id": policy_id,
                "dominant_driver": driver,
                "action": action_text,
                "is_price_action": is_price_action,
                "concession_value": concession_value,
                "save_probability": save_probability,
                "expected_value": expected_value,
                "suppressed": suppressed,
                "suppressed_reason": suppressed_reason,
                "holdout_group": holdout_group,
                "status": "pending",
                "simulated_outcome_renewed": simulated_outcome_renewed,
                "created_at": time.time(),
            }
        )
    return recs


def persist_recommendations(recs: list[dict]) -> None:
    with db.get_conn() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO recommendations
               (rec_id, policy_id, dominant_driver, action, is_price_action,
                concession_value, save_probability, expected_value,
                suppressed, suppressed_reason, holdout_group, status,
                simulated_outcome_renewed, created_at)
               VALUES (:rec_id, :policy_id, :dominant_driver, :action, :is_price_action,
                       :concession_value, :save_probability, :expected_value,
                       :suppressed, :suppressed_reason, :holdout_group, :status,
                       :simulated_outcome_renewed, :created_at)""",
            recs,
        )


def record_decision(rec_id: str, actor_role: str, actor_id: str, decision: str, reason: Optional[str]) -> None:
    """decision in {'approved', 'rejected', 'modified'} — FR-406/FR-407."""
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE recommendations SET status = ? WHERE rec_id = ?", (decision, rec_id)
        )
        conn.execute(
            """INSERT INTO decisions (rec_id, actor_role, actor_id, decision, reason, decided_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (rec_id, actor_role, actor_id, decision, reason, time.time()),
        )
