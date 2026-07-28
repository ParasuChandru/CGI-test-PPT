"""Map a diff (pasted unified diff text, or a Git ref) to the seed symbols
it touches, so impact.py can run the same blast-radius analysis from a
change instead of a function name.

See IMPACT_STUDIO_SPEC.md section 7.
"""

import os
import re
import subprocess

import gosu_parser

EXT_TO_LANG = {
    ".py": "python",
    ".java": "java",
    ".gs": "gosu",
    ".gsx": "gosu",
    ".gst": "gosu",
}

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

_PY_DEF_LINE_RE = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)")
_JAVA_DEF_LINE_RE = re.compile(
    r"^\s*(?:public|private|protected|static|final|abstract|synchronized)\s+"
    r"(?:[\w<>\[\],.]+\s+)+(\w+)\s*\("
)


def _lang_for_path(path):
    ext = os.path.splitext(path)[1]
    return EXT_TO_LANG.get(ext)


def _def_name_from_line(line, lang):
    if lang == "python":
        m = _PY_DEF_LINE_RE.match(line)
        return m.group(1) if m else None
    if lang == "java":
        m = _JAVA_DEF_LINE_RE.match(line)
        return m.group(1) if m else None
    if lang == "gosu":
        m = gosu_parser.DEF_RE.match(line.lstrip("\n"))
        return m.group(2) if m else None
    return None


def _strip_prefix(path):
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


class DiffParseError(ValueError):
    pass


def parse_unified_diff(diff_text):
    """Parse unified diff text into per-file changed line numbers and
    per-file removed/added definition names (used for deleted-symbol
    detection). Raises DiffParseError on unparseable input.
    """
    if not diff_text or not diff_text.strip():
        raise DiffParseError("empty diff text")

    lines = diff_text.splitlines()
    changed_lines = {}
    new_files = set()
    hunk_defs = {}  # path -> {"removed": set(name), "added": set(name)}

    current_file = None
    current_lang = None
    old_side_is_dev_null = False
    new_line_no = None
    new_count_remaining = 0

    saw_any_hunk = False

    for raw_line in lines:
        if raw_line.startswith("--- "):
            old_path = raw_line[4:].strip()
            old_side_is_dev_null = old_path == "/dev/null"
            continue

        if raw_line.startswith("+++ "):
            new_path_raw = raw_line[4:].strip()
            if new_path_raw == "/dev/null":
                current_file = None
                current_lang = None
                continue
            current_file = _strip_prefix(new_path_raw)
            current_lang = _lang_for_path(current_file)
            changed_lines.setdefault(current_file, set())
            hunk_defs.setdefault(current_file, {"removed": set(), "added": set()})
            if old_side_is_dev_null:
                new_files.add(current_file)
            continue

        m = _HUNK_RE.match(raw_line)
        if m:
            saw_any_hunk = True
            new_start = int(m.group(3))
            new_count = int(m.group(4)) if m.group(4) is not None else 1
            new_line_no = new_start
            new_count_remaining = new_count
            continue

        if current_file is None:
            continue

        if raw_line.startswith("-") and not raw_line.startswith("---"):
            name = _def_name_from_line(raw_line[1:], current_lang)
            if name:
                hunk_defs[current_file]["removed"].add(name)
            continue

        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            if new_count_remaining > 0:
                changed_lines[current_file].add(new_line_no)
                new_line_no += 1
                new_count_remaining -= 1
            name = _def_name_from_line(raw_line[1:], current_lang)
            if name:
                hunk_defs[current_file]["added"].add(name)
            continue

        # context line (only present with non-zero context diffs)
        if raw_line.startswith(" "):
            if new_count_remaining > 0:
                new_line_no += 1
                new_count_remaining -= 1

    if not saw_any_hunk:
        raise DiffParseError("no diff hunks found (expected '@@ -a,b +c,d @@' headers)")

    return changed_lines, new_files, hunk_defs


def diff_from_git_ref(repo_dir, ref):
    if not re.match(r"^[\w./~^-]+$", ref):
        raise DiffParseError(f"invalid git ref: {ref!r}")
    try:
        result = subprocess.run(
            ["git", "diff", "--unified=0", ref],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        raise DiffParseError(f"git diff against {ref!r} timed out")
    if result.returncode != 0:
        raise DiffParseError(f"git diff failed: {result.stderr[-400:]}")
    return result.stdout


def changed_symbols(con, file_path, changed_lines):
    """Map changed line numbers to their enclosing symbols."""
    rows = con.execute(
        """
        SELECT s.name, s.kind, s.line, s.end_line
        FROM symbols s JOIN files f ON f.id = s.file_id
        WHERE f.path = ?""",
        (file_path,),
    ).fetchall()
    hits = set()
    unattributed = []
    for ln in changed_lines:
        cands = [r for r in rows if r["line"] <= ln <= r["end_line"]]
        if cands:
            hits.add(max(cands, key=lambda r: r["line"])["name"])
        else:
            unattributed.append(ln)
    return hits, unattributed


def map_diff(con, diff_text=None, git_ref=None, repo_dir=None):
    """Top-level entry point: produce the section 7.5 output shape
    (minus the symbol_impact union, which the caller adds via
    ImpactEngine.multi_symbol_impact(seed_symbols))."""
    if git_ref:
        if not repo_dir:
            raise DiffParseError("git_ref requires a repo workspace")
        diff_text = diff_from_git_ref(repo_dir, git_ref)
    elif not diff_text:
        raise DiffParseError("no diff_text or git_ref provided")

    changed_lines, new_files, hunk_defs = parse_unified_diff(diff_text)

    known_files = {
        row[0] for row in con.execute("SELECT path FROM files").fetchall()
    }

    seed_symbols = set()
    unattributed_files = []
    deleted_symbols = []

    for path, lines in changed_lines.items():
        if path in new_files or path not in known_files:
            if path not in new_files:
                new_files.add(path)  # unindexed file: treat as new/informational
            continue

        hits, unattributed = changed_symbols(con, path, lines)
        seed_symbols.update(hits)
        if unattributed:
            unattributed_files.append(path)

        defs = hunk_defs.get(path, {"removed": set(), "added": set()})
        current_names = {
            row[0]
            for row in con.execute(
                "SELECT s.name FROM symbols s JOIN files f ON f.id = s.file_id WHERE f.path = ?",
                (path,),
            ).fetchall()
        }
        for name in defs["removed"] - defs["added"]:
            if name not in current_names:
                deleted_symbols.append(name)

    return {
        "seed_symbols": sorted(seed_symbols),
        "deleted_symbols": sorted(set(deleted_symbols)),
        "unattributed_files": sorted(set(unattributed_files)),
        "new_files": sorted(new_files),
    }
