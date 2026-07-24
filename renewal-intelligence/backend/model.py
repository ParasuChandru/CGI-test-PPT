"""
Interpretable churn model (FR-200).

FR-203 requires a coefficient-based or tree-based model with per-feature
attribution; deep models are explicitly excluded for v1. This uses a
standardized-feature logistic regression: the logit is exactly
    intercept + sum(coef_i * z_i)
which gives an exact, auditable additive decomposition for FR-204 (no
approximation, unlike SHAP on a black-box model) — appropriate for a
regulated-market v1 where "why did the model say this" must be answerable
with arithmetic, not a separate explainer model.
"""
from __future__ import annotations

import time
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

from . import db
from .config import MODEL_VERSION

FEATURES = [
    "premium_change_pct",
    "claims_declined_count",
    "claims_partial_count",
    "avg_settlement_days",
    "complaints_12m",
    "inbound_contacts_90d",
    "portal_logins_90d",
    "notice_opened",
    "tenure_years",
    "product_count",
    "discount_applied",
]

# Features where a HIGHER raw value is protective (reduces churn), used only
# for documentation / sanity-checking learned coefficient signs.
PROTECTIVE = {"notice_opened", "tenure_years", "product_count", "discount_applied"}


def _feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    X = df[FEATURES].copy()
    X["notice_opened"] = X["notice_opened"].astype(int)
    X["discount_applied"] = X["discount_applied"].astype(int)
    return X.astype(float)


def _expected_calibration_error(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> float:
    bins = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    n = len(y_true)
    for lo, hi in zip(bins[:-1], bins[1:]):
        mask = (y_prob >= lo) & (y_prob < hi) if hi < 1 else (y_prob >= lo) & (y_prob <= hi)
        if mask.sum() == 0:
            continue
        bin_conf = y_prob[mask].mean()
        bin_acc = y_true[mask].mean()
        ece += (mask.sum() / n) * abs(bin_conf - bin_acc)
    return float(ece)


def train(df: pd.DataFrame, model_version: str = MODEL_VERSION) -> dict:
    """Train on the churned-label dataset; persist coefficients + metrics."""
    X = _feature_frame(df)
    y = (~df["outcome_renewed"].astype(bool)).astype(int).to_numpy()  # 1 = lapsed

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=7, stratify=y
    )

    mean = X_train.mean()
    std = X_train.std().replace(0, 1.0)
    Xz_train = (X_train - mean) / std
    Xz_test = (X_test - mean) / std

    clf = LogisticRegression(max_iter=1000)
    clf.fit(Xz_train, y_train)

    y_prob_test = clf.predict_proba(Xz_test)[:, 1]
    auc = float(roc_auc_score(y_test, y_prob_test))

    k = max(1, int(0.10 * len(y_test)))
    top_k_idx = np.argsort(-y_prob_test)[:k]
    base_rate = float(y_test.mean())
    precision_at_10 = float(y_test[top_k_idx].mean() / base_rate) if base_rate > 0 else float("nan")

    calibration_error = _expected_calibration_error(y_test, y_prob_test)

    coefficients = {"__intercept__": float(clf.intercept_[0])}
    coefficients.update({f: float(c) for f, c in zip(FEATURES, clf.coef_[0])})

    with db.get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO model_meta
               (model_version, trained_at, auc, precision_at_10, calibration_error,
                base_lapse_rate, coefficients_json, feature_means_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                model_version,
                time.time(),
                auc,
                precision_at_10,
                calibration_error,
                float(y.mean()),
                db.dumps(coefficients),
                db.dumps({"mean": mean.to_dict(), "std": std.to_dict()}),
            ),
        )

    return {
        "model_version": model_version,
        "auc": auc,
        "precision_at_10": precision_at_10,
        "calibration_error": calibration_error,
        "base_lapse_rate": float(y.mean()),
        "n_train": len(X_train),
        "n_test": len(X_test),
        "coefficients": coefficients,
        "meets_targets": {
            "auc_ge_0.72": auc >= 0.72,
            "precision_at_10_ge_2.5x": precision_at_10 >= 2.5 if not np.isnan(precision_at_10) else False,
            "calibration_le_0.05": calibration_error <= 0.05,
        },
    }


def load_model_meta(model_version: str = MODEL_VERSION) -> Optional[dict]:
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM model_meta WHERE model_version = ?", (model_version,)
        ).fetchone()
    if not row:
        return None
    return {
        "model_version": row["model_version"],
        "trained_at": row["trained_at"],
        "auc": row["auc"],
        "precision_at_10": row["precision_at_10"],
        "calibration_error": row["calibration_error"],
        "base_lapse_rate": row["base_lapse_rate"],
        "coefficients": db.loads(row["coefficients_json"]),
        "feature_stats": db.loads(row["feature_means_json"]),
    }


def score_dataframe(df: pd.DataFrame, model_meta: dict) -> tuple[np.ndarray, pd.DataFrame]:
    """Return (probabilities, standardized-contribution frame) for every row."""
    X = _feature_frame(df)
    mean = pd.Series(model_meta["feature_stats"]["mean"])
    std = pd.Series(model_meta["feature_stats"]["std"])
    Xz = (X - mean) / std

    coefs = model_meta["coefficients"]
    intercept = coefs["__intercept__"]
    contrib = Xz.copy()
    for f in FEATURES:
        contrib[f] = Xz[f] * coefs[f]

    logit = intercept + contrib.sum(axis=1)
    prob = 1 / (1 + np.exp(-logit))
    return prob.to_numpy(), contrib
