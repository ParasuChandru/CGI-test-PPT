"""Portfolio analytics (FR-500)."""
from __future__ import annotations

import math

import pandas as pd

from . import db


def _policies_df() -> pd.DataFrame:
    with db.get_conn() as conn:
        return pd.read_sql_query("SELECT * FROM policies", conn)


def _scores_df() -> pd.DataFrame:
    with db.get_conn() as conn:
        return pd.read_sql_query("SELECT * FROM scores", conn)


def _attributions_df() -> pd.DataFrame:
    with db.get_conn() as conn:
        return pd.read_sql_query("SELECT * FROM attributions", conn)


def _recommendations_df() -> pd.DataFrame:
    with db.get_conn() as conn:
        return pd.read_sql_query("SELECT * FROM recommendations", conn)


def funnel() -> dict:
    """FR-501: up_for_renewal -> contacted -> engaged -> renewed, loss at each stage.

    Stages are strictly nested (each a subset of the prior one) so "loss at
    each stage" is meaningful. "renewed" here means renewed *among those
    engaged* — most policies in this market auto-renew without any contact
    at all (§1.3 excludes rebuilding that batch process), so the book-wide
    renewal rate is a different number, reported separately in
    lapse_rate_breakdown().overall_lapse_rate.
    """
    df = _policies_df()
    contacted = df["funnel_contacted"].astype(bool)
    engaged = contacted & df["funnel_engaged"].astype(bool)
    renewed_among_engaged = engaged & df["outcome_renewed"].astype(bool)

    stages = [
        ("up_for_renewal", len(df)),
        ("contacted", int(contacted.sum())),
        ("engaged", int(engaged.sum())),
        ("renewed (of engaged)", int(renewed_among_engaged.sum())),
    ]
    out = []
    prev = None
    for name, count in stages:
        loss = None if prev is None else prev - count
        out.append({"stage": name, "count": count, "loss_from_prior": loss})
        prev = count
    return {
        "funnel": out,
        "total_policies": len(df),
        "book_wide_renewal_rate": round(float(df["outcome_renewed"].mean()), 4),
    }


def lapse_rate_breakdown() -> dict:
    """FR-502: lapse rate by line, segment, tenure band, premium band, region."""
    df = _policies_df()
    df["lapsed"] = ~df["outcome_renewed"].astype(bool)
    df["tenure_band"] = pd.cut(
        df["tenure_years"], bins=[-0.1, 1, 3, 7, 100], labels=["0-1y", "1-3y", "3-7y", "7y+"]
    )
    df["premium_band"] = pd.cut(
        df["renewal_quote"],
        bins=[0, 300, 600, 1000, 1e9],
        labels=["<300", "300-600", "600-1000", "1000+"],
    )

    def rate_by(col):
        g = df.groupby(col, observed=True)["lapsed"].agg(["mean", "count"])
        return [
            {"segment": str(idx), "lapse_rate": round(float(row["mean"]), 4), "n": int(row["count"])}
            for idx, row in g.iterrows()
        ]

    return {
        "by_line": rate_by("line"),
        "by_segment": rate_by("segment"),
        "by_tenure_band": rate_by("tenure_band"),
        "by_premium_band": rate_by("premium_band"),
        "by_region": rate_by("region"),
        "overall_lapse_rate": round(float(df["lapsed"].mean()), 4),
    }


def driver_mix(trend: bool = True) -> dict:
    """FR-503: driver mix across the book, trended over time."""
    attr = _attributions_df()
    pol = _policies_df()[["policy_id", "renewal_month"]]

    dominant = (
        attr.sort_values("contribution_pct", ascending=False)
        .dropna(subset=["contribution_pct"])
        .groupby("policy_id")
        .first()
        .reset_index()[["policy_id", "driver"]]
    )
    merged = dominant.merge(pol, on="policy_id", how="left")

    overall = merged["driver"].value_counts(normalize=True).round(4).to_dict()

    result = {"overall_mix": overall}
    if trend:
        by_month = (
            merged.groupby(["renewal_month", "driver"]).size().unstack(fill_value=0)
        )
        by_month_pct = by_month.div(by_month.sum(axis=1), axis=0).round(4)
        result["trend"] = by_month_pct.reset_index().to_dict(orient="records")
    return result


