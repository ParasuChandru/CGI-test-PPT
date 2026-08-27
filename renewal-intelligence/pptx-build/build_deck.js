const pptxgen = require("pptxgenjs");
const fs = require("fs");

const RED = "E31937";
const DEEP_RED = "991F3D";
const AMBER = "F2A200";
const DARK = "1A1A1A";
const WHITE = "FFFFFF";
const GRAY = "6B6B6B";
const LIGHT_GRAY = "F2F2F2";

const ICON = (name, color) => `${__dirname}/icons/${name}_${color}.png`;

function iconCircle(slide, { x, y, d, icon, iconColor, circleColor, iconScale = 0.52 }) {
  slide.addShape("ellipse", { x, y, w: d, h: d, fill: { color: circleColor }, line: { type: "none" } });
  const iw = d * iconScale;
  slide.addImage({ path: icon, x: x + (d - iw) / 2, y: y + (d - iw) / 2, w: iw, h: iw });
}

function footer(slide, label, pageNum, light) {
  slide.addText("CGI", {
    x: 0.5, y: 0.22, w: 1.5, h: 0.35, fontFace: "Arial", bold: true, fontSize: 14,
    color: light ? WHITE : RED, isTextBox: true, margin: 0,
  });
  slide.addText(label, {
    x: 2.0, y: 0.24, w: 8, h: 0.3, fontFace: "Calibri", fontSize: 10, color: light ? "E8B9C2" : GRAY,
    isTextBox: true, margin: 0,
  });
  slide.addText(pageNum, {
    x: 12.3, y: 0.22, w: 0.8, h: 0.3, fontFace: "Calibri", fontSize: 10, align: "right",
    color: light ? "E8B9C2" : GRAY, isTextBox: true, margin: 0,
  });
}

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5
const PGW = 13.33, PGH = 7.5;

/* ---------------- Slide 1: Title ---------------- */
{
  const s = pres.addSlide();
  s.background = { color: RED };

  // Decorative motif: three overlapping circles (predict/explain/act), large, low-opacity
  s.addShape("ellipse", { x: 8.6, y: -1.2, w: 5.2, h: 5.2, fill: { color: DEEP_RED, transparency: 35 }, line: { type: "none" } });
  s.addShape("ellipse", { x: 10.6, y: 1.6, w: 4.0, h: 4.0, fill: { color: DEEP_RED, transparency: 45 }, line: { type: "none" } });
  s.addShape("ellipse", { x: 9.6, y: 4.6, w: 3.0, h: 3.0, fill: { color: AMBER, transparency: 55 }, line: { type: "none" } });

  s.addText("CGI", { x: 0.7, y: 0.5, w: 2, h: 0.5, fontFace: "Arial", bold: true, fontSize: 20, color: WHITE, isTextBox: true, margin: 0 });

  s.addText("RENEWAL INTELLIGENCE", {
    x: 0.7, y: 2.7, w: 9.5, h: 1.5, fontFace: "Cambria", bold: true, fontSize: 46, color: WHITE,
    isTextBox: true, margin: 0,
  });
  s.addText("An analytics-led renewal retention layer", {
    x: 0.72, y: 3.85, w: 8.5, h: 0.6, fontFace: "Calibri", fontSize: 20, color: "FBD7DE", isTextBox: true, margin: 0,
  });
  s.addText("Predicts which policies will lapse, explains why, and recommends the right action —\nfeeding your existing systems rather than replacing them.", {
    x: 0.72, y: 4.55, w: 7.6, h: 0.9, fontFace: "Calibri", fontSize: 13.5, color: "FBD7DE", isTextBox: true, margin: 0, lineSpacingMultiple: 1.25,
  });

  s.addText("Requirements & Approach — Stage 0 Review", {
    x: 0.72, y: 6.6, w: 6, h: 0.4, fontFace: "Calibri", fontSize: 12, italic: true, color: "F6AEBB", isTextBox: true, margin: 0,
  });
}

