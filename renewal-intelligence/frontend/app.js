const API = "";

const ROLE_TABS = {
  manager: ["portfolio", "policies", "recommendations", "model", "audit"],
  underwriter: ["portfolio", "policies", "recommendations"],
  analyst: ["portfolio"],
  pricing: ["model"],
  service_agent: ["lookup"],
  customer: ["chat"],
};

const TAB_LABELS = {
  portfolio: "Portfolio",
  policies: "Policies",
  recommendations: "Recommendations",
  model: "Model",
  audit: "Audit log",
  lookup: "Customer lookup",
  chat: "Assistant chat",
};

let currentRole = "manager";
let currentTab = "portfolio";

function headers(extra) {
  const role = document.getElementById("roleSelect").value;
  const user = document.getElementById("userId").value || "demo-user";
  return Object.assign({ "X-Role": role, "X-User-Id": user }, extra || {});
}

async function api(path, opts) {
  opts = opts || {};
  opts.headers = Object.assign(headers(opts.jsonBody ? { "Content-Type": "application/json" } : {}), opts.headers || {});
  if (opts.jsonBody) {
    opts.body = JSON.stringify(opts.jsonBody);
    delete opts.jsonBody;
  }
  const res = await fetch(API + path, opts);
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${detail}`);
  }
  const ct = res.headers.get("content-type") || "";
  return ct.includes("application/json") ? res.json() : res.text();
}

function showError(msg) {
  const box = document.getElementById("globalError");
  box.innerHTML = `<div class="error-box">${msg}</div>`;
  setTimeout(() => (box.innerHTML = ""), 6000);
}

function bar(label, value, max, formatted) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return `<div class="bar-row">
    <div class="label">${label}</div>
    <div class="track"><div class="fill" style="width:${pct}%"></div></div>
    <div class="value">${formatted !== undefined ? formatted : value}</div>
  </div>`;
}

function renderTabs() {
  const tabs = ROLE_TABS[currentRole] || [];
  const nav = document.getElementById("tabs");
  nav.innerHTML = tabs
    .map((t) => `<button data-tab="${t}" class="${t === currentTab ? "active" : ""}">${TAB_LABELS[t]}</button>`)
    .join("");
  nav.querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => switchTab(b.dataset.tab))
  );
  if (!tabs.includes(currentTab)) currentTab = tabs[0];
  switchTab(currentTab);
}

function switchTab(tab) {
  currentTab = tab;
  document.querySelectorAll("nav.tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  document.querySelectorAll("main .view").forEach((v) => v.classList.remove("active"));
  const el = document.getElementById("view-" + tab);
  if (el) el.classList.add("active");
  loadTab(tab);
}

function loadTab(tab) {
  const loaders = {
    portfolio: loadPortfolio,
    policies: loadPolicies,
    recommendations: loadRecommendations,
    model: loadModel,
    audit: loadAudit,
    lookup: () => {},
    chat: () => {},
  };
  (loaders[tab] || (() => {}))().catch((e) => showError(e.message));
}

// ---------------- Portfolio ----------------
async function loadPortfolio() {
  const [funnel, lapse, driverMix, premium, holdout, approval] = await Promise.all([
    api("/analytics/funnel"),
    api("/analytics/lapse-rate"),
    api("/analytics/driver-mix"),
    api("/analytics/premium-at-risk"),
    api("/analytics/holdout-uplift"),
    api("/analytics/approval-rate"),
  ]);

  document.getElementById("portfolioStats").innerHTML = `
    <div class="card"><h3>Book</h3><div class="stat-row">
      <div class="stat"><div class="num">${funnel.total_policies}</div><div class="label">Total policies</div></div>
      <div class="stat"><div class="num">${(funnel.book_wide_renewal_rate * 100).toFixed(1)}%</div><div class="label">Book-wide renewal rate</div></div>
      <div class="stat"><div class="num">${(lapse.overall_lapse_rate * 100).toFixed(1)}%</div><div class="label">Overall lapse rate</div></div>
    </div></div>
    <div class="card"><h3>Premium (FR-504)</h3><div class="stat-row">
      <div class="stat"><div class="num">$${premium.total_premium_at_risk.toLocaleString()}</div><div class="label">Annualised premium at risk</div></div>
      <div class="stat"><div class="num">$${premium.total_premium_saved.toLocaleString()}</div><div class="label">Premium saved (approved & renewed)</div></div>
    </div></div>`;

  const maxFunnel = Math.max(...funnel.funnel.map((f) => f.count));
  document.getElementById("funnelChart").innerHTML = funnel.funnel
    .map((f) => bar(f.stage, f.count, maxFunnel, `${f.count}${f.loss_from_prior !== null ? ` (−${f.loss_from_prior})` : ""}`))
    .join("");

  const mix = driverMix.overall_mix || {};
  const maxMix = Math.max(...Object.values(mix), 0.01);
  document.getElementById("driverMixChart").innerHTML = Object.entries(mix)
    .sort((a, b) => b[1] - a[1])
    .map(([d, v]) => bar(d, v, maxMix, `${(v * 100).toFixed(1)}%`))
    .join("") || "<p class='small-muted'>No driver mix data yet.</p>";

  const byLine = lapse.by_line;
  const maxLine = Math.max(...byLine.map((r) => r.lapse_rate));
  document.getElementById("lapseByLine").innerHTML = byLine
    .map((r) => bar(r.segment, r.lapse_rate, maxLine, `${(r.lapse_rate * 100).toFixed(1)}% (n=${r.n})`))
    .join("");

  const byTenure = lapse.by_tenure_band;
  const maxTenure = Math.max(...byTenure.map((r) => r.lapse_rate));
  document.getElementById("lapseByTenure").innerHTML = byTenure
    .map((r) => bar(r.segment, r.lapse_rate, maxTenure, `${(r.lapse_rate * 100).toFixed(1)}% (n=${r.n})`))
    .join("");

  document.getElementById("holdoutBox").innerHTML = holdout.available
    ? `<div class="stat-row">
        <div class="stat bad"><div class="num">${(holdout.treatment_lapse_rate * 100).toFixed(1)}%</div><div class="label">Treatment lapse rate (n=${holdout.treatment_n})</div></div>
        <div class="stat"><div class="num">${(holdout.control_lapse_rate * 100).toFixed(1)}%</div><div class="label">Control lapse rate (n=${holdout.control_n})</div></div>
        <div class="stat ${holdout["statistically_significant_at_0.05"] ? "ok" : ""}"><div class="num">${(holdout.relative_reduction * 100).toFixed(1)}%</div><div class="label">Relative reduction (p=${holdout.p_value})</div></div>
      </div>
      <p class="small-muted">${holdout["statistically_significant_at_0.05"] ? "Statistically significant at 0.05." : "Not yet statistically significant — approve more recommendations to build sample size."}</p>`
    : `<p class="small-muted">${holdout.reason}</p>`;

  document.getElementById("approvalBox").innerHTML = approval.available
    ? `<div class="stat ${approval["meets_target_ge_0.60"] ? "ok" : "bad"}"><div class="num">${(approval.approval_rate * 100).toFixed(1)}%</div><div class="label">Approval rate (n=${approval.n_decided} decided)</div></div>`
    : `<p class="small-muted">${approval.reason}</p>`;

  document.getElementById("exportBtn").onclick = () => {
    window.open(API + "/analytics/export.csv?" + new URLSearchParams(headers()).toString());
  };
}

// ---------------- Policies ----------------
async function loadPolicies() {
  const policies = await api("/policies?limit=100");
  const rows = policies
    .map(
      (p) => `<tr data-id="${p.policy_id}">
      <td>${p.policy_id}</td><td>${p.line}</td><td>${p.segment}</td>
      <td>${(p.score * 100).toFixed(1)}%</td><td>${p.dominant_driver || "-"}</td>
      <td>$${p.renewal_quote.toLocaleString()}</td>
    </tr>`
    )
    .join("");
  document.getElementById("policiesTableWrap").innerHTML = `
    <table><thead><tr><th>Policy</th><th>Line</th><th>Segment</th><th>Score</th><th>Dominant driver</th><th>Renewal premium</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
  document.querySelectorAll("#policiesTableWrap tr[data-id]").forEach((tr) =>
    tr.addEventListener("click", () => loadPolicyDetail(tr.dataset.id))
  );
}

