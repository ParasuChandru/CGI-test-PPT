"""
Scripted conversational agent layer (FR-600).

This is deliberately NOT a free-generation LLM chat: FR-605 requires
responses "constrained to an approved knowledge base; no free generation
about pricing," which a rule-based, bounded-intent flow satisfies by
construction. It only ever discusses a recommendation that has already been
human-approved (FR-406) — there is nothing here for the agent to release on
its own authority.

Guardrails:
- Opens with context the system already has (FR-603) — never asks the
  customer to re-supply data on record.
- Never surfaces the raw churn score or model internals to the customer
  (extends NFR-103's "not to customer-facing staff" logic to the
  customer-facing surface itself — a gap flagged in the requirements
  review; NFR-205 already bars disclosing pricing *logic*, this closes the
  analogous gap for the *score*).
- Escalates to a human on explicit request, cancellation intent, or any
  message it cannot classify into its bounded intent set (FR-604).
"""
from __future__ import annotations

import time
import uuid

from . import db

EXPLANATIONS = {
    "premium_shock": (
        "Your renewal premium changed compared to last year — that's the main factor "
        "behind this offer."
    ),
    "claim_experience": (
        "Recent claims activity on your policy was a contributing factor, so we're "
        "offering enhanced service support rather than a price change."
    ),
    "service_friction": (
        "We noticed some recent service interactions that didn't go as smoothly as "
        "they should have, so we're prioritising a service-recovery contact for you."
    ),
    "disengagement": (
        "We haven't seen much recent activity on your account, so we wanted to check "
        "in and make sure everything is working the way you expect."
    ),
    "competitive_gap": (
        "We wanted to check in ahead of your renewal to make sure your cover still "
        "fits your needs."
    ),
    "unattributed": (
        "We wanted to check in ahead of your renewal to make sure you have everything "
        "you need."
    ),
}

CANCEL_KEYWORDS = ["cancel", "terminate", "close my policy", "end my policy"]
HUMAN_KEYWORDS = ["human", "agent", "representative", "speak to someone", "speak to a person"]
ACCEPT_KEYWORDS = ["accept", "yes", "sounds good", "ok", "okay", "sure", "agreed"]
DECLINE_KEYWORDS = ["no thanks", "not interested", "decline", "no "]
WHY_KEYWORDS = ["why", "explain", "reason", "how come"]


def _classify(text: str) -> str:
    t = f" {text.lower().strip()} "
    if any(k in t for k in CANCEL_KEYWORDS) or any(k in t for k in HUMAN_KEYWORDS):
        return "escalate"
    if any(k in t for k in WHY_KEYWORDS):
        return "why"
    if any(k in t for k in ACCEPT_KEYWORDS):
        return "accept"
    if any(k in t for k in DECLINE_KEYWORDS):
        return "decline"
    return "unrecognized"


def _approved_recommendation(policy_id: str) -> dict | None:
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM recommendations WHERE policy_id = ? AND status = 'approved' "
            "ORDER BY created_at DESC LIMIT 1",
            (policy_id,),
        ).fetchone()
    return dict(row) if row else None


def _append_turn(session_id: str, policy_id: str, turn_index: int, sender: str, message: str, escalated: bool = False):
    with db.get_conn() as conn:
        conn.execute(
            """INSERT INTO transcripts (session_id, policy_id, turn_index, sender, message, escalated, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (session_id, policy_id, turn_index, sender, message, int(escalated), time.time()),
        )


def start_session(policy_id: str) -> dict:
    rec = _approved_recommendation(policy_id)
    session_id = uuid.uuid4().hex[:12]

    if not rec:
        msg = (
            "Hi, thanks for reaching out. I don't have an active pre-approved offer for "
            "this policy right now, so let me connect you with a member of our team."
        )
        _append_turn(session_id, policy_id, 0, "agent", msg, escalated=True)
        return {"session_id": session_id, "message": msg, "escalated": True}

    explanation = EXPLANATIONS.get(rec["dominant_driver"], EXPLANATIONS["unattributed"])
    if rec["is_price_action"] and not rec["suppressed"] and rec["concession_value"] > 0:
        offer = (
            f"Ahead of your renewal, we'd like to offer a premium adjustment of "
            f"${rec['concession_value']:.2f}. {explanation}"
        )
    else:
        offer = f"Ahead of your renewal, we'd like to offer: {rec['action']}. {explanation}"

    msg = f"Hi, I'm reaching out about your upcoming renewal. {offer} Would that work for you?"
    _append_turn(session_id, policy_id, 0, "agent", msg)
    return {"session_id": session_id, "message": msg, "escalated": False, "recommendation": rec}


def send_message(session_id: str, policy_id: str, user_text: str) -> dict:
    with db.get_conn() as conn:
        last = conn.execute(
            "SELECT MAX(turn_index) AS m FROM transcripts WHERE session_id = ?", (session_id,)
        ).fetchone()
    next_index = (last["m"] if last and last["m"] is not None else -1) + 1
    _append_turn(session_id, policy_id, next_index, "customer", user_text)

    intent = _classify(user_text)
    rec = _approved_recommendation(policy_id)
    escalated = False

    if intent == "escalate":
        reply = "Of course — I'll connect you with one of our team members right away."
        escalated = True
    elif intent == "why":
        driver = rec["dominant_driver"] if rec else "unattributed"
        reply = EXPLANATIONS.get(driver, EXPLANATIONS["unattributed"])
    elif intent == "accept":
        reply = "Great — I've noted that you'd like to go ahead. You'll receive confirmation shortly."
    elif intent == "decline":
        reply = "No problem at all. Let me know if you'd like to talk through any other options."
    else:
        reply = (
            "I want to make sure you get the right answer for that — let me connect you "
            "with a member of our team."
        )
        escalated = True

    _append_turn(session_id, policy_id, next_index + 1, "agent", reply, escalated=escalated)
    return {"session_id": session_id, "message": reply, "escalated": escalated, "intent": intent}


def get_transcript(session_id: str) -> list[dict]:
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM transcripts WHERE session_id = ? ORDER BY turn_index", (session_id,)
        ).fetchall()
    return [dict(r) for r in rows]