/* ---------------- Slide 2: The problem ---------------- */
{
  const s = pres.addSlide();
  s.background = { color: WHITE };
  footer(s, "The Problem", "02", false);

  s.addText("Policies lapse. We usually find out after it's too late to act.", {
    x: 0.7, y: 0.85, w: 11.8, h: 1.0, fontFace: "Cambria", bold: true, fontSize: 30, color: DARK, isTextBox: true, margin: 0,
  });
  s.addText("A blanket discount doesn't fix a service problem — and by the time we notice a dip, the customer's already gone.", {
    x: 0.7, y: 1.65, w: 10.8, h: 0.5, fontFace: "Calibri", fontSize: 14, color: GRAY, isTextBox: true, margin: 0,
  });

  const items = [
    { icon: "problem_late", title: "Found out too late", body: "By the time a policy shows up as “lapsed,” the moment to intervene has already passed." },
    { icon: "problem_unseen", title: "No visibility into “why”", body: "1,000 policies up for renewal, 700 renew — nobody can say with confidence why the other 300 left." },
    { icon: "problem_discount", title: "One tool for every problem", body: "A generic discount gets offered even when the real issue was a bad claims experience or poor service." },
  ];
  const cardW = 3.75, gap = 0.35, startX = 0.7, y = 2.55, cardH = 3.5;
  items.forEach((it, i) => {
    const x = startX + i * (cardW + gap);
    s.addShape("roundRect", { x, y, w: cardW, h: cardH, rectRadius: 0.08, fill: { color: LIGHT_GRAY }, line: { type: "none" } });
    iconCircle(s, { x: x + (cardW - 1.1) / 2, y: y + 0.4, d: 1.1, icon: ICON(it.icon, "white"), circleColor: RED });
    s.addText(it.title, {
      x: x + 0.25, y: y + 1.7, w: cardW - 0.5, h: 0.5, fontFace: "Cambria", bold: true, fontSize: 16, color: DARK,
      isTextBox: true, margin: 0, align: "center",
    });
    s.addText(it.body, {
      x: x + 0.35, y: y + 2.2, w: cardW - 0.7, h: 1.2, fontFace: "Calibri", fontSize: 12, color: GRAY,
      isTextBox: true, margin: 0, align: "center", valign: "top", lineSpacingMultiple: 1.2,
    });
  });
}

/* ---------------- Slide 3: What changed ---------------- */
{
  const s = pres.addSlide();
  s.background = { color: WHITE };
  footer(s, "What Changed", "03", false);

  s.addText("Analytics is the product. AI chat is just one delivery channel.", {
    x: 0.7, y: 0.85, w: 11.8, h: 1.0, fontFace: "Cambria", bold: true, fontSize: 28, color: DARK, isTextBox: true, margin: 0,
  });
  s.addText("The original idea led with a conversational agent. Your review feedback reordered it.", {
    x: 0.7, y: 1.65, w: 10.8, h: 0.5, fontFace: "Calibri", fontSize: 14, color: GRAY, isTextBox: true, margin: 0,
  });

  // Two quote cards
  const quotes = [
    { text: "“AI is not the answer for everything … what comes to my mind immediately is analytics.”", who: "— A. Karanth" },
    { text: "“Using AI, we should understand why there is a dip, what may be the reason.”", who: "— S. Kamath" },
  ];
  const qW = 5.6, qH = 1.9, qY = 2.55;
  quotes.forEach((q, i) => {
    const x = 0.7 + i * (qW + 0.4);
    s.addShape("roundRect", { x, y: qY, w: qW, h: qH, rectRadius: 0.08, fill: { color: LIGHT_GRAY }, line: { type: "none" } });
    s.addText(q.text, {
      x: x + 0.35, y: qY + 0.25, w: qW - 0.7, h: 1.15, fontFace: "Cambria", italic: true, fontSize: 14.5, color: DARK,
      isTextBox: true, margin: 0, valign: "top", lineSpacingMultiple: 1.25,
    });
    s.addText(q.who, {
      x: x + 0.35, y: qY + 1.42, w: qW - 0.7, h: 0.35, fontFace: "Calibri", bold: true, fontSize: 12, color: RED,
      isTextBox: true, margin: 0,
    });
  });

  // Before / After row
  const rowY = 4.95;
  s.addShape("roundRect", { x: 0.7, y: rowY, w: 5.6, h: 1.55, rectRadius: 0.08, fill: { color: WHITE }, line: { color: "DDDDDD", width: 1 } });
  iconCircle(s, { x: 0.95, y: rowY + 0.28, d: 1.0, icon: ICON("changed_ai", "dark"), circleColor: LIGHT_GRAY, iconScale: 0.5 });
  s.addText("Original pitch", { x: 2.15, y: rowY + 0.25, w: 4.0, h: 0.4, fontFace: "Calibri", bold: true, fontSize: 13, color: GRAY, isTextBox: true, margin: 0 });
  s.addText("Lead with a conversational renewal agent", { x: 2.15, y: rowY + 0.65, w: 4.0, h: 0.7, fontFace: "Calibri", fontSize: 13, color: DARK, isTextBox: true, margin: 0, lineSpacingMultiple: 1.15 });

  s.addShape("roundRect", { x: 6.7, y: rowY, w: 5.6, h: 1.55, rectRadius: 0.08, fill: { color: "FDEDEF" }, line: { type: "none" } });
  iconCircle(s, { x: 6.95, y: rowY + 0.28, d: 1.0, icon: ICON("changed_analytics", "white"), circleColor: RED, iconScale: 0.5 });
  s.addText("This approach", { x: 8.15, y: rowY + 0.25, w: 4.0, h: 0.4, fontFace: "Calibri", bold: true, fontSize: 13, color: RED, isTextBox: true, margin: 0 });
  s.addText("Analytics predicts and explains — the agent is one optional channel on top", { x: 8.15, y: rowY + 0.65, w: 4.0, h: 0.7, fontFace: "Calibri", fontSize: 13, color: DARK, isTextBox: true, margin: 0, lineSpacingMultiple: 1.15 });
}

