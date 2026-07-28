"""Flask server, background indexing jobs, and the inlined UI for Impact
Studio. See IMPACT_STUDIO_SPEC.md section 8.
"""

import argparse
import os
import re
import sqlite3
import subprocess
import threading
import time
import uuid

from flask import Flask, jsonify, request, Response

import diffmap
import indexer
from impact import ImpactEngine

APP_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACES_DIR = os.path.join(APP_DIR, "workspaces")

app = Flask(__name__)

JOBS = {}
REPOS = {}
_INFLIGHT = {}  # repo_key -> job_id, for jobs currently running


# ---------------------------------------------------------------------------
# Git / URL handling (spec 8.2, 8.3)
# ---------------------------------------------------------------------------

_URL_SCHEME_RE = re.compile(r"^(https://|git@|http://)")
_URL_BAD_CHARS_RE = re.compile(r"[;&|`$\n ]")


def validate_git_url(url):
    if not _URL_SCHEME_RE.match(url):
        raise ValueError("URL must start with https://, http://, or git@")
    if _URL_BAD_CHARS_RE.search(url):
        raise ValueError("URL contains disallowed characters")


def slugify(text, max_len=60):
    s = text.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return (s or "repo")[:max_len]


def clone_repo(url, dest, branch=None):
    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [url, dest]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        raise RuntimeError("git clone timed out after 600s")
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-400:])


