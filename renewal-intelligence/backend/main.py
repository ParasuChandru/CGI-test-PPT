"""
FastAPI wiring for the Renewal Intelligence Stage 0 POC.

Every route that touches score/attribution/recommendation/model data is
role-gated server-side (NFR-101) and logged (NFR-106). See config.py for the
role/permission matrix and the ambiguity resolutions made during spec
review (override rights, Pricing tier, customer-facing score exposure).
"""
from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import analytics, agent as agent_module, db, model, recommend
from .auth import audited, require_role
from .config import (
    CAN_APPROVE_RECOMMENDATION,
    CAN_OVERRIDE_SCORE,
    CAN_VIEW_AGGREGATE_ANALYTICS,
    CAN_VIEW_CUSTOMER_EXPLANATION_ONLY,
    CAN_VIEW_MODEL_INTERNALS,
    CAN_VIEW_RAW_SCORE,
    MODEL_VERSION,
)
from .schemas import AgentMessageRequest, AgentStartRequest, DecisionRequest, OverrideRequest

app = FastAPI(title="Renewal Intelligence (Stage 0 POC)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _ensure_seeded():
    db.init_db()


@app.get("/health")
def health():
    return {"status": "ok", "seeded": db.is_seeded()}


# --- Model (FR-200, NFR-104) ----------------------------------------------

@app.get("/model/performance")
def model_performance(actor=Depends(require_role(*CAN_VIEW_AGGREGATE_ANALYTICS, *CAN_VIEW_MODEL_INTERNALS))):
    audited(actor, "view", "model/performance")
    meta = model.load_model_meta(MODEL_VERSION)
    if not meta:
        raise HTTPException(404, "Model not trained yet — run scripts/seed.py")
    return {
        "model_version": meta["model_version"],
        "trained_at": meta["trained_at"],
        "auc": meta["auc"],
        "precision_at_10": meta["precision_at_10"],
        "calibration_error": meta["calibration_error"],
        "base_lapse_rate": meta["base_lapse_rate"],
        "meets_targets": {
            "auc_ge_0.72": meta["auc"] >= 0.72,
            "precision_at_10_ge_2.5x": meta["precision_at_10"] >= 2.5,
            "calibration_le_0.05": meta["calibration_error"] <= 0.05,
        },
    }


@app.get("/model/internals")
def model_internals(actor=Depends(require_role(*CAN_VIEW_MODEL_INTERNALS))):
    audited(actor, "view", "model/internals")
    meta = model.load_model_meta(MODEL_VERSION)
    if not meta:
        raise HTTPException(404, "Model not trained yet — run scripts/seed.py")
    return {"model_version": meta["model_version"], "coefficients": meta["coefficients"]}


# --- Policies (FR-200, FR-300, NFR-103) -----------------------------------

@app.get("/policies")
def list_policies(
    at_risk_only: bool = True,
    limit: int = 200,
    actor=Depends(require_role(*CAN_VIEW_RAW_SCORE)),
):
    audited(actor, "list", "policies")
    with db.get_conn() as conn:
        q = """
            SELECT p.policy_id, p.line, p.segment, p.region, p.tenure_years,
                   p.renewal_quote, p.premium_change_pct, s.score,
                   (SELECT driver FROM attributions a WHERE a.policy_id = p.policy_id
                    AND a.contribution_pct IS NOT NULL
                    ORDER BY a.contribution_pct DESC LIMIT 1) AS dominant_driver
            FROM policies p JOIN scores s ON s.policy_id = p.policy_id
        """
        if at_risk_only:
            q += " WHERE s.score >= 0.35"
        q += " ORDER BY s.score DESC LIMIT ?"
        rows = conn.execute(q, (limit,)).fetchall()
    return [dict(r) for r in rows]


@app.get("/policies/{policy_id}")
def policy_detail(policy_id: str, actor=Depends(require_role(*CAN_VIEW_RAW_SCORE))):
    audited(actor, "view", f"policy/{policy_id}")
    with db.get_conn() as conn:
        policy = conn.execute("SELECT * FROM policies WHERE policy_id = ?", (policy_id,)).fetchone()
        if not policy:
            raise HTTPException(404, "Policy not found")
        score = conn.execute("SELECT * FROM scores WHERE policy_id = ?", (policy_id,)).fetchone()
        drivers = conn.execute("SELECT * FROM attributions WHERE policy_id = ?", (policy_id,)).fetchall()
        recs = conn.execute(
            "SELECT * FROM recommendations WHERE policy_id = ? ORDER BY created_at DESC", (policy_id,)
        ).fetchall()
        overrides = conn.execute(
            "SELECT * FROM overrides WHERE policy_id = ? ORDER BY created_at DESC", (policy_id,)
        ).fetchall()
    return {
        "policy": dict(policy),
        "score": dict(score) if score else None,
        "drivers": [dict(d) for d in drivers],
        "recommendations": [dict(r) for r in recs],
        "overrides": [dict(o) for o in overrides],
    }


@app.get("/policies/{policy_id}/customer-view")
def policy_customer_view(policy_id: str, actor=Depends(require_role(*CAN_VIEW_CUSTOMER_EXPLANATION_ONLY))):
    """NFR-103 / NFR-205 extended to the customer surface: reason and action
    only — never the raw score or model internals."""
    audited(actor, "view", f"policy/{policy_id}/customer-view")
    with db.get_conn() as conn:
        rec = conn.execute(
            "SELECT * FROM recommendations WHERE policy_id = ? AND status = 'approved' "
            "ORDER BY created_at DESC LIMIT 1",
            (policy_id,),
        ).fetchone()
    if not rec:
        return {"policy_id": policy_id, "has_offer": False}
    return {
        "policy_id": policy_id,
        "has_offer": True,
        "action": rec["action"],
        "dominant_driver": rec["dominant_driver"],
        "concession_value": rec["concession_value"] if rec["is_price_action"] else None,
    }


@app.post("/policies/{policy_id}/override")
def override_score(policy_id: str, body: OverrideRequest, actor=Depends(require_role(*CAN_OVERRIDE_SCORE))):
    """FR-206: mandatory reason, logged, feeds retraining review."""
    with db.get_conn() as conn:
        current = conn.execute("SELECT score FROM scores WHERE policy_id = ?", (policy_id,)).fetchone()
        if not current:
            raise HTTPException(404, "Policy has no score to override")
        conn.execute(
            """INSERT INTO overrides (policy_id, actor_role, actor_id, original_score, override_score, reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?, strftime('%s','now'))""",
            (policy_id, actor["role"], actor["user_id"], current["score"], body.override_score, body.reason),
        )
    audited(actor, "override", f"policy/{policy_id}")
    return {"status": "recorded", "policy_id": policy_id, "override_score": body.override_score}


# --- Recommendations (FR-400) --------------------------------------------

@app.get("/recommendations")
def list_recommendations(status: str = "pending", actor=Depends(require_role(*CAN_APPROVE_RECOMMENDATION))):
    audited(actor, "list", "recommendations")
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM recommendations WHERE status = ? ORDER BY created_at DESC LIMIT 200", (status,)
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/recommendations/{rec_id}/decision")
def decide_recommendation(rec_id: str, body: DecisionRequest, actor=Depends(require_role(*CAN_APPROVE_RECOMMENDATION))):
    """FR-406/FR-407: no auto-release; every decision recorded for outcome tracking."""
    with db.get_conn() as conn:
        rec = conn.execute("SELECT * FROM recommendations WHERE rec_id = ?", (rec_id,)).fetchone()
    if not rec:
        raise HTTPException(404, "Recommendation not found")
    if rec["holdout_group"] == "control":
        raise HTTPException(409, "This policy is in the A/B holdout control group and must not receive treatment (FR-408)")
    recommend.record_decision(rec_id, actor["role"], actor["user_id"], body.decision, body.reason)
    audited(actor, body.decision, f"recommendation/{rec_id}")
    return {"status": "ok", "rec_id": rec_id, "decision": body.decision}


# --- Portfolio analytics (FR-500) -----------------------------------------

@app.get("/analytics/funnel")
def analytics_funnel(actor=Depends(require_role(*CAN_VIEW_AGGREGATE_ANALYTICS))):
    audited(actor, "view", "analytics/funnel")
    return analytics.funnel()


@app.get("/analytics/lapse-rate")
def analytics_lapse_rate(actor=Depends(require_role(*CAN_VIEW_AGGREGATE_ANALYTICS))):
    audited(actor, "view", "analytics/lapse-rate")
    return analytics.lapse_rate_breakdown()


@app.get("/analytics/driver-mix")
def analytics_driver_mix(actor=Depends(require_role(*CAN_VIEW_AGGREGATE_ANALYTICS))):
    audited(actor, "view", "analytics/driver-mix")
    return analytics.driver_mix()


@app.get("/analytics/premium-at-risk")
def analytics_premium_at_risk(actor=Depends(require_role(*CAN_VIEW_AGGREGATE_ANALYTICS))):
    audited(actor, "view", "analytics/premium-at-risk")
    return analytics.premium_at_risk_and_saved()


@app.get("/analytics/cohort")
def analytics_cohort(actor=Depends(require_role(*CAN_VIEW_AGGREGATE_ANALYTICS))):
    audited(actor, "view", "analytics/cohort")
    return analytics.cohort_comparison()


@app.get("/analytics/holdout-uplift")
def analytics_holdout(actor=Depends(require_role(*CAN_VIEW_AGGREGATE_ANALYTICS))):
    audited(actor, "view", "analytics/holdout-uplift")
    return analytics.holdout_uplift()


@app.get("/analytics/approval-rate")
def analytics_approval_rate(actor=Depends(require_role(*CAN_VIEW_AGGREGATE_ANALYTICS))):
    audited(actor, "view", "analytics/approval-rate")
    return analytics.approval_rate()


@app.get("/analytics/export.csv")
def analytics_export(actor=Depends(require_role(*CAN_VIEW_AGGREGATE_ANALYTICS))):
    audited(actor, "export", "analytics/export.csv")
    return PlainTextResponse(analytics.export_policies_csv(), media_type="text/csv")


@app.get("/audit-log")
def audit_log(limit: int = 200, actor=Depends(require_role("manager"))):
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# --- Agent layer (FR-600) --------------------------------------------------

@app.post("/agent/session/start")
def agent_start(body: AgentStartRequest, actor=Depends(require_role(*CAN_VIEW_CUSTOMER_EXPLANATION_ONLY))):
    audited(actor, "start", f"agent-session/policy/{body.policy_id}")
    return agent_module.start_session(body.policy_id)


@app.post("/agent/session/message")
def agent_message(body: AgentMessageRequest, actor=Depends(require_role(*CAN_VIEW_CUSTOMER_EXPLANATION_ONLY))):
    audited(actor, "message", f"agent-session/{body.session_id}")
    return agent_module.send_message(body.session_id, body.policy_id, body.message)


@app.get("/agent/session/{session_id}/transcript")
def agent_transcript(
    session_id: str,
    actor=Depends(require_role("manager", "underwriter", "service_agent", "customer")),
):
    audited(actor, "view", f"agent-transcript/{session_id}")
    return agent_module.get_transcript(session_id)


# --- Static frontend --------------------------------------------------------
import pathlib
_frontend_dir = pathlib.Path(__file__).resolve().parent.parent / "frontend"
if _frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