async function loadPolicyDetail(policyId) {
  const d = await api(`/policies/${policyId}`);
  const driverChips = d.drivers
    .map((dr) => {
      const cls = dr.status === "insufficient_data" ? "na" : dr.driver === (d.recommendations[0] && d.recommendations[0].dominant_driver) ? "dominant" : "";
      const val = dr.contribution_pct === null ? "n/a" : `${dr.contribution_pct}%`;
      return `<span class="driver-chip ${cls}">${dr.driver}: ${val}</span>`;
    })
    .join("");

  const rec = d.recommendations[0];
  const recBox = rec
    ? `<h3>Recommendation <span class="badge ${rec.status}">${rec.status}</span> <span class="badge ${rec.holdout_group}">${rec.holdout_group}</span></h3>
       <p><strong>${rec.action}</strong></p>
       <p class="small-muted">Concession: $${rec.concession_value} · Save probability: ${(rec.save_probability * 100).toFixed(1)}% · Expected value: $${rec.expected_value}</p>
       ${rec.suppressed ? `<p class="small-muted">Suppressed: ${rec.suppressed_reason}</p>` : ""}
       ${rec.status === "pending" && rec.holdout_group !== "control" ? `
         <button class="btn" onclick="decide('${rec.rec_id}','approved')">Approve</button>
         <button class="btn secondary" onclick="decide('${rec.rec_id}','rejected')">Reject</button>
         <button class="btn ghost" onclick="decide('${rec.rec_id}','modified')">Modify</button>` : ""}
       ${rec.holdout_group === "control" ? `<p class="small-muted">Held out as A/B control (FR-408) — cannot be approved.</p>` : ""}`
    : "<p class='small-muted'>No recommendation (not at-risk or below threshold).</p>";

  document.getElementById("policyDetail").innerHTML = `
    <div class="detail-panel">
      <div class="card">
        <h3>${policyId} — score ${(d.score.score * 100).toFixed(1)}%</h3>
        <div>${driverChips}</div>
        <p class="small-muted">Model version: ${d.score.model_version}</p>
        <h3 style="margin-top:16px">Override (FR-206)</h3>
        <input type="text" id="overrideScore" placeholder="0.00 - 1.00" />
        <textarea id="overrideReason" placeholder="Mandatory reason" rows="2" style="margin-top:6px"></textarea>
        <button class="btn" style="margin-top:8px" onclick="submitOverride('${policyId}')">Submit override</button>
        ${d.overrides.length ? `<p class="small-muted" style="margin-top:8px">${d.overrides.length} prior override(s) on record.</p>` : ""}
      </div>
      <div class="card">${recBox}</div>
    </div>`;
}

