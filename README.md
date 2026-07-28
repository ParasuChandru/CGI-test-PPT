# Impact Studio

Static impact analysis for Python, Java, and Gosu codebases. Connect a repo
(Git URL or local path), and it clones/parses it, builds a symbol
dependency graph in SQLite, and answers two questions:

1. **"If I change this function, what breaks?"** — Symbol tab: search a
   symbol, see its full blast radius (transitive callers) and which of
   those are entry points you should retest first.
2. **"Here is my actual change. What do I need to retest?"** — Change tab:
   paste a unified diff (or give a Git ref like `HEAD~1`), and it maps the
   changed lines to the symbols they landed in, then runs the same
   blast-radius analysis from there.

No ML, no embeddings, no LLM inference — pure static analysis via AST
parsing (tree-sitter for Python/Java; a regex extractor for Gosu, see
below). Designed to scale to ~1M LOC; see "Performance" below for measured
numbers.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Git must be on `PATH` (used for cloning and for Git-ref diff mode).

## Running

```bash
python studio.py --port 8000
```

Open `http://localhost:8000`. Paste a Git URL (or one of the quick-start
chips: flask / requests / fastapi), or use the "local path" field to index
an already-cloned or private repo without network access — this also works
for the bundled `sample/` fixture directory (`./sample`), which exercises
all three supported languages.

**Port already in use:** `python studio.py --port 8080`. Find the occupant
with `lsof -i :8000`.

**Sharing on a LAN:** the server already binds `0.0.0.0`; reach it from
another machine at `http://<your-ip>:8000` (find your IP with
`ipconfig getifaddr en0` on macOS).

## Running the tests

```bash
pytest -v
```

51 tests across indexer, Gosu extractor, impact engine, diff mapper, API,
a real end-to-end run against `psf/requests`, and a ~400K-LOC synthetic
performance test. The integration test needs network access to clone
`psf/requests`; it skips cleanly if that's unavailable.

## Architecture

```
Git URL ─┐
         ├─► clone ─► parse ─► SQLite graph ─┬─► symbol ─► reverse-BFS ─► blast radius
local path ┘                                 │
                                             └─► diff ─► seed symbols ─► reverse-BFS ─► blast radius
```

| File | Responsibility |
|---|---|
| `indexer.py` | Walk, parse, build and persist the graph |
| `gosu_parser.py` | Regex extractor for Gosu |
| `impact.py` | Query engine over the graph (`ImpactEngine`) |
| `diffmap.py` | Map a diff to seed symbols |
| `studio.py` | Flask server, inlined UI, background indexing jobs |

Indexing is incremental: each file's content is SHA1-hashed, and unchanged
files are skipped entirely on reindex — so it's cheap enough to run on
every commit, not just on demand. Every reference records which symbol
encloses it, which is what makes `symbol_impact` a true symbol-to-symbol
graph (not just file-to-file), and what diff mode uses to map changed
lines back to the functions they landed in.

Repos indexed once are persisted at `./workspaces/<repo-key>.db` and
`./workspaces/<repo-key>/` (the clone/local-path workspace); the server
rescans `./workspaces/*.db` on startup, so a mid-demo restart doesn't lose
indexed repos.

## Gosu limitations

There is no public tree-sitter grammar for Gosu, so `gosu_parser.py` is a
line/brace-based regex extractor rather than an AST parser — a first cut,
not production-grade. Specifically:

- **Entities and typelists are generated from XML metadata**, not declared
  in Gosu source. `Policy`, `Claim`, and their fields have no source
  definition the parser can see, so a model-change's impact can't be
  resolved today. Supporting it means parsing entity metadata as a
  first-class symbol source — a phase-two piece of work.
- **PCF files bind UI to Gosu via XML.** Those call edges live outside the
  code and are invisible to this tool.
- **Regex extraction cannot resolve types**, so `svc.process()` matches
  every `process` method in the codebase, not just the one on `svc`'s
  actual type. This is true more generally, not just for Gosu (see below).

## General limitation: name-based resolution