def update_repo(dest):
    try:
        r1 = subprocess.run(
            ["git", "fetch", "--depth", "1", "origin"],
            cwd=dest, capture_output=True, text=True, timeout=600,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("git fetch timed out after 600s")
    if r1.returncode != 0:
        raise RuntimeError(r1.stderr[-400:])
    r2 = subprocess.run(
        ["git", "reset", "--hard", "origin/HEAD"],
        cwd=dest, capture_output=True, text=True, timeout=120,
    )
    if r2.returncode != 0:
        raise RuntimeError(r2.stderr[-400:])


# ---------------------------------------------------------------------------
# Per-repo metadata (name/url/path/indexed_at), stored alongside the graph
# ---------------------------------------------------------------------------

def _write_meta(db_path, **kv):
    con = sqlite3.connect(db_path)
    try:
        con.execute("CREATE TABLE IF NOT EXISTS studio_meta (key TEXT PRIMARY KEY, value TEXT)")
        kv["indexed_at"] = time.time()
        for k, v in kv.items():
            if v is None:
                continue
            con.execute(
                "INSERT INTO studio_meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (k, str(v)),
            )
        con.commit()
    finally:
        con.close()


def _read_meta(db_path):
    con = sqlite3.connect(db_path)
    try:
        con.execute("CREATE TABLE IF NOT EXISTS studio_meta (key TEXT PRIMARY KEY, value TEXT)")
        return dict(con.execute("SELECT key, value FROM studio_meta").fetchall())
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Background indexing job (spec 8.1)
# ---------------------------------------------------------------------------

def _run_connect_job(job_id, url=None, path=None, branch=None):
    repo_key = None
    try:
        os.makedirs(WORKSPACES_DIR, exist_ok=True)

        if path:
            if not os.path.isdir(path):
                raise ValueError(f"local path not found or not a directory: {path}")
            repo_key = slugify(path)
            name = os.path.basename(os.path.normpath(path)) or repo_key
            workspace_dir = path
            url_display = None
        else:
            validate_git_url(url)
            repo_key = slugify(url)
            name = url.rstrip("/").rsplit("/", 1)[-1]
            if name.endswith(".git"):
                name = name[:-4]
            workspace_dir = os.path.join(WORKSPACES_DIR, repo_key)
            url_display = url

            JOBS[job_id].update(phase="clone", message="Cloning repository…")
            if os.path.isdir(workspace_dir):
                update_repo(workspace_dir)
            else:
                clone_repo(url, workspace_dir, branch=branch)

        JOBS[job_id].update(phase="parse", message="Parsing & building graph…")
        db_path = os.path.join(WORKSPACES_DIR, f"{repo_key}.db")

        def progress(changed, seen):
            JOBS[job_id]["message"] = f"Indexed {changed} changed / {seen} files…"

        index_stats = indexer.index_path(db_path, workspace_dir, progress=progress)

        _write_meta(db_path, name=name, url=url_display, path=workspace_dir, branch=branch)

        eng = ImpactEngine(db_path)
        full_stats = eng.stats()
        full_stats["by_lang"] = index_stats["by_lang"]
        full_stats["elapsed"] = index_stats["elapsed"]

        REPOS[repo_key] = {
            "db": db_path,
            "path": workspace_dir,
            "name": name,
            "url": url_display,
            "stats": full_stats,
            "indexed_at": time.time(),
        }

        JOBS[job_id].update(
            status="done",
            phase="done",
            message=f"Ready — {full_stats['files']} files, {full_stats['loc']} LOC.",
            repo=repo_key,
            stats=full_stats,
        )
    except Exception as e:
        JOBS[job_id].update(status="error", phase="error", message=str(e), error=str(e))
    finally:
        if repo_key is not None:
            _INFLIGHT.pop(repo_key, None)


def _rescan_workspaces():
    if not os.path.isdir(WORKSPACES_DIR):
        return
    for fname in sorted(os.listdir(WORKSPACES_DIR)):
        if not fname.endswith(".db"):
            continue
        db_path = os.path.join(WORKSPACES_DIR, fname)
        repo_key = fname[:-3]
        try:
            eng = ImpactEngine(db_path)
            stats = eng.stats()
            meta = _read_meta(db_path)
            REPOS[repo_key] = {
                "db": db_path,
                "path": meta.get("path") or os.path.join(WORKSPACES_DIR, repo_key),
                "name": meta.get("name", repo_key),
                "url": meta.get("url"),
                "stats": stats,
                "indexed_at": float(meta.get("indexed_at", time.time())),
            }
        except Exception:
            continue


# ---------------------------------------------------------------------------
# API routes (spec 8.5)
# ---------------------------------------------------------------------------

@app.route("/api/connect", methods=["POST"])
def api_connect():
    body = request.get_json(silent=True) or {}
    url = (body.get("url") or "").strip()
    path = (body.get("path") or "").strip()
    branch = (body.get("branch") or "").strip() or None

    if not url and not path:
        return jsonify({"error": "provide a repository url or a local path"}), 400

    if url:
        try:
            validate_git_url(url)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        repo_key = slugify(url)
    else:
        if not os.path.isdir(path):
            return jsonify({"error": f"local path not found or not a directory: {path}"}), 400
        repo_key = slugify(path)

    existing_job = _INFLIGHT.get(repo_key)
    if existing_job and JOBS.get(existing_job, {}).get("status") == "running":
        return jsonify({"job_id": existing_job})

    job_id = uuid.uuid4().hex
    JOBS[job_id] = {
        "status": "running", "phase": "queued", "message": "Queued…",
        "repo": None, "stats": None, "error": None,
    }
    _INFLIGHT[repo_key] = job_id

    t = threading.Thread(
        target=_run_connect_job,
        kwargs={"job_id": job_id, "url": url or None, "path": path or None, "branch": branch},
        daemon=True,
    )
    t.start()
    return jsonify({"job_id": job_id})


@app.route("/api/job/<job_id>")
def api_job(job_id):
    job = JOBS.get(job_id)
    if job is None:
        return jsonify({"error": "unknown job"}), 404
    return jsonify(job)


@app.route("/api/repos")
def api_repos():
    items = sorted(REPOS.items(), key=lambda kv: kv[1]["indexed_at"], reverse=True)
    return jsonify([
        {
            "key": key,
            "name": rep["name"],
            "url": rep["url"],
            "path": rep["path"],
            "stats": rep["stats"],
            "indexed_at": rep["indexed_at"],
        }
        for key, rep in items
    ])


def _get_repo_or_404(repo_key):
    rep = REPOS.get(repo_key)
    if rep is None:
        return None, (jsonify({"error": "repo not indexed"}), 404)
    return rep, None


@app.route("/api/<repo_key>/search")
def api_search(repo_key):
    rep, err = _get_repo_or_404(repo_key)
    if err:
        return err
    q = request.args.get("q", "")
    eng = ImpactEngine(rep["db"])
    return jsonify(eng.search(q))


@app.route("/api/<repo_key>/impact")
def api_impact(repo_key):
    rep, err = _get_repo_or_404(repo_key)
    if err:
        return err
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    eng = ImpactEngine(rep["db"])
    return jsonify(eng.symbol_impact(name))


@app.route("/api/<repo_key>/impact_from_diff", methods=["POST"])
def api_impact_from_diff(repo_key):
    rep, err = _get_repo_or_404(repo_key)
    if err:
        return err
    body = request.get_json(silent=True) or {}
    diff_text = body.get("diff_text") or None
    git_ref = (body.get("git_ref") or "").strip() or None
    if not diff_text and not git_ref:
        return jsonify({"error": "diff_text or git_ref is required"}), 400

    con = indexer.open_db(rep["db"])
    try:
        try:
            mapped = diffmap.map_diff(con, diff_text=diff_text, git_ref=git_ref, repo_dir=rep["path"])
        except diffmap.DiffParseError as e:
            return jsonify({"error": str(e)}), 400
    finally:
        con.close()

    eng = ImpactEngine(rep["db"])
    if mapped["seed_symbols"]:
        union = eng.multi_symbol_impact(mapped["seed_symbols"])
    else:
        union = {
            "seeds": [], "impacted_symbols": [], "impacted_files": {},
            "entry_points": [], "edges": [], "depth_reached": 0, "truncated": False,
        }
    return jsonify({**mapped, **union})


@app.route("/api/<repo_key>/file_impact")
def api_file_impact(repo_key):
    rep, err = _get_repo_or_404(repo_key)
    if err:
        return err
    path = request.args.get("path", "").strip()
    if not path:
        return jsonify({"error": "path is required"}), 400
    eng = ImpactEngine(rep["db"])
    return jsonify(eng.file_impact(path))


@app.route("/")
def index():
    return Response(INDEX_HTML, mimetype="text/html")


# ---------------------------------------------------------------------------
# UI (spec section 9) -- single inlined page, no build step
# ---------------------------------------------------------------------------

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Impact Studio</title>
<style>
  :root {
    --bg: #070b14;
    --panel: rgba(255,255,255,0.04);
    --panel-border: rgba(255,255,255,0.09);
    --cyan: #3ddbd9;
    --violet: #7b6bff;
    --green: #4ade80;
    --amber: #ffb454;
    --red: #ff6b81;
    --text: #e6f1ff;
    --text-dim: #8a97ad;
    --mono: ui-monospace, "SF Mono", Menlo, monospace;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body {
    margin: 0;
    font-family: var(--mono);
    color: var(--text);
    background:
      radial-gradient(60ch 60ch at 12% 8%, rgba(61,219,217,0.14), transparent 60%),
      radial-gradient(70ch 70ch at 90% 15%, rgba(123,107,255,0.14), transparent 60%),
      var(--bg);
    min-height: 100vh;
  }
  a { color: inherit; }
  .hidden { display: none !important; }

  /* ---------- Landing ---------- */
  #screen-landing { max-width: 980px; margin: 0 auto; padding: 48px 24px 80px; }
  .brand { font-size: 15px; letter-spacing: 0.08em; color: var(--text-dim); text-transform: uppercase; margin-bottom: 6px; }
  .brand span { color: var(--cyan); }
  h1 { font-size: 28px; margin: 0 0 28px; }

  .panel {
    background: var(--panel);
    border: 1px solid var(--panel-border);
    border-radius: 14px;
    backdrop-filter: blur(12px);
    padding: 24px;
  }
  .panel + .panel { margin-top: 20px; }

  label { display: block; font-size: 12px; color: var(--text-dim); margin-bottom: 6px; }
  input[type=text] {
    width: 100%;
    background: rgba(255,255,255,0.03);
    border: 1px solid var(--panel-border);
    border-radius: 8px;
    color: var(--text);
    font-family: var(--mono);
    font-size: 14px;
    padding: 10px 12px;
    outline: none;
  }
  input[type=text]:focus { border-color: var(--cyan); }

  .row { display: flex; gap: 14px; align-items: flex-end; }
  .row > div { flex: 1; }
  .row .narrow { flex: 0 0 140px; }

  button {
    font-family: var(--mono);
    cursor: pointer;
    border-radius: 8px;
    border: 1px solid var(--panel-border);
    background: rgba(255,255,255,0.04);
    color: var(--text);
    padding: 10px 16px;
    font-size: 14px;
  }
  button:hover { background: rgba(255,255,255,0.08); }
  button:disabled { opacity: 0.5; cursor: default; }
  .btn-primary {
    background: linear-gradient(120deg, var(--cyan), var(--violet));
    border: none;
    color: #06111f;
    font-weight: 600;
  }
  .btn-primary:hover { filter: brightness(1.08); }

  .chips { display: flex; gap: 8px; margin-top: 14px; flex-wrap: wrap; }
  .chip {
    font-size: 12px; padding: 6px 12px; border-radius: 999px;
    border: 1px solid var(--panel-border); color: var(--text-dim); cursor: pointer;
  }
  .chip:hover { color: var(--cyan); border-color: var(--cyan); }

  .divider { display: flex; align-items: center; gap: 12px; margin: 20px 0; color: var(--text-dim); font-size: 12px; }
  .divider::before, .divider::after { content: ""; flex: 1; height: 1px; background: var(--panel-border); }

  #status-line { margin-top: 16px; font-size: 13px; display: flex; align-items: center; gap: 10px; }
  .spinner {
    width: 14px; height: 14px; border-radius: 50%;
    border: 2px solid rgba(255,255,255,0.15); border-top-color: var(--cyan);
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  #status-line.ok { color: var(--green); }
  #status-line.err { color: var(--red); }

  .repo-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 16px; margin-top: 20px; }
  .repo-card {
    background: var(--panel); border: 1px solid var(--panel-border); border-radius: 14px;
    padding: 18px; cursor: pointer; transition: transform 0.12s ease, border-color 0.12s ease;
  }
  .repo-card:hover { transform: translateY(-2px); border-color: var(--cyan); }
  .repo-card h3 { margin: 0 0 4px; font-size: 15px; }
  .repo-card .url { color: var(--text-dim); font-size: 11px; margin-bottom: 12px; word-break: break-all; }
  .repo-card .counts { display: flex; gap: 14px; font-size: 12px; color: var(--text-dim); margin-bottom: 10px; }
  .repo-card .counts b { color: var(--text); }
  .badges { display: flex; gap: 6px; flex-wrap: wrap; }
  .badge {
    font-size: 10px; padding: 3px 8px; border-radius: 6px; text-transform: uppercase;
    letter-spacing: 0.04em; border: 1px solid var(--panel-border); color: var(--text-dim);
  }
  .badge.python { color: var(--cyan); border-color: var(--cyan); }
  .badge.java { color: var(--amber); border-color: var(--amber); }
  .badge.gosu { color: var(--violet); border-color: var(--violet); }
  .empty-note { color: var(--text-dim); font-size: 13px; margin-top: 20px; }

  /* ---------- Studio ---------- */
  #screen-studio { display: flex; height: 100vh; }
  .sidebar {
    width: 320px; flex: none; border-right: 1px solid var(--panel-border);
    padding: 20px; overflow-y: auto;
  }
  .back-link { color: var(--text-dim); font-size: 13px; cursor: pointer; margin-bottom: 16px; display: inline-block; }
  .back-link:hover { color: var(--cyan); }
  .repo-title { font-size: 16px; margin: 0 0 16px; }

  .tabs { display: flex; gap: 6px; margin-bottom: 16px; }
  .tab {
    flex: 1; text-align: center; padding: 8px; border-radius: 8px; cursor: pointer;
    border: 1px solid var(--panel-border); color: var(--text-dim); font-size: 13px;
  }
  .tab.active { color: var(--cyan); border-color: var(--cyan); background: rgba(61,219,217,0.08); }

  .tab-panel { display: none; }
  .tab-panel.active { display: block; }

  .result-item {
    padding: 10px; border-radius: 8px; border: 1px solid transparent; cursor: pointer; font-size: 13px;
  }
  .result-item:hover { border-color: var(--panel-border); background: rgba(255,255,255,0.03); }
  .result-item .kind { color: var(--text-dim); font-size: 11px; margin-left: 6px; }

  textarea {
    width: 100%; min-height: 160px; background: rgba(255,255,255,0.03);
    border: 1px solid var(--panel-border); border-radius: 8px; color: var(--text);
    font-family: var(--mono); font-size: 12px; padding: 10px; resize: vertical;
  }

  .main-panel { flex: 1; padding: 28px; overflow-y: auto; }
  .card { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 14px; padding: 20px; margin-bottom: 18px; }
  .card h2 { margin: 0 0 12px; font-size: 14px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-dim); }
  .count-badges { display: flex; gap: 20px; margin: 10px 0; }
  .count-badge { text-align: center; }
  .count-badge .n { font-size: 26px; font-weight: 600; }
  .count-badge .label { font-size: 11px; color: var(--text-dim); }
  .amber-badge {
    display: inline-block; padding: 6px 10px; border-radius: 8px; margin: 4px 6px 0 0;
    background: rgba(255,180,84,0.1); border: 1px solid var(--amber); color: var(--amber); font-size: 12px;
  }
  .file-row { padding: 10px 0; border-top: 1px solid var(--panel-border); }
  .file-row:first-child { border-top: none; }
  .file-row .path { color: var(--cyan); font-size: 13px; }
  .file-row .syms { color: var(--text-dim); font-size: 12px; margin-top: 4px; }
  .deleted-badge { color: var(--red); font-size: 12px; }
  .truncated-note { color: var(--amber); font-size: 12px; margin-top: 6px; }
</style>
</head>
<body>

<div id="screen-landing">
  <div class="brand">Code <span>Impact</span> Analyzer</div>
  <h1>Connect a repository</h1>

  <div class="panel">
    <div class="row">
      <div>
        <label for="repo-url">Git URL</label>
        <input type="text" id="repo-url" placeholder="https://github.com/org/repo.git">
      </div>
      <div class="narrow">
        <label for="repo-branch">Branch</label>
        <input type="text" id="repo-branch" placeholder="main">
      </div>
      <div class="narrow">
        <button class="btn-primary" id="btn-analyze">Analyze &rarr;</button>
      </div>
    </div>

    <div class="chips" id="quick-chips">
      <div class="chip" data-url="https://github.com/pallets/flask.git">flask</div>
      <div class="chip" data-url="https://github.com/psf/requests.git">requests</div>
      <div class="chip" data-url="https://github.com/tiangolo/fastapi.git">fastapi</div>
    </div>

    <div class="divider">or use a local path</div>
    <div class="row">
      <div>
        <input type="text" id="repo-path" placeholder="/path/to/local/repo or ./sample">
      </div>
      <div class="narrow">
        <button id="btn-analyze-local">Analyze local &rarr;</button>
      </div>
    </div>

    <div id="status-line" class="hidden">
      <div class="spinner" id="status-spinner"></div>
      <span id="status-text"></span>
    </div>
  </div>

  <div id="repo-grid" class="repo-grid"></div>
  <div id="empty-note" class="empty-note hidden">No repositories indexed yet.</div>
</div>

<div id="screen-studio" class="hidden">
  <div class="sidebar">
    <span class="back-link" id="btn-back">&larr; repositories</span>
    <h2 class="repo-title" id="studio-repo-title"></h2>

    <div class="tabs">
      <div class="tab active" data-tab="symbol">Symbol</div>
      <div class="tab" data-tab="change">Change</div>
    </div>

    <div class="tab-panel active" id="tab-symbol">
      <label for="search-input">Search a symbol</label>
      <input type="text" id="search-input" placeholder="e.g. to_native_string">
      <div id="search-results" style="margin-top:10px;"></div>
    </div>

    <div class="tab-panel" id="tab-change">
      <label for="diff-text">Paste a unified diff</label>
      <textarea id="diff-text" placeholder="diff --git a/... "></textarea>
      <label for="diff-ref" style="margin-top:12px;">or a Git ref</label>
      <input type="text" id="diff-ref" placeholder="HEAD~1">
      <button class="btn-primary" id="btn-analyze-change" style="margin-top:12px; width:100%;">Analyze change</button>
    </div>
  </div>

  <div class="main-panel" id="main-panel">
    <div class="empty-note">Search a symbol or paste a diff to see its blast radius.</div>
  </div>
</div>

<script>
(function () {
  var state = { repoKey: null, repos: [] };

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function apiGet(url) {
    return fetch(url).then(function (r) { return r.json().then(function (b) { return { ok: r.ok, body: b }; }); });
  }
  function apiPost(url, payload) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    }).then(function (r) { return r.json().then(function (b) { return { ok: r.ok, body: b }; }); });
  }

  // ---------------- Landing: connect flow ----------------

  var statusLine = document.getElementById("status-line");
  var statusText = document.getElementById("status-text");
  var statusSpinner = document.getElementById("status-spinner");
  var btnAnalyze = document.getElementById("btn-analyze");
  var btnAnalyzeLocal = document.getElementById("btn-analyze-local");

  document.querySelectorAll(".chip").forEach(function (chip) {
    chip.addEventListener("click", function () {
      document.getElementById("repo-url").value = chip.getAttribute("data-url");
    });
  });

  function setStatus(mode, message) {
    statusLine.classList.remove("hidden", "ok", "err");
    statusSpinner.classList.remove("hidden");
    if (mode === "running") {
      statusText.textContent = message;
    } else if (mode === "ok") {
      statusLine.classList.add("ok");
      statusSpinner.classList.add("hidden");
      statusText.textContent = "✓ " + message;
    } else if (mode === "err") {
      statusLine.classList.add("err");
      statusSpinner.classList.add("hidden");
      statusText.textContent = "✕ " + message;
    }
  }

  function pollJob(jobId) {
    apiGet("/api/job/" + jobId).then(function (res) {
      if (!res.ok) {
        setStatus("err", res.body.error || "job not found");
        setButtonsEnabled(true);
        return;
      }
      var job = res.body;
      if (job.status === "running") {
        setStatus("running", job.message || "Working…");
        setTimeout(function () { pollJob(jobId); }, 700);
      } else if (job.status === "done") {
        setStatus("ok", job.message);
        setButtonsEnabled(true);
        loadRepos();
      } else {
        setStatus("err", job.message || job.error || "failed");
        setButtonsEnabled(true);
      }
    }).catch(function () {
      setStatus("err", "lost contact with server");
      setButtonsEnabled(true);
    });
  }

  function setButtonsEnabled(enabled) {
    btnAnalyze.disabled = !enabled;
    btnAnalyzeLocal.disabled = !enabled;
  }

  function startConnect(payload) {
    setButtonsEnabled(false);
    setStatus("running", "Queued…");
    apiPost("/api/connect", payload).then(function (res) {
      if (!res.ok) {
        setStatus("err", res.body.error || "could not connect");
        setButtonsEnabled(true);
        return;
      }
      pollJob(res.body.job_id);
    }).catch(function () {
      setStatus("err", "could not reach server");
      setButtonsEnabled(true);
    });
  }

  btnAnalyze.addEventListener("click", function () {
    var url = document.getElementById("repo-url").value.trim();
    var branch = document.getElementById("repo-branch").value.trim();
    if (!url) { setStatus("err", "enter a repository URL"); return; }
    startConnect({ url: url, branch: branch || undefined });
  });

  btnAnalyzeLocal.addEventListener("click", function () {
    var path = document.getElementById("repo-path").value.trim();
    if (!path) { setStatus("err", "enter a local path"); return; }
    startConnect({ path: path });
  });

  function fmtNum(n) { return (n === undefined || n === null) ? "0" : n.toLocaleString(); }

  function renderRepoCard(repo) {
    var card = el("div", "repo-card");
    card.addEventListener("click", function () { openStudio(repo.key, repo.name); });

    card.appendChild(el("h3", null, repo.name));
    card.appendChild(el("div", "url", repo.url || repo.path || ""));

    var counts = el("div", "counts");
    var stats = repo.stats || {};
    counts.appendChild(el("span", null, fmtNum(stats.files) + " files"));
    counts.appendChild(el("span", null, fmtNum(stats.loc) + " LOC"));
    counts.appendChild(el("span", null, fmtNum(stats.symbols) + " symbols"));
    card.appendChild(counts);

    var badges = el("div", "badges");
    var byLang = stats.by_lang || {};
    Object.keys(byLang).forEach(function (lang) {
      badges.appendChild(el("span", "badge " + lang, lang));
    });
    card.appendChild(badges);

    return card;
  }

  function loadRepos() {
    apiGet("/api/repos").then(function (res) {
      state.repos = res.body || [];
      var grid = document.getElementById("repo-grid");
      grid.innerHTML = "";
      var emptyNote = document.getElementById("empty-note");
      if (!state.repos.length) {
        emptyNote.classList.remove("hidden");
        return;
      }
      emptyNote.classList.add("hidden");
      state.repos.forEach(function (repo) { grid.appendChild(renderRepoCard(repo)); });
    });
  }

  // ---------------- Studio screen ----------------

  function openStudio(key, name) {
    state.repoKey = key;
    document.getElementById("screen-landing").classList.add("hidden");
    document.getElementById("screen-studio").classList.remove("hidden");
    document.getElementById("studio-repo-title").textContent = name || key;
    document.getElementById("main-panel").innerHTML =
      '<div class="empty-note">Search a symbol or paste a diff to see its blast radius.</div>';
    document.getElementById("search-input").value = "";
    document.getElementById("search-results").innerHTML = "";
    document.getElementById("diff-text").value = "";
    document.getElementById("diff-ref").value = "";
  }

  document.getElementById("btn-back").addEventListener("click", function () {
    document.getElementById("screen-studio").classList.add("hidden");
    document.getElementById("screen-landing").classList.remove("hidden");
    loadRepos();
  });

  document.querySelectorAll(".tab").forEach(function (tab) {
    tab.addEventListener("click", function () {
      document.querySelectorAll(".tab").forEach(function (t) { t.classList.remove("active"); });
      document.querySelectorAll(".tab-panel").forEach(function (p) { p.classList.remove("active"); });
      tab.classList.add("active");
      document.getElementById("tab-" + tab.getAttribute("data-tab")).classList.add("active");
    });
  });

  // ---- Symbol search ----

  var searchInput = document.getElementById("search-input");
  var searchTimer = null;
  searchInput.addEventListener("input", function () {
    clearTimeout(searchTimer);
    var q = searchInput.value.trim();
    searchTimer = setTimeout(function () { runSearch(q); }, 180);
  });

  function runSearch(q) {
    var box = document.getElementById("search-results");
    if (!q) { box.innerHTML = ""; return; }
    apiGet("/api/" + state.repoKey + "/search?q=" + encodeURIComponent(q)).then(function (res) {
      box.innerHTML = "";
      (res.body || []).forEach(function (r) {
        var item = el("div", "result-item");
        item.innerHTML = '<span>' + r.name + '</span><span class="kind">' + r.kind + ' · ' + r.path + '</span>';
        item.addEventListener("click", function () { runSymbolImpact(r.name); });
        box.appendChild(item);
      });
    });
  }

  function runSymbolImpact(name) {
    apiGet("/api/" + state.repoKey + "/impact?name=" + encodeURIComponent(name)).then(function (res) {
      if (!res.ok) { renderError(res.body.error); return; }
      renderImpact(res.body, null);
    });
  }

  // ---- Change / diff mode ----

  document.getElementById("btn-analyze-change").addEventListener("click", function () {
    var diffText = document.getElementById("diff-text").value;
    var ref = document.getElementById("diff-ref").value.trim();
    var payload = {};
    if (ref) payload.git_ref = ref;
    else payload.diff_text = diffText;
    apiPost("/api/" + state.repoKey + "/impact_from_diff", payload).then(function (res) {
      if (!res.ok) { renderError(res.body.error); return; }
      renderImpact(res.body, res.body);
    });
  });

  // ---- Rendering result cards ----

  function renderError(message) {
    var panel = document.getElementById("main-panel");
    panel.innerHTML = "";
    var card = el("div", "card");
    card.innerHTML = '<h2>Error</h2><div style="color:var(--red)">' + escapeHtml(message || "unknown error") + '</div>';
    panel.appendChild(card);
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]; });
  }

  function renderImpact(result, diffResult) {
    var panel = document.getElementById("main-panel");
    panel.innerHTML = "";

    if (diffResult) {
      var seedsCard = el("div", "card");
      var h = el("h2", null, "Seeds");
      seedsCard.appendChild(h);

      if (diffResult.seed_symbols && diffResult.seed_symbols.length) {
        var seedWrap = el("div");
        diffResult.seed_symbols.forEach(function (s) {
          seedWrap.appendChild(el("span", "amber-badge", s));
        });
        seedsCard.appendChild(seedWrap);
      } else {
        seedsCard.appendChild(el("div", "empty-note", "No symbols directly seeded by this change."));
      }

      if (diffResult.deleted_symbols && diffResult.deleted_symbols.length) {
        var delWrap = el("div", null);
        delWrap.style.marginTop = "10px";
        diffResult.deleted_symbols.forEach(function (s) {
          var line = el("div", "deleted-badge", s + " — callers broken");
          delWrap.appendChild(line);
        });
        seedsCard.appendChild(delWrap);
      }

      var meta = el("div", "file-row");
      meta.style.color = "var(--text-dim)";
      meta.style.fontSize = "12px";
      meta.textContent =
        (diffResult.unattributed_files || []).length + " unattributed file(s), " +
        (diffResult.new_files || []).length + " new file(s)";
      seedsCard.appendChild(meta);

      panel.appendChild(seedsCard);
    }

    var header = el("div", "card");
    header.appendChild(el("h2", null, "Blast radius"));
    var targetLine = el("div");
    targetLine.style.fontSize = "13px";
    targetLine.style.color = "var(--text-dim)";
    if (result.target) {
      targetLine.textContent = "Target: " + result.target;
    } else if (result.seeds) {
      targetLine.textContent = result.seeds.length + " seed symbol(s)";
    }
    header.appendChild(targetLine);

    var badges = el("div", "count-badges");
    badges.appendChild(countBadge(result.impacted_symbols.length, "symbols"));
    badges.appendChild(countBadge(Object.keys(result.impacted_files || {}).length, "files"));
    badges.appendChild(countBadge((result.entry_points || []).length, "entry points"));
    header.appendChild(badges);

    var depthLine = el("div");
    depthLine.style.fontSize = "12px";
    depthLine.style.color = "var(--text-dim)";
    depthLine.textContent = "depth reached: " + result.depth_reached;
    header.appendChild(depthLine);

    if (result.truncated) {
      header.appendChild(el("div", "truncated-note", "⚠ truncated at depth/node limit"));
    }
    panel.appendChild(header);

    if (result.entry_points && result.entry_points.length) {
      var epCard = el("div", "card");
      epCard.appendChild(el("h2", null, "⚠ Retest these first"));
      var epWrap = el("div");
      result.entry_points.forEach(function (name) {
        epWrap.appendChild(el("span", "amber-badge", name));
      });
      epCard.appendChild(epWrap);
      panel.appendChild(epCard);
    }

    var filesCard = el("div", "card");
    var fileEntries = Object.entries(result.impacted_files || {});
    filesCard.appendChild(el("h2", null, "Impacted files (" + fileEntries.length + ")"));
    if (!fileEntries.length) {
      filesCard.appendChild(el("div", "empty-note", "Nothing depends on this — safe to change."));
    } else {
      fileEntries.forEach(function (entry) {
        var row = el("div", "file-row");
        row.appendChild(el("div", "path", entry[0]));
        row.appendChild(el("div", "syms", entry[1].join(", ")));
        filesCard.appendChild(row);
      });
    }
    panel.appendChild(filesCard);
  }

  function countBadge(n, label) {
    var b = el("div", "count-badge");
    b.appendChild(el("div", "n", String(n)));
    b.appendChild(el("div", "label", label));
    return b;
  }

  loadRepos();
})();
</script>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="Impact Studio server")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    _rescan_workspaces()
    app.run("0.0.0.0", args.port)


if __name__ == "__main__":
    main()
