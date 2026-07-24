"""
Populate the database: generate synthetic data, train the churn model,
compute attribution, generate recommendations. Equivalent to one run of the
batch scoring cycle described in FR-202/NFR-301, executed offline rather
than on a schedule for this POC.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from backend import attribution, data_gen, db, model, recommend
from backend.config import MODEL_VERSION


def run(n_policies: int = 8000) -> dict:
    print(f"Generating {n_policies} synthetic policies...")
    df = data_gen.generate(n_policies=n_policies)

    db.init_db()
    with db.get_conn() as conn:
        conn.execute("DELETE FROM decisions")
        conn.execute("DELETE FROM overrides")
        conn.execute("DELETE FROM transcripts")
        conn.execute("DELETE FROM recommendations")
        conn.execute("DELETE FROM attributions")
        conn.execute("DELETE FROM scores")
        conn.execute("DELETE FROM policies")

    df_for_db = df.copy()
    for bool_col in ["discount_applied", "notice_opened", "outcome_renewed", "funnel_contacted", "funnel_engaged"]:
        df_for_db[bool_col] = df_for_db[bool_col].astype(int)
    with db.get_conn() as conn:
        df_for_db.to_sql("policies", conn, if_exists="append", index=False)

    print("Training interpretable churn model...")
    metrics = model.train(df, model_version=MODEL_VERSION)
    print(f"  AUC={metrics['auc']:.3f}  precision@10%={metrics['precision_at_10']:.2f}x  "
          f"calibration_error={metrics['calibration_error']:.3f}")
    print(f"  meets §6.1 targets: {metrics['meets_targets']}")

    meta = model.load_model_meta(MODEL_VERSION)
    scores, contrib = model.score_dataframe(df, meta)

    import time
    now = time.time()
    with db.get_conn() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO scores (policy_id, score, model_version, scored_at) VALUES (?, ?, ?, ?)",
            [(pid, float(s), MODEL_VERSION, now) for pid, s in zip(df["policy_id"], scores)],
        )

    print("Computing driver attribution...")
    attributions = attribution.attribute(df["policy_id"], contrib)
    attr_rows = []
    for a in attributions:
        for driver, d in a["drivers"].items():
            attr_rows.append((a["policy_id"], driver, d["contribution_pct"], d["status"], MODEL_VERSION))
    with db.get_conn() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO attributions (policy_id, driver, contribution_pct, status, model_version) "
            "VALUES (?, ?, ?, ?, ?)",
            attr_rows,
        )

    print("Generating recommendations...")
    recs = recommend.build_recommendations(df, scores, attributions)
    recommend.persist_recommendations(recs)
    print(f"  {len(recs)} at-risk policies received a recommendation "
          f"({sum(r['suppressed'] for r in recs)} suppressed as duplicate discounts)")

    return metrics


if __name__ == "__main__":
    run()
