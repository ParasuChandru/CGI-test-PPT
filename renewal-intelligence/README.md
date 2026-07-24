# Renewal Intelligence — Stage 0 Synthetic POC

An interpretable churn model, driver attribution, recommendation engine,
portfolio analytics, and a scripted conversational agent, built against
**synthetic data only** — this is Stage 0 of the staged data-access approach
in `RenewalIntelligenceRequirements.md` §5.2, the only stage that requires
no client data. It demonstrates the analytics methodology described in the
requirements spec; it is not a claim about any real book of business.

## What's here vs. what's deliberately deferred

| Built | Deferred (and why) |
|---|---|
| Synthetic data generator matching the §5.1 minimum viable dataset | Real ingestion pipelines (FR-101–107) — blocked on data access (§8.1) |
| Interpretable (logistic regression) churn model, versioned, meeting all three §6.1 targets | Deep/black-box models — excluded by FR-203 anyway |
| Exact per-feature logit attribution rolled up to the 5-driver taxonomy | Market/competitive-gap driver — no data source exists yet (FR-105, blocked); kept in the taxonomy flagged `insufficient_data` rather than faked |
| Recommendation engine: concession ceilings, duplicate-discount suppression, non-price actions, A/B holdout, approval workflow | Real integration to an offer-execution layer (NFR-402) — no such system exists in this environment |
| Portfolio analytics: funnel, lapse-rate breakdowns, driver mix, premium at risk/saved, cohort, CSV export | True multi-year cohort tracking (FR-505) — needs Stage 2+ longitudinal data; approximated here with a tenure-band proxy |
| Scripted (non-generative) agent: bounded intents, context-aware opening, escalation, transcript logging | Real self-service-portal embedding (FR-602) and SSO (NFR-403) — no portal/IdP to integrate with here |
| Server-side RBAC across 6 roles with an audit log | Enterprise SSO (NFR-403) — replaced with an `X-Role`/`X-User-Id` header demo shim |

Everything under "Deferred" is blocked by the same items the requirements
doc already calls out in §8 (data access, portal overlap, DPO/legal input) —
nothing here works around those blockers, it demonstrates what's buildable
on the other side of them.

## Decisions made resolving review ambiguities

The requirements review surfaced four places where the spec was internally
ambiguous. Rather than leave them open, this build makes an explicit choice
and documents it in `backend/config.py`:

1. **Override rights** (§2.1 gives the Manager "override scores"; FR-206 says
   "underwriter"): both Manager and Underwriter can override, since
   overriding is how an underwriter exercises the "challenge" the spec
   gives them — every override is logged with actor role regardless.
2. **Pricing access tier**: NFR-104 implies Pricing needs to view model
   internals but §2.1's role table has no Pricing row. Added `pricing` as a
   sixth role with exactly that one permission.
3. **Competitive-gap driver vs. blocked FR-105 data**: rather than let a
   Must-priority taxonomy category attribute to noise, it's always reported
   `insufficient_data` and never selected as dominant.
4. **Customer-facing score exposure**: NFR-205 bars disclosing pricing
   *logic* to customers but says nothing about the raw *score*. Both the
   Service Agent and Customer surfaces (`/policies/{id}/customer-view`,
   the agent) now never receive the score or coefficients — only the
   approved action and driver label.

## Running it

```bash
cd renewal-intelligence
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

python scripts/seed.py        # generates data, trains the model, seeds recommendations
uvicorn backend.main:app --reload --port 8000
```

Open `http://localhost:8000/`. The top bar's **Role** selector switches
between the six roles; every permission boundary is enforced server-side
(NFR-101) — the UI just adapts what it shows, it does not gate anything
itself.

To regenerate everything from scratch (new random seed, fresh model):
delete `data/renewal_intelligence.db` and re-run `scripts/seed.py`.

## Architecture

```
backend/
  config.py       # driver taxonomy, concession ceilings, RBAC matrix — all data, not code (FR-305)
  data_gen.py      # synthetic policy/claims/interaction/outcome generator (§5.1)
  db.py            # SQLite schema + connection helpers
  model.py         # standardized-feature logistic regression, exact logit attribution (FR-200/FR-204)
  attribution.py   # per-feature contributions rolled up to the 5-driver taxonomy (FR-300)
  recommend.py     # action selection, ceilings, suppression, holdout (FR-400)
  analytics.py     # portfolio-level aggregations (FR-500)
  agent.py         # scripted, bounded-knowledge-base conversational flow (FR-600)
  auth.py          # RBAC dependency + audit logging (NFR-100)
  main.py          # FastAPI routes
scripts/seed.py     # one-shot batch: generate -> train -> score -> attribute -> recommend
frontend/           # role-aware single-page dashboard (no build step, no CDN dependency)
```

## Model note

The model is a **standardized logistic regression**, not a tree/SHAP setup —
this gives an *exact*, arithmetic attribution (`logit = intercept +
Σ coef·z`) rather than an approximation, which matters for FR-204's "must
sum to the score" requirement and for a regulated market where "why did the
model say this" needs to survive an audit. On the seeded synthetic run it
reaches AUC 0.758, precision@10% 2.72×, and calibration error 0.016 —
meeting all three §6.1 targets (results vary slightly with the random seed).