/* ---------------- Slide 4: What it does ---------------- */
{
  const s = pres.addSlide();
  s.background = { color: WHITE };
  footer(s, "What It Does", "04", false);

  s.addText("Three steps, per policy, before renewal.", {
    x: 0.7, y: 0.85, w: 11.8, h: 0.8, fontFace: "Cambria", bold: true, fontSize: 30, color: DARK, isTextBox: true, margin: 0,
  });

  const steps = [
    { n: "1", icon: "step_predict", title: "Predict risk", body: "An explainable score per policy — not a black box. Every number can be challenged and audited." },
    { n: "2", icon: "step_explain", title: "Explain why", body: "Classified into one of five causes: premium shock, competitive gap, service friction, disengagement, or claim experience." },
    { n: "3", icon: "step_act", title: "Recommend the right action", body: "Matched to the real cause — not always a discount — capped, and never released without human approval." },
  ];
  const cardW = 3.75, gap = 0.35, startX = 0.7, y = 1.95, cardH = 4.15;
  steps.forEach((st, i) => {
    const x = startX + i * (cardW + gap);
    s.addShape("roundRect", { x, y, w: cardW, h: cardH, rectRadius: 0.08, fill: { color: LIGHT_GRAY }, line: { type: "none" } });
    s.addText(st.n, {
      x: x + 0.25, y: y + 0.2, w: 0.7, h: 0.6, fontFace: "Cambria", bold: true, fontSize: 26, color: "CFCFCF", isTextBox: true, margin: 0,
    });
    iconCircle(s, { x: x + (cardW - 1.15) / 2, y: y + 0.75, d: 1.15, icon: ICON(st.icon, "white"), circleColor: RED });
    s.addText(st.title, {
      x: x + 0.25, y: y + 2.15, w: cardW - 0.5, h: 0.5, fontFace: "Cambria", bold: true, fontSize: 17, color: DARK,
      isTextBox: true, margin: 0, align: "center",
    });
    s.addText(st.body, {
      x: x + 0.35, y: y + 2.65, w: cardW - 0.7, h: 1.35, fontFace: "Calibri", fontSize: 12.5, color: GRAY,
      isTextBox: true, margin: 0, align: "center", valign: "top", lineSpacingMultiple: 1.25,
    });
    if (i < steps.length - 1) {
      s.addText("→", { x: x + cardW + 0.02, y: y + 1.55, w: 0.32, h: 0.6, fontFace: "Arial", bold: true, fontSize: 26, color: AMBER, isTextBox: true, margin: 0, align: "center" });
    }
  });
}