async function decide(recId, decision) {
  const reason = decision !== "approved" ? prompt("Reason (optional):") : null;
  try {
    await api(`/recommendations/${recId}/decision`, { method: "POST", jsonBody: { decision, reason } });
    loadTab("policies");
  } catch (e) {
    showError(e.message);
  }
}

async function submitOverride(policyId) {
  const score = parseFloat(document.getElementById("overrideScore").value);
  const reason = document.getElementById("overrideReason").value;
  if (isNaN(score) || score < 0 || score > 1) return showError("Override score must be between 0 and 1.");
  if (!reason || reason.length < 5) return showError("A reason (5+ chars) is required (FR-206).");
  try {
    await api(`/policies/${policyId}/override`, { method: "POST", jsonBody: { override_score: score, reason } });
    loadPolicyDetail(policyId);
  } catch (e) {
    showError(e.message);
  }
}

// ---------------- Recommendations queue ----------------
async function loadRecommendations() {
  const recs = await api("/recommendations?status=pending");
  const rows = recs
    .map(
      (r) => `<tr>
      <td>${r.policy_id}</td><td>${r.dominant_driver}</td><td>${r.action}</td>
      <td>$${r.concession_value}</td><td>$${r.expected_value}</td>
      <td><span class="badge ${r.holdout_group}">${r.holdout_group}</span></td>
      <td>${r.holdout_group !== "control" ? `
        <button class="btn" onclick="decide('${r.rec_id}','approved')">Approve</button>
        <button class="btn secondary" onclick="decide('${r.rec_id}','rejected')">Reject</button>` : "withheld (control)"}</td>
    </tr>`
    )
    .join("");
  document.getElementById("recQueue").innerHTML = `
    <table><thead><tr><th>Policy</th><th>Driver</th><th>Action</th><th>Concession</th><th>Expected value</th><th>Group</th><th>Decision</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}
window.decide = decide;
window.submitOverride = submitOverride;

// ---------------- Model ----------------
async function loadModel() {
  const perf = await api("/model/performance");
  document.getElementById("modelPerf").innerHTML = `
    <div class="card"><h3>Performance (FR-207 / §6.1)</h3><div class="stat-row">
      <div class="stat ${perf.meets_targets["auc_ge_0.72"] ? "ok" : "bad"}"><div class="num">${perf.auc.toFixed(3)}</div><div class="label">AUC (target ≥0.72)</div></div>
      <div class="stat ${perf.meets_targets["precision_at_10_ge_2.5x"] ? "ok" : "bad"}"><div class="num">${perf.precision_at_10.toFixed(2)}x</div><div class="label">Precision@10% (target ≥2.5x)</div></div>
      <div class="stat ${perf.meets_targets["calibration_le_0.05"] ? "ok" : "bad"}"><div class="num">${perf.calibration_error.toFixed(3)}</div><div class="label">Calibration error (target ≤0.05)</div></div>
    </div><p class="small-muted">Model version ${perf.model_version} · base lapse rate ${(perf.base_lapse_rate * 100).toFixed(1)}%</p></div>`;

  const internalsCard = document.getElementById("modelInternalsCard");
  try {
    const internals = await api("/model/internals");
    internalsCard.style.display = "block";
    const rows = Object.entries(internals.coefficients)
      .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
      .map(([f, c]) => `<tr><td>${f}</td><td>${c.toFixed(4)}</td></tr>`)
      .join("");
    document.getElementById("modelInternals").innerHTML = `<table><thead><tr><th>Feature</th><th>Standardized coefficient</th></tr></thead><tbody>${rows}</tbody></table>`;
  } catch (e) {
    internalsCard.style.display = "none"; // 403 for non-manager/pricing roles — expected
  }
}

// ---------------- Audit log ----------------
async function loadAudit() {
  const rows = await api("/audit-log?limit=100");
  document.getElementById("auditTableWrap").innerHTML = `
    <table><thead><tr><th>Time</th><th>Role</th><th>User</th><th>Action</th><th>Resource</th></tr></thead>
    <tbody>${rows.map((r) => `<tr><td>${new Date(r.created_at * 1000).toLocaleString()}</td><td>${r.actor_role}</td><td>${r.actor_id}</td><td>${r.action}</td><td>${r.resource}</td></tr>`).join("")}</tbody></table>`;
}

// ---------------- Service agent lookup ----------------
document.getElementById("lookupBtn").addEventListener("click", async () => {
  const id = document.getElementById("lookupPolicyId").value.trim();
  if (!id) return showError("Enter a policy ID (see the Policies tab under a Manager/Underwriter role).");
  try {
    const r = await api(`/policies/${id}/customer-view`);
    document.getElementById("lookupResult").innerHTML = r.has_offer
      ? `<div class="card"><h3>${id}</h3><p><strong>${r.action}</strong></p>
         <p class="small-muted">Driver category: ${r.dominant_driver}${r.concession_value ? ` · Concession: $${r.concession_value}` : ""}</p>
         <p class="small-muted">No churn score or model internals shown here (NFR-103).</p></div>`
      : `<div class="card"><p>No approved offer on record for ${id}.</p></div>`;
  } catch (e) {
    showError(e.message);
  }
});

// ---------------- Chat ----------------
let chatSessionId = null;
let chatPolicyId = null;

function appendChatMsg(sender, message, escalated) {
  const win = document.getElementById("chatWindow");
  const div = document.createElement("div");
  div.className = `chat-msg ${sender}${escalated ? " escalated" : ""}`;
  div.textContent = message;
  win.appendChild(div);
  win.scrollTop = win.scrollHeight;
}

document.getElementById("chatStartBtn").addEventListener("click", async () => {
  chatPolicyId = document.getElementById("chatPolicyId").value.trim();
  if (!chatPolicyId) return showError("Enter a policy ID with an approved recommendation.");
  document.getElementById("chatWindow").innerHTML = "";
  try {
    const r = await api("/agent/session/start", { method: "POST", jsonBody: { policy_id: chatPolicyId } });
    chatSessionId = r.session_id;
    appendChatMsg("agent", r.message, r.escalated);
    document.getElementById("chatInput").disabled = false;
    document.getElementById("chatSendBtn").disabled = false;
  } catch (e) {
    showError(e.message);
  }
});

document.getElementById("chatSendBtn").addEventListener("click", sendChat);
document.getElementById("chatInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendChat();
});

async function sendChat() {
  const input = document.getElementById("chatInput");
  const text = input.value.trim();
  if (!text || !chatSessionId) return;
  appendChatMsg("customer", text);
  input.value = "";
  try {
    const r = await api("/agent/session/message", {
      method: "POST",
      jsonBody: { session_id: chatSessionId, policy_id: chatPolicyId, message: text },
    });
    appendChatMsg("agent", r.message, r.escalated);
  } catch (e) {
    showError(e.message);
  }
}

// ---------------- Init ----------------
document.getElementById("roleSelect").addEventListener("change", (e) => {
  currentRole = e.target.value;
  currentTab = (ROLE_TABS[currentRole] || [])[0];
  renderTabs();
});

renderTabs();