def premium_at_risk_and_saved() -> dict:
    """FR-504: premium at risk (annualised) and premium saved, by period."""
    pol = _policies_df()
    scores = _scores_df()
    recs = _recommendations_df()

    merged = pol.merge(scores, on="policy_id", how="left")
    merged["at_risk"] = merged["score"].fillna(0) >= 0.35

    at_risk_by_month = (
        merged[merged["at_risk"]]
        .groupby("renewal_month")["renewal_quote"]
        .sum()
        .round(2)
        .reset_index()
        .rename(columns={"renewal_quote": "premium_at_risk"})
    )

    approved = recs[recs["status"] == "approved"].merge(
        pol[["policy_id", "renewal_month", "renewal_quote"]], on="policy_id", how="left"
    )
    # "Saved" = renewal premium retained on approved recommendations whose
    # simulated outcome is renewed, net of concession cost.
    approved["saved_amount"] = 0.0
    saved_mask = approved["simulated_outcome_renewed"] == 1
    approved.loc[saved_mask, "saved_amount"] = (
        approved.loc[saved_mask, "renewal_quote"] - approved.loc[saved_mask, "concession_value"]
    )
    saved_by_month = (
        approved.groupby("renewal_month")["saved_amount"]
        .sum()
        .round(2)
        .reset_index()
        .rename(columns={"saved_amount": "premium_saved"})
    )

    return {
        "premium_at_risk_by_month": at_risk_by_month.to_dict(orient="records"),
        "premium_saved_by_month": saved_by_month.to_dict(orient="records"),
        "total_premium_at_risk": round(float(at_risk_by_month["premium_at_risk"].sum()), 2)
        if len(at_risk_by_month) else 0.0,
        "total_premium_saved": round(float(saved_by_month["premium_saved"].sum()), 2)
        if len(saved_by_month) else 0.0,
    }


def cohort_comparison() -> dict:
    """FR-505 (Should): retention by tenure-band cohort, as a proxy for
    year-on-year acquisition cohort comparison (the synthetic dataset is a
    single snapshot, so true multi-year cohort tracking needs Stage 2+ data)."""
    df = _policies_df()
    df["cohort"] = pd.cut(
        df["tenure_years"], bins=[-0.1, 1, 2, 3, 5, 100],
        labels=["<1y", "1-2y", "2-3y", "3-5y", "5y+"],
    )
    g = df.groupby("cohort", observed=True)["outcome_renewed"].agg(["mean", "count"])
    return [
        {"cohort": str(idx), "retention_rate": round(float(row["mean"]), 4), "n": int(row["count"])}
        for idx, row in g.iterrows()
    ]


def holdout_uplift() -> dict:
    """FR-408 / §6.2: measured lapse-rate difference, treatment vs control."""
    recs = _recommendations_df()
    scored = recs[recs["holdout_group"].isin(["treatment", "control"]) & ~recs["suppressed"].astype(bool)]
    if scored.empty:
        return {"available": False, "reason": "No holdout-eligible recommendations yet."}

    def lapse_rate(group_df):
        n = len(group_df)
        lapsed = int((group_df["simulated_outcome_renewed"] == 0).sum())
        return lapsed, n

    t_lapsed, t_n = lapse_rate(scored[scored["holdout_group"] == "treatment"])
    c_lapsed, c_n = lapse_rate(scored[scored["holdout_group"] == "control"])
    if t_n == 0 or c_n == 0:
        return {"available": False, "reason": "Insufficient data in one arm."}

    p_t, p_c = t_lapsed / t_n, c_lapsed / c_n
    p_pool = (t_lapsed + c_lapsed) / (t_n + c_n)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / t_n + 1 / c_n)) if 0 < p_pool < 1 else 0
    z = (p_c - p_t) / se if se > 0 else 0.0
    # two-sided p-value from z, via error function (no scipy dependency)
    p_value = math.erfc(abs(z) / math.sqrt(2))

    return {
        "available": True,
        "treatment_lapse_rate": round(p_t, 4),
        "treatment_n": t_n,
        "control_lapse_rate": round(p_c, 4),
        "control_n": c_n,
        "relative_reduction": round((p_c - p_t) / p_c, 4) if p_c > 0 else None,
        "z_score": round(z, 3),
        "p_value": round(p_value, 4),
        "statistically_significant_at_0.05": p_value < 0.05,
    }


def approval_rate() -> dict:
    """§6.2: offer approval rate target >= 60%."""
    recs = _recommendations_df()
    decided = recs[recs["status"].isin(["approved", "rejected", "modified"])]
    if decided.empty:
        return {"available": False, "reason": "No decisions recorded yet."}
    rate = float((decided["status"] == "approved").mean())
    return {
        "available": True,
        "approval_rate": round(rate, 4),
        "n_decided": len(decided),
        "meets_target_ge_0.60": rate >= 0.60,
    }


def export_policies_csv() -> str:
    """FR-506: CSV export of policy-level scores/attributions/recommendations."""
    pol = _policies_df()
    scores = _scores_df()
    recs = _recommendations_df()
    dominant = (
        _attributions_df()
        .dropna(subset=["contribution_pct"])
        .sort_values("contribution_pct", ascending=False)
        .groupby("policy_id")
        .first()
        .reset_index()[["policy_id", "driver"]]
        .rename(columns={"driver": "dominant_driver"})
    )
    merged = pol.merge(scores, on="policy_id", how="left").merge(
        dominant, on="policy_id", how="left"
    ).merge(
        recs[["policy_id", "action", "concession_value", "status", "holdout_group"]],
        on="policy_id",
        how="left",
    )
    return merged.to_csv(index=False)