/* ---------------- Slide 5: Scope boundaries ---------------- */
{
  const s = pres.addSlide();
  s.background = { color: WHITE };
  footer(s, "Scope Boundaries", "05", false);

  s.addText("If a capability already exists, we feed it. We don't rebuild it.", {
    x: 0.7, y: 0.85, w: 11.8, h: 0.9, fontFace: "Cambria", bold: true, fontSize: 27, color: DARK, isTextBox: true, margin: 0,
  });
  s.addText("Deliberately scoped to avoid duplicating work already in flight.", {
    x: 0.7, y: 1.65, w: 10.8, h: 0.4, fontFace: "Calibri", fontSize: 14, color: GRAY, isTextBox: true, margin: 0,
  });

  // In scope column
  const colY = 2.35, colW = 5.6, colH = 4.4;
  s.addShape("roundRect", { x: 0.7, y: colY, w: colW, h: colH, rectRadius: 0.08, fill: { color: "EFF7F1" }, line: { type: "none" } });
  s.addText("What this delivers", { x: 1.05, y: colY + 0.3, w: colW - 0.7, h: 0.4, fontFace: "Cambria", bold: true, fontSize: 16, color: "1E7A3D", isTextBox: true, margin: 0 });
  const inScope = ["A target list of at-risk policies", "The reason each one is at risk", "A recommended action, ready for approval"];
  inScope.forEach((t, i) => {
    const iy = colY + 1.15 + i * 1.05;
    s.addImage({ path: ICON("in_scope", "dark"), x: 1.05, y: iy, w: 0.38, h: 0.38 });
    s.addText(t, { x: 1.6, y: iy - 0.08, w: colW - 1.25, h: 0.55, fontFace: "Calibri", fontSize: 14.5, color: DARK, isTextBox: true, margin: 0, valign: "middle" });
  });

  // Out of scope column
  s.addShape("roundRect", { x: 6.7, y: colY, w: colW, h: colH, rectRadius: 0.08, fill: { color: "FBEEF0" }, line: { type: "none" } });
  s.addText("What stays where it is", { x: 7.05, y: colY + 0.3, w: colW - 0.7, h: 0.4, fontFace: "Cambria", bold: true, fontSize: 16, color: DEEP_RED, isTextBox: true, margin: 0 });
  const outScope = [
    ["Offer execution", "self-service portal"],
    ["Renewal batch processing", "policy admin system"],
    ["Loyalty / no-claims discounts", "existing rating systems"],
    ["Owning the customer channel", "self-service portal"],
    ["Underwriter pricing copilot", "AccuWrite"],
  ];
  outScope.forEach((pair, i) => {
    const iy = colY + 0.9 + i * 0.68;
    s.addImage({ path: ICON("out_scope", "dark"), x: 7.05, y: iy, w: 0.3, h: 0.3 });
    s.addText(pair[0], { x: 7.5, y: iy - 0.07, w: 3.1, h: 0.44, fontFace: "Calibri", bold: true, fontSize: 12.5, color: DARK, isTextBox: true, margin: 0, valign: "middle" });
    s.addText(pair[1], { x: 7.5, y: iy + 0.28, w: 3.1, h: 0.3, fontFace: "Calibri", italic: true, fontSize: 10.5, color: GRAY, isTextBox: true, margin: 0 });
  });
}

