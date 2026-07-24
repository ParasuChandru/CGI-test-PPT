"""
Synthetic data generator — Stage 0 of the data access strategy (spec §5.2).

Produces a policy-level fact table matching the "minimum viable dataset"
(§5.1): policy attributes, premium history, claims history, interaction
events, and the renewed/lapsed outcome label. Relationships between features
and the outcome are seeded deliberately (not random) so a churn model trained
on this data recovers meaningful, explainable coefficients — this is a
methodology proof, not a claim about any real book of business.

"competitive_gap" is intentionally NOT modelled here: the spec has no
approved market/benchmark data source in v1 (FR-105, blocked). Manufacturing
a fake competitive-pricing signal would misrepresent what Stage 0 can show.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

LINES = ["Motor", "Home", "Life", "Travel"]
SEGMENTS = ["Retail", "SME"]
REGIONS = ["North", "South", "East", "West"]
COVER_LEVELS = ["Basic", "Standard", "Premium"]

BASE_PREMIUM = {"Motor": 650, "Home": 480, "Life": 900, "Travel": 120}
LINE_BASE_LAPSE_LOGIT = {"Motor": -0.55, "Home": -0.75, "Life": -0.30, "Travel": -0.10}


def generate(n_policies: int = 8000, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    line = rng.choice(LINES, size=n_policies, p=[0.42, 0.33, 0.15, 0.10])
    segment = rng.choice(SEGMENTS, size=n_policies, p=[0.7, 0.3])
    region = rng.choice(REGIONS, size=n_policies)
    cover_level = rng.choice(COVER_LEVELS, size=n_policies, p=[0.35, 0.45, 0.20])

    tenure_years = np.clip(rng.exponential(scale=4.0, size=n_policies), 0, 20).round(1)
    product_count = rng.choice([1, 2, 3, 4], size=n_policies, p=[0.55, 0.28, 0.12, 0.05])

    base_premium = np.array([BASE_PREMIUM[l] for l in line])
    cover_multiplier = pd.Series(cover_level).map({"Basic": 0.8, "Standard": 1.0, "Premium": 1.35}).to_numpy()
    sum_insured = (base_premium * cover_multiplier * rng.uniform(8, 14, size=n_policies)).round(0)
    prior_premium = (base_premium * cover_multiplier * rng.uniform(0.9, 1.1, size=n_policies)).round(2)

    # Premium change: mostly modest, with a fat tail of "shock" increases.
    is_shock = rng.random(n_policies) < 0.18
    premium_change_pct = np.where(
        is_shock,
        rng.uniform(0.15, 0.45, size=n_policies),
        rng.normal(0.02, 0.05, size=n_policies),
    )
    renewal_quote = (prior_premium * (1 + premium_change_pct)).round(2)

    # Claims history
    claim_count_3y = rng.poisson(lam=np.where(line == "Motor", 0.55, 0.30), size=n_policies)
    claims_declined_count = rng.binomial(claim_count_3y, 0.18)
    claims_partial_count = rng.binomial(claim_count_3y, 0.15)
    last_claim_days_before_renewal = np.where(
        claim_count_3y > 0, rng.integers(5, 1095, size=n_policies), -1
    )
    avg_settlement_days = np.where(
        claim_count_3y > 0,
        np.clip(rng.normal(21, 12, size=n_policies), 3, 120).round(1),
        0.0,
    )

    # Interaction / engagement signals
    portal_logins_90d = rng.poisson(lam=2.2, size=n_policies)
    notice_opened = rng.random(n_policies) < np.clip(0.55 + 0.03 * tenure_years, 0.1, 0.95)
    inbound_contacts_90d = rng.poisson(lam=0.6, size=n_policies)
    complaints_12m = rng.poisson(lam=0.12, size=n_policies)

    # Automatic discounts (loyalty / no-claims) applied by separate systems
    # (spec §1.3, §8.3) — recorded so the recommendation engine can avoid
    # duplicating them (FR-405).
    no_claims_eligible = claim_count_3y == 0
    loyalty_eligible = tenure_years >= 3
    discount_source = np.select(
        [no_claims_eligible & (rng.random(n_policies) < 0.7),
         loyalty_eligible & (rng.random(n_policies) < 0.4)],
        ["no_claims", "loyalty"],
        default="none",
    )
    discount_applied = discount_source != "none"

    # --- Latent churn logit -----------------------------------------------
    line_base = np.array([LINE_BASE_LAPSE_LOGIT[l] for l in line])
    logit = (
        line_base
        + 3.8 * premium_change_pct
        + 0.55 * claims_declined_count
        + 0.32 * claims_partial_count
        + 0.020 * avg_settlement_days
        + 0.65 * complaints_12m
        + 0.28 * inbound_contacts_90d
        - 0.18 * portal_logins_90d
        - 0.45 * notice_opened.astype(float)
        - 0.08 * tenure_years
        - 0.14 * product_count
        - 0.8 * discount_applied.astype(float)
        + rng.normal(0, 0.34, size=n_policies)  # unexplained variance
    )
    churn_prob_true = 1 / (1 + np.exp(-logit))
    lapsed = rng.random(n_policies) < churn_prob_true
    renewed = ~lapsed

    df = pd.DataFrame(
        {
            "policy_id": [f"POL-{i:06d}" for i in range(1, n_policies + 1)],
            "line": line,
            "segment": segment,
            "region": region,
            "cover_level": cover_level,
            "tenure_years": tenure_years,
            "product_count": product_count,
            "sum_insured": sum_insured,
            "prior_premium": prior_premium,
            "renewal_quote": renewal_quote,
            "premium_change_pct": premium_change_pct.round(4),
            "discount_applied": discount_applied,
            "discount_source": discount_source,
            "claim_count_3y": claim_count_3y,
            "claims_declined_count": claims_declined_count,
            "claims_partial_count": claims_partial_count,
            "last_claim_days_before_renewal": last_claim_days_before_renewal,
            "avg_settlement_days": avg_settlement_days,
            "portal_logins_90d": portal_logins_90d,
            "notice_opened": notice_opened,
            "inbound_contacts_90d": inbound_contacts_90d,
            "complaints_12m": complaints_12m,
            "outcome_renewed": renewed,
            "final_bound": np.where(renewed, renewal_quote, np.nan),
        }
    )

    # Renewal funnel stage (FR-501): everyone is "up_for_renewal"; a subset
    # were contacted proactively; of those, a subset engaged; renewal outcome
    # already determined above and is consistent with engagement likelihood.
    contacted = rng.random(n_policies) < 0.65
    engaged = contacted & (rng.random(n_policies) < np.where(renewed, 0.8, 0.35))
    df["funnel_contacted"] = contacted
    df["funnel_engaged"] = engaged

    # Spread policies across the last 12 renewal months so portfolio
    # analytics (FR-503, FR-504) can show a trend, not just a single batch.
    months_ago = rng.integers(0, 12, size=n_policies)
    periods = pd.period_range(end=pd.Timestamp.today(), periods=12, freq="M")
    df["renewal_month"] = [str(periods[-1 - m]) for m in months_ago]

    return df
