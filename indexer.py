"""Walk a repository, parse Python/Java/Gosu source, and persist a symbol
dependency graph to SQLite.

See IMPACT_STUDIO_SPEC.md section 4 for the schema and extraction rules
this module implements.
"""

import bisect
import hashlib
import os
import re
import sqlite3
import time

import tree_sitter
import tree_sitter_java as tsjava
import tree_sitter_python as tspython

import gosu_parser

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
  id INTEGER PRIMARY KEY, path TEXT UNIQUE, lang TEXT, hash TEXT, loc INTEGER
);
CREATE TABLE IF NOT EXISTS symbols (
  id INTEGER PRIMARY KEY, file_id INTEGER, name TEXT, kind TEXT,
  line INTEGER, end_line INTEGER, qualified TEXT
);
CREATE TABLE IF NOT EXISTS refs (
  id INTEGER PRIMARY KEY, file_id INTEGER, name TEXT, line INTEGER,
  src_symbol_id INTEGER
);
CREATE TABLE IF NOT EXISTS file_deps (src_file_id INTEGER, dst_module TEXT);

CREATE INDEX IF NOT EXISTS ix_sym_name ON symbols(name);
CREATE INDEX IF NOT EXISTS ix_sym_file ON symbols(file_id);
CREATE INDEX IF NOT EXISTS ix_sym_span ON symbols(file_id, line, end_line);
CREATE INDEX IF NOT EXISTS ix_ref_name ON refs(name);
CREATE INDEX IF NOT EXISTS ix_ref_file ON refs(file_id);
"""

EXT_TO_LANG = {
    ".py": "python",
    ".java": "java",
    ".gs": "gosu",
    ".gsx": "gosu",
    ".gst": "gosu",
}

SKIP_MARKERS = ("/.git/", "/node_modules/", "/__pycache__/", "/target/", "/build/")

_PY_LANGUAGE = tree_sitter.Language(tspython.language())
_JAVA_LANGUAGE = tree_sitter.Language(tsjava.language())
_PY_PARSER = tree_sitter.Parser(_PY_LANGUAGE)
_JAVA_PARSER = tree_sitter.Parser(_JAVA_LANGUAGE)

_IDENT_RE = re.compile(r"^\w+$")


def open_db(db_path):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def _should_skip(rel_path):
    norm = "/" + rel_path.replace(os.sep, "/")
    return any(marker in norm for marker in SKIP_MARKERS)


def _iter_source_files(root_dir):
    for dirpath, dirnames, filenames in os.walk(root_dir):
        rel_dir = os.path.relpath(dirpath, root_dir)
        rel_dir = "" if rel_dir == "." else rel_dir
        dirnames[:] = [
            d for d in dirnames if not _should_skip(os.path.join(rel_dir, d) + "/")
        ]
        for fname in filenames:
            ext = os.path.splitext(fname)[1]
            if ext not in EXT_TO_LANG:
                continue
            rel_path = os.path.join(rel_dir, fname) if rel_dir else fname
            rel_path = rel_path.replace(os.sep, "/")
            if _should_skip(rel_path):
                continue
            yield rel_path, EXT_TO_LANG[ext]


class _LineIndex:
    """Maps a byte offset to a 1-indexed line number.

    Node.start_point/.end_point have been observed to segfault this
    tree-sitter binding on some real-world files (deep native crash, not a
    catchable exception -- see extract_python below). Node.start_byte/
    end_byte are safe, so every line number in this module is derived from
    those via this index instead of the Point accessors.
    """

    def __init__(self, data):
        offsets = []
        idx = data.find(b"\n")
        while idx != -1:
            offsets.append(idx)
            idx = data.find(b"\n", idx + 1)
        self._offsets = offsets

    def line_of(self, byte_offset):
        return bisect.bisect_left(self._offsets, byte_offset) + 1


# ---------------------------------------------------------------------------
# Python extraction
# ---------------------------------------------------------------------------

def _iter_nodes(root):
    """Iterative pre-order walk of a tree-sitter (sub)tree.

    Real-world files can nest deeply enough (long chained calls, long
    boolean/binary-op chains) that a recursive Python walker overflows the
    C stack -- which segfaults rather than raising a catchable exception.
    An explicit stack keeps this bounded by heap, not call depth.
    """
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(node.children)


def extract_python(text):
    # A single combined pass, not one walk per concern: re-walking the same
    # parsed tree from the root a second time has been observed to corrupt
    # native state in this tree-sitter binding and segfault (not a
    # catchable exception) on large real-world files. One pass sidesteps it
    # and is cheaper besides.
    data = text.encode("utf-8")
    tree = _PY_PARSER.parse(data)
    lines = _LineIndex(data)
    defs, refs, deps = [], [], []
    for node in _iter_nodes(tree.root_node):
        if node.type == "function_definition":
            name = node.child_by_field_name("name")
            if name is not None:
                defs.append({
                    "name": name.text.decode("utf-8", "replace"),
                    "kind": "function",
                    "line": lines.line_of(node.start_byte),
                    "end_line": lines.line_of(node.end_byte),
                })
        elif node.type == "class_definition":
            name = node.child_by_field_name("name")
            if name is not None:
                defs.append({
                    "name": name.text.decode("utf-8", "replace"),
                    "kind": "class",
                    "line": lines.line_of(node.start_byte),
                    "end_line": lines.line_of(node.end_byte),
                })
        elif node.type == "call":
            fn = node.child_by_field_name("function")
            if fn is not None:
                raw = fn.text.decode("utf-8", "replace")
                name = raw.rsplit(".", 1)[-1]
                if _IDENT_RE.match(name):
                    refs.append({"name": name, "line": lines.line_of(node.start_byte)})
        elif node.type == "import_statement":
            for child in node.children:
                if child.type == "dotted_name":
                    deps.append(child.text.decode("utf-8", "replace"))
                elif child.type == "aliased_import":
                    dn = child.child_by_field_name("name")
                    if dn is not None:
                        deps.append(dn.text.decode("utf-8", "replace"))
        elif node.type == "import_from_statement":
            for child in node.children:
                if child.type in ("dotted_name", "relative_import"):
                    deps.append(child.text.decode("utf-8", "replace"))
                    break
    return defs, refs, deps


# ---------------------------------------------------------------------------
# Java extraction
# ---------------------------------------------------------------------------

_JAVA_DEF_KIND = {
    "method_declaration": "method",
    "constructor_declaration": "method",
    "class_declaration": "class",
    "interface_declaration": "interface",
}


def extract_java(text):
    data = text.encode("utf-8")
    tree = _JAVA_PARSER.parse(data)
    lines = _LineIndex(data)
    defs, refs, deps = [], [], []
    for node in _iter_nodes(tree.root_node):
        kind = _JAVA_DEF_KIND.get(node.type)
        if kind is not None:
            name = node.child_by_field_name("name")
            if name is not None:
                defs.append({
                    "name": name.text.decode("utf-8", "replace"),
                    "kind": kind,
                    "line": lines.line_of(node.start_byte),
                    "end_line": lines.line_of(node.end_byte),
                })
        elif node.type == "method_invocation":
            name = node.child_by_field_name("name")
            if name is not None:
                text_ = name.text.decode("utf-8", "replace")
                if _IDENT_RE.match(text_):
                    refs.append({"name": text_, "line": lines.line_of(node.start_byte)})
        elif node.type == "object_creation_expression":
            type_node = node.child_by_field_name("type")
            if type_node is not None:
                raw = type_node.text.decode("utf-8", "replace")
                name = raw.rsplit(".", 1)[-1]
                name = re.sub(r"<.*$", "", name)
                if _IDENT_RE.match(name):
                    refs.append({"name": name, "line": lines.line_of(node.start_byte)})
        elif node.type == "import_declaration":
            raw = node.text.decode("utf-8", "replace")
            raw = raw.strip()
            if raw.endswith(";"):
                raw = raw[:-1]
            raw = raw.replace("import", "", 1).strip()
            raw = raw.replace("static", "", 1).strip() if raw.startswith("static") else raw
            if raw:
                deps.append(raw)
    return defs, refs, deps


# ---------------------------------------------------------------------------
# Shared: enclosing-symbol attribution + qualified names (spec 4.3)
# ---------------------------------------------------------------------------

def _qualified_names(defs):
    # Process outermost (largest span) first, so each def's chosen parent --
    # which always has a strictly larger span -- is already resolved by the
    # time we reach it. This avoids recursion entirely (a large file can
    # otherwise blow the C stack) and sidesteps any cycle between defs that
    # happen to share an identical span (excluded from "contains" below).
    order = sorted(range(len(defs)), key=lambda i: defs[i]["end_line"] - defs[i]["line"], reverse=True)
    qualified = [None] * len(defs)

    for i in order:
        d = defs[i]
        containers = [
            j for j in range(len(defs))
            if j != i
            and defs[j]["line"] <= d["line"]
            and defs[j]["end_line"] >= d["end_line"]
            and (defs[j]["line"], defs[j]["end_line"]) != (d["line"], d["end_line"])
        ]
        if not containers:
            qualified[i] = d["name"]
        else:
            parent = min(containers, key=lambda j: defs[j]["end_line"] - defs[j]["line"])
            parent_q = qualified[parent] or defs[parent]["name"]
            qualified[i] = parent_q + "." + d["name"]

    return qualified


def _enclosing_symbol_id(ref_line, defs, symbol_ids):
    candidates = [
        i for i, d in enumerate(defs) if d["line"] <= ref_line <= d["end_line"]
    ]
    if not candidates:
        return None
    best = max(candidates, key=lambda i: defs[i]["line"])
    return symbol_ids[best]


# ---------------------------------------------------------------------------
# Top-level indexing
# ---------------------------------------------------------------------------

def _delete_file_rows(con, file_id):
    con.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))
    con.execute("DELETE FROM refs WHERE file_id = ?", (file_id,))
    con.execute("DELETE FROM file_deps WHERE src_file_id = ?", (file_id,))


def _index_one_file(con, root_dir, rel_path, lang):
    abs_path = os.path.join(root_dir, rel_path)
    try:
        with open(abs_path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return False

    digest = hashlib.sha1(raw).hexdigest()
    row = con.execute("SELECT id, hash FROM files WHERE path = ?", (rel_path,)).fetchone()
    if row is not None and row["hash"] == digest:
        return False

    text = raw.decode("utf-8", errors="replace")
    loc = text.count("\n") + (1 if text and not text.endswith("\n") else 0)

    try:
        if lang == "python":
            defs, refs, deps = extract_python(text)
        elif lang == "java":
            defs, refs, deps = extract_java(text)
        else:
            defs, refs, deps = gosu_parser.extract(text)
    except Exception:
        defs, refs, deps = [], [], []

    if row is not None:
        file_id = row["id"]
        _delete_file_rows(con, file_id)
        con.execute(
            "UPDATE files SET lang = ?, hash = ?, loc = ? WHERE id = ?",
            (lang, digest, loc, file_id),
        )
    else:
        cur = con.execute(
            "INSERT INTO files (path, lang, hash, loc) VALUES (?, ?, ?, ?)",
            (rel_path, lang, digest, loc),
        )
        file_id = cur.lastrowid

    qualified = _qualified_names(defs) if defs else []
    symbol_ids = []
    for d, q in zip(defs, qualified):
        cur = con.execute(
            "INSERT INTO symbols (file_id, name, kind, line, end_line, qualified) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (file_id, d["name"], d["kind"], d["line"], d["end_line"], q),
        )
        symbol_ids.append(cur.lastrowid)

    for r in refs:
        src_symbol_id = _enclosing_symbol_id(r["line"], defs, symbol_ids)
        con.execute(
            "INSERT INTO refs (file_id, name, line, src_symbol_id) VALUES (?, ?, ?, ?)",
            (file_id, r["name"], r["line"], src_symbol_id),
        )

    for dep in deps:
        con.execute(
            "INSERT INTO file_deps (src_file_id, dst_module) VALUES (?, ?)",
            (file_id, dep),
        )

    return True


def index_path(db_path, root_dir, progress=None):
    start = time.time()
    con = open_db(db_path)
    files_seen = 0
    files_changed = 0
    by_lang = {}

    try:
        for rel_path, lang in _iter_source_files(root_dir):
            files_seen += 1
            by_lang[lang] = by_lang.get(lang, 0) + 1
            try:
                changed = _index_one_file(con, root_dir, rel_path, lang)
            except Exception:
                changed = False
            if changed:
                files_changed += 1
            if progress is not None and files_seen % 200 == 0:
                progress(files_changed, files_seen)
        con.commit()
    finally:
        con.close()

    if progress is not None:
        progress(files_changed, files_seen)

    return {
        "files_seen": files_seen,
        "files_changed": files_changed,
        "elapsed": time.time() - start,
        "by_lang": by_lang,
    }