/* ---------------- Slide 6: Proof it works ---------------- */
{
  const s = pres.addSlide();
  s.background = { color: DARK };
  footer(s, "Proof It Works", "06", true);

  s.addText("Built and tested — not just designed.", {
    x: 0.7, y: 0.85, w: 11.8, h: 0.9, fontFace: "Cambria", bold: true, fontSize: 30, color: WHITE, isTextBox: true, margin: 0,
  });
  s.addText("Run on a realistic synthetic policy book, before any client data was requested.", {
    x: 0.7, y: 1.65, w: 10.8, h: 0.4, fontFace: "Calibri", fontSize: 14, color: "C9C9C9", isTextBox: true, margin: 0,
  });

  const stats = [
    { num: "0.76", label: "Model accuracy (AUC)", sub: "target: ≥ 0.72" },
    { num: "2.7×", label: "Better than random at flagging risk", sub: "target: ≥ 2.5×" },
    { num: "0.02", label: "Calibration error", sub: "target: ≤ 0.05" },
  ];
  const cardW = 3.75, gap = 0.35, startX = 0.7, y = 2.5, cardH = 2.1;
  stats.forEach((st, i) => {
    const x = startX + i * (cardW + gap);
    s.addShape("roundRect", { x, y, w: cardW, h: cardH, rectRadius: 0.08, fill: { color: "262626" }, line: { type: "none" } });
    s.addText(st.num, { x: x + 0.2, y: y + 0.22, w: cardW - 0.4, h: 0.95, fontFace: "Cambria", bold: true, fontSize: 44, color: RED, isTextBox: true, margin: 0, align: "center" });
    s.addText(st.label, { x: x + 0.25, y: y + 1.2, w: cardW - 0.5, h: 0.5, fontFace: "Calibri", fontSize: 12.5, color: WHITE, isTextBox: true, margin: 0, align: "center", valign: "top" });
    s.addText(st.sub, { x: x + 0.25, y: y + 1.68, w: cardW - 0.5, h: 0.3, fontFace: "Calibri", italic: true, fontSize: 10.5, color: "9A9A9A", isTextBox: true, margin: 0, align: "center" });
  });

  s.addShape("roundRect", { x: 0.7, y: 4.95, w: 11.75, h: 1.3, rectRadius: 0.08, fill: { color: "262626" }, line: { type: "none" } });
  iconCircle(s, { x: 1.0, y: 5.22, d: 0.78, icon: ICON("ask_layers", "white"), circleColor: AMBER, iconScale: 0.55 });
  s.addText("A/B holdout, built in from day one", { x: 2.05, y: 5.12, w: 10.1, h: 0.4, fontFace: "Cambria", bold: true, fontSize: 15, color: WHITE, isTextBox: true, margin: 0 });
  s.addText("A control group receives no treatment, so any retention uplift we report is measured, not assumed — a defensible business case, not a demo.", {
    x: 2.05, y: 5.52, w: 10.1, h: 0.65, fontFace: "Calibri", fontSize: 12.5, color: "C9C9C9", isTextBox: true, margin: 0, lineSpacingMultiple: 1.2,
  });
}

/* ---------------- Slide 7: Guardrails ---------------- */
{
  const s = pres.addSlide();
  s.background = { color: WHITE };
  footer(s, "Guardrails", "07", false);

  s.addText("Nothing reaches a customer without a person signing off.", {
    x: 0.7, y: 0.85, w: 11.8, h: 0.9, fontFace: "Cambria", bold: true, fontSize: 28, color: DARK, isTextBox: true, margin: 0,
  });
  s.addText("Fairness and compliance are design constraints, not an afterthought.", {
    x: 0.7, y: 1.65, w: 10.8, h: 0.4, fontFace: "Calibri", fontSize: 14, color: GRAY, isTextBox: true, margin: 0,
  });

  const guards = [
    { icon: "guard_lock", title: "Role-based access", body: "Enforced on the server, not just hidden in the screen — every tier sees only what it should." },
    { icon: "guard_shield", title: "Scores stay internal", body: "Frontline staff and customers never see the raw risk number — only the reason and the recommendation." },
    { icon: "guard_approve", title: "Human approval, always", body: "Every recommendation is approved, rejected, or modified by a person before it goes anywhere." },
    { icon: "guard_audit", title: "Full audit trail", body: "Who saw what, who approved what, and when — logged for every action, every time." },
  ];
  const cardW = 2.8, gap = 0.28, startX = 0.7, y = 2.55, cardH = 3.5;
  guards.forEach((g, i) => {
    const x = startX + i * (cardW + gap);
    s.addShape("roundRect", { x, y, w: cardW, h: cardH, rectRadius: 0.08, fill: { color: LIGHT_GRAY }, line: { type: "none" } });
    iconCircle(s, { x: x + (cardW - 0.95) / 2, y: y + 0.35, d: 0.95, icon: ICON(g.icon, "white"), circleColor: DEEP_RED, iconScale: 0.5 });
    s.addText(g.title, { x: x + 0.18, y: y + 1.5, w: cardW - 0.36, h: 0.65, fontFace: "Cambria", bold: true, fontSize: 13.5, color: DARK, isTextBox: true, margin: 0, align: "center", valign: "top" });
    s.addText(g.body, { x: x + 0.22, y: y + 2.15, w: cardW - 0.44, h: 1.2, fontFace: "Calibri", fontSize: 10.8, color: GRAY, isTextBox: true, margin: 0, align: "center", valign: "top", lineSpacingMultiple: 1.2 });
  });
}