All three languages resolve calls **by name, not by type**. Two unrelated
methods that happen to share a name are conflated — a real source of false
positives. This is a deliberate tradeoff: over-approximating a retest list
is safe (you retest a bit more than strictly necessary); under-approximating
it is not (you'd risk missing something that actually breaks). Type-aware
resolution would narrow this, at significantly more implementation cost.
Dynamic dispatch, reflection, and DI-framework wiring are also invisible to
any static parser, Gosu or otherwise.

## Performance

Measured on this build, against a synthetic ~2000-file / ~400K-LOC Python
repo with cross-file call chains (`tests/test_performance.py`):

- Cold index: **~2.4s**
- Incremental reindex, no changes: **~0.04s**
- Incremental reindex, one file touched: `files_changed == 1`, ~0.05s
- `symbol_impact` query: **well under 1s** (sub-millisecond in practice)

And against the real `psf/requests` repo (`tests/test_integration.py`):
37 files, ~12,000 LOC, ~807 symbols indexed in ~0.2–0.3s;
`to_native_string` (a small, widely-used utility) has a blast radius across
18 files with populated entry points (including the test functions that
cover it); `default_headers` (comparable in size, different role) has a
blast radius of a single file — same codebase, very different retest cost.

## Deployment

### Docker

```bash
docker build -t impact-studio .
docker run -p 8000:8000 -v $(pwd)/workspaces:/app/workspaces impact-studio
```

The volume mount preserves indexed graphs across container restarts.

### Production note

Flask's built-in server is for local/demo use only. For anything beyond
that: `gunicorn -w 4 -b 0.0.0.0:8000 studio:app`. Note that `JOBS` and
`REPOS` are in-memory and per-worker-process, so a multi-worker deployment
needs shared state (Redis, or a jobs/repos table in SQLite) to work
correctly — out of scope here.

## Demo script

1. **Connect and index** — paste `https://github.com/psf/requests.git`,
   click Analyze, watch the live status line. No config, no model — it
   clones, parses every file into an AST, and builds a dependency graph in
   a few seconds.
2. **The expensive change** — search `to_native_string`, click it. A small
   utility function with an 18-file blast radius. Point at the entry
   points card: that's the retest list, including the test functions that
   already cover it.
3. **The cheap change, for contrast** — search `default_headers`. Same
   codebase, a single-file footprint. The tool tells you which changes are
   cheap and which are expensive before you commit to one.
4. **"I have a change, not a function name"** — switch to the Change tab,
   paste a real diff or a Git ref like `HEAD~1`, click Analyze change.
   Point at the seeds card first (the functions the change actually
   touched — not obvious from reading a diff), then the entry points. If
   the diff deletes a function, its callers show up in red: "callers
   broken", not merely affected.
5. **Incremental speed** — reanalyze the same repo. Content-hashed;
   unchanged files are skipped entirely, so this is cheap enough to run on
   every commit in CI.
6. **Multi-language, including Gosu** — analyze the local `sample/`
   folder. Search `validate` (on `PolicyUtil`), show its blast radius
   crossing files. Gosu has no public parser grammar, so that extractor is
   pattern-based rather than AST — a first cut, not production-grade for
   Guidewire specifically (see Gosu limitations above).

**Closing, stated before anyone asks:** name-based resolution
over-approximates (false positives, never false negatives — the safe
direction for a retest recommendation); dynamic dispatch and DI wiring are
invisible to static analysis; and for Guidewire specifically, entities and
typelists generated from XML metadata have no anchor in the Gosu source,
so a model-change's impact isn't resolvable yet — that's the phase-two
conversation.

| Question | Answer |
|---|---|
| Does this work on our codebase? | Python, Java, and Gosu today. Each additional language is a parser mapping, not a redesign. |
| How does it scale? | See "Performance" above. |
| How is this different from an IDE's Find Usages? | An IDE resolves one hop, interactively, for one developer. This computes the transitive closure across the whole repo, headless — so it runs in CI and can gate a PR with a retest list. |
| What about false positives? | Real, and deliberate — over-approximation is the safe direction. Type resolution would narrow it. |
| Can it tell me what a model change affects? | Not yet for Guidewire entities — see the Gosu limitations section. |

## API

| Method | Route | Purpose |
|---|---|---|
| POST | `/api/connect` | `{url or path, branch?}` → `{job_id}`, or 400 `{error}` |
| GET | `/api/job/<job_id>` | Job status; 404 if unknown |
| GET | `/api/repos` | Indexed repos, newest first |
| GET | `/api/<repo>/search?q=` | Symbol search |
| GET | `/api/<repo>/impact?name=` | Blast radius for one symbol |
| POST | `/api/<repo>/impact_from_diff` | `{diff_text}` or `{git_ref}` → diff-mode result |
| GET | `/api/<repo>/file_impact?path=` | File-level dependents |
| GET | `/` | The UI |

Repo-scoped routes return 404 `{"error": "repo not indexed"}` for unknown
keys.
