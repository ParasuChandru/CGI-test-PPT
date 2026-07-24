"""
Configuration for the Renewal Intelligence Stage 0 POC.

Driver taxonomy and concession ceilings are data, not code (FR-305) so they
can be extended without touching attribution.py / recommend.py.
"""

MODEL_VERSION = "poc-0.1.0"

# --- Driver taxonomy (FR-301, FR-302) ------------------------------------
# "competitive_gap" is defined per spec but has NO feature backing it in this
# POC: FR-105 (market/competitive reference data) is priority "Could" and
# blocked pending client input (see requirements doc §8, ❗). Rather than let
# a Must-priority driver silently attribute to noise, it is kept in the
# taxonomy with an explicit "insufficient_data" status and is never selected
# as a dominant driver until a real feature feeds it.
DRIVER_TAXONOMY = {
    "premium_shock": {
        "label": "Premium shock",
        "features": ["premium_change_pct"],
        "status": "active",
    },
    "claim_experience": {
        "label": "Claim experience",
        "features": ["claims_declined_count", "claims_partial_count", "avg_settlement_days"],
        "status": "active",
    },
    "service_friction": {
        "label": "Service friction",
        "features": ["complaints_12m", "inbound_contacts_90d"],
        "status": "active",
    },
    "disengagement": {
        "label": "Disengagement",
        "features": ["portal_logins_90d", "notice_opened"],
        "status": "active",
    },
    "competitive_gap": {
        "label": "Competitive gap",
        "features": [],
        "status": "insufficient_data",  # blocked on FR-105 / §8.1
    },
}

FEATURE_TO_DRIVER = {
    f: driver
    for driver, spec in DRIVER_TAXONOMY.items()
    for f in spec["features"]
}

# --- Recommendation actions (FR-401, FR-402) -----------------------------
# Service- and claim-driven churn deliberately map to non-price actions.
ACTION_BY_DRIVER = {
    "premium_shock": {
        "action": "Offer a tiered premium concession, capped at the configured ceiling",
        "is_price_action": True,
    },
    "claim_experience": {
        "action": "Proactive claims-service outreach and fast-track settlement review",
        "is_price_action": False,
    },
    "service_friction": {
        "action": "Priority service-recovery contact from a senior agent",
        "is_price_action": False,
    },
    "disengagement": {
        "action": "Re-engagement nudge and guided portal walkthrough",
        "is_price_action": False,
    },
    "competitive_gap": {
        "action": "Flag for underwriter review (insufficient data to recommend an action)",
        "is_price_action": False,
    },
}

# --- Concession ceilings (FR-404) ----------------------------------------
# Percent of renewal premium, by line and segment.
CONCESSION_CEILINGS = {
    ("Motor", "Retail"): 0.08,
    ("Motor", "SME"): 0.06,
    ("Home", "Retail"): 0.07,
    ("Home", "SME"): 0.05,
    ("Life", "Retail"): 0.04,
    ("Travel", "Retail"): 0.10,
}
DEFAULT_CEILING = 0.05

# --- A/B holdout (FR-408) -------------------------------------------------
HOLDOUT_FRACTION = 0.20  # 20% of at-risk policies withheld as control
AT_RISK_THRESHOLD = 0.35  # churn probability above which a policy is "at risk"

# Assumed treatment effect (relative reduction in churn probability) used
# only to *simulate* an outcome for the holdout demo — in production this
# would be measured, not assumed (see FR-408 rationale in the spec).
ASSUMED_TREATMENT_UPLIFT = {
    "premium_shock": 0.35,
    "claim_experience": 0.25,
    "service_friction": 0.30,
    "disengagement": 0.20,
    "competitive_gap": 0.05,
}

# --- RBAC (NFR-101 to NFR-104) --------------------------------------------
# Resolves a spec ambiguity found in review: the requirements doc gives the
# Manager "override scores" and the Underwriter only "inspect and challenge"
# (§2.1), while FR-206 says "allow an underwriter to override a score".
# Decision for this build: both Manager and Underwriter may override,
# since overriding *is* how an underwriter exercises a challenge — but every
# override is logged with actor role for audit (NFR-106).
ROLES = ["manager", "underwriter", "service_agent", "analyst", "pricing", "customer"]

CAN_OVERRIDE_SCORE = {"manager", "underwriter"}
CAN_VIEW_RAW_SCORE = {"manager", "underwriter"}
CAN_VIEW_MODEL_INTERNALS = {"manager", "pricing"}  # NFR-104; adds a Pricing tier
CAN_APPROVE_RECOMMENDATION = {"manager", "underwriter"}
CAN_VIEW_AGGREGATE_ANALYTICS = {"manager", "underwriter", "analyst"}
CAN_VIEW_CUSTOMER_EXPLANATION_ONLY = {"service_agent", "customer"}