/* ---------------- Slide 8: The ask ---------------- */
{
  const s = pres.addSlide();
  s.background = { color: RED };

  s.addShape("ellipse", { x: -1.5, y: 4.2, w: 5.5, h: 5.5, fill: { color: DEEP_RED, transparency: 40 }, line: { type: "none" } });

  s.addText("CGI", { x: 0.7, y: 0.5, w: 2, h: 0.5, fontFace: "Arial", bold: true, fontSize: 20, color: WHITE, isTextBox: true, margin: 0 });

  s.addText("The smallest dataset that proves the next step.", {
    x: 0.7, y: 1.15, w: 11.5, h: 1.0, fontFace: "Cambria", bold: true, fontSize: 32, color: WHITE, isTextBox: true, margin: 0,
  });
  s.addText("Not a full data extract. A staged path, so value is proven before any commitment grows.", {
    x: 0.72, y: 2.0, w: 10, h: 0.5, fontFace: "Calibri", fontSize: 15, color: "FBD7DE", isTextBox: true, margin: 0,
  });

  const stages = [
    { n: "1", title: "Aggregate numbers", body: "Lapse rate by line and segment — numbers you likely already have on hand." },
    { n: "2", title: "Validate the model", body: "Confirm our five risk drivers match the reasons you're actually seeing." },
    { n: "3", title: "Decide together", body: "Only then discuss a pseudonymised extract and the next phase." },
  ];
  const cardW = 3.75, gap = 0.35, startX = 0.7, y = 2.85, cardH = 2.55;
  stages.forEach((st, i) => {
    const x = startX + i * (cardW + gap);
    s.addShape("roundRect", { x, y, w: cardW, h: cardH, rectRadius: 0.08, fill: { color: DEEP_RED }, line: { type: "none" } });
    s.addShape("ellipse", { x: x + 0.28, y: y + 0.28, w: 0.6, h: 0.6, fill: { color: WHITE }, line: { type: "none" } });
    s.addText(st.n, { x: x + 0.28, y: y + 0.28, w: 0.6, h: 0.6, fontFace: "Cambria", bold: true, fontSize: 20, color: RED, isTextBox: true, margin: 0, align: "center", valign: "middle" });
    s.addText(st.title, { x: x + 0.28, y: y + 1.05, w: cardW - 0.56, h: 0.45, fontFace: "Cambria", bold: true, fontSize: 15, color: WHITE, isTextBox: true, margin: 0 });
    s.addText(st.body, { x: x + 0.28, y: y + 1.5, w: cardW - 0.56, h: 0.9, fontFace: "Calibri", fontSize: 11.5, color: "FBD7DE", isTextBox: true, margin: 0, lineSpacingMultiple: 1.25 });
  });

  s.addText("The ask: a business sponsor to champion Stage 1, and a short walkthrough to confirm we're not duplicating the self-service portal's existing offer work.", {
    x: 0.7, y: 5.75, w: 11.9, h: 0.8, fontFace: "Calibri", italic: true, fontSize: 13, color: "FDEDEF", isTextBox: true, margin: 0, lineSpacingMultiple: 1.25,
  });
}

pres.writeFile({ fileName: "/home/user/CGI-test-PPT/renewal-intelligence/RenewalIntelligence-Pitch.pptx" })
  .then(fileName => console.log("Wrote:", fileName))
  .catch(err => { console.error(err); process.exit(1); });
