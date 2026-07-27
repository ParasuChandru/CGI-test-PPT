"""Regex-based symbol/reference extractor for Gosu (.gs/.gsx/.gst).

No tree-sitter grammar exists for Gosu, so extraction is pattern-based
rather than AST-based. See IMPACT_STUDIO_SPEC.md section 5 for the design
this module implements, and its README limitations section for what this
approach cannot see (generated entities/typelists, PCF bindings, and
name-only call resolution).

Exposes extract(text) -> (defs, refs, deps) with the same shape as the
tree-sitter-backed extractors in indexer.py.
"""

import bisect
import re

DEF_RE = re.compile(
    r'^\s*(?:(?:public|private|protected|internal|static|final|abstract|override)\s+)*'
    r'(function|construct|property\s+get|property\s+set|class|interface|enhancement|structure)'
    r'\s+(\w+)', re.M)

CALL_RE = re.compile(r'(?<![\w.])(\w+)\s*\(')        # bare calls
QUAL_RE = re.compile(r'(?<![\w.])\w+\.(\w+)\s*\(')   # obj.method() -> method
NEW_RE = re.compile(r'\bnew\s+([A-Z]\w*)')           # constructions
USES_RE = re.compile(r'^\s*uses\s+([\w.]+)', re.M)   # imports
TYPE_RE = re.compile(r':\s*([A-Z]\w*)')              # declared types

_BLOCK_COMMENT_RE = re.compile(r'/\*.*?\*/', re.S)
_LINE_COMMENT_RE = re.compile(r'//[^\n]*')
_STRING_RE = re.compile(r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'')

_KIND_MAP = {
    "function": "function",
    "construct": "method",
    "property get": "property",
    "property set": "property",
    "class": "class",
    "interface": "interface",
    "enhancement": "class",
    "structure": "structure",
}

KEYWORDS = {
    "if", "while", "for", "switch", "catch", "return", "new",
    "typeof", "foreach", "and", "or", "not",
}


def _blank(match):
    s = match.group(0)
    return "".join(c if c == "\n" else " " for c in s)


def strip_comments_and_strings(text):
    """Blank out comments and string literals, preserving line/column offsets."""
    text = _BLOCK_COMMENT_RE.sub(_blank, text)
    text = _LINE_COMMENT_RE.sub(_blank, text)
    text = _STRING_RE.sub(_blank, text)
    return text


def _brace_index(text):
    offsets = []
    prefix = [0]
    depth = 0
    for i, ch in enumerate(text):
        if ch == "{":
            depth += 1
            offsets.append(i)
            prefix.append(depth)
        elif ch == "}":
            depth -= 1
            offsets.append(i)
            prefix.append(depth)
    return offsets, prefix


def _depth_before(offsets, prefix, pos):
    idx = bisect.bisect_left(offsets, pos)
    return prefix[idx]


def _end_line_after(offsets, prefix, text, start_pos, outer_depth):
    idx = bisect.bisect_left(offsets, start_pos)
    for k in range(idx, len(offsets)):
        if prefix[k + 1] == outer_depth:
            return text.count("\n", 0, offsets[k]) + 1
    return text.count("\n") + 1


def extract(text):
    stripped = strip_comments_and_strings(text)
    offsets, prefix = _brace_index(stripped)

    defs = []
    for m in DEF_RE.finditer(stripped):
        kind_raw = re.sub(r"\s+", " ", m.group(1)).strip().lower()
        kind = _KIND_MAP.get(kind_raw, kind_raw)
        name = m.group(2)
        # Anchor on the keyword itself, not m.start(): DEF_RE's leading \s*
        # matches newlines too, so on a blank-then-blanked-comment run it can
        # swallow several lines before the real keyword.
        kw_start = m.start(1)
        start_line = stripped.count("\n", 0, kw_start) + 1
        outer_depth = _depth_before(offsets, prefix, kw_start)
        end_line = _end_line_after(offsets, prefix, stripped, m.end(), outer_depth)
        defs.append({
            "name": name,
            "kind": kind,
            "line": start_line,
            "end_line": max(end_line, start_line),
        })

    def_lines = {(d["line"], d["name"]) for d in defs}

    refs = []
    for m in CALL_RE.finditer(stripped):
        name = m.group(1)
        if name in KEYWORDS:
            continue
        preceding = stripped[:m.start(1)]
        if re.search(r"\bnew\s*$", preceding):
            continue  # already captured by NEW_RE
        line = stripped.count("\n", 0, m.start()) + 1
        if (line, name) in def_lines:
            continue
        refs.append({"name": name, "line": line})

    for m in QUAL_RE.finditer(stripped):
        name = m.group(1)
        if name in KEYWORDS:
            continue
        line = stripped.count("\n", 0, m.start()) + 1
        if (line, name) in def_lines:
            continue
        refs.append({"name": name, "line": line})

    for m in NEW_RE.finditer(stripped):
        name = m.group(1)
        line = stripped.count("\n", 0, m.start()) + 1
        refs.append({"name": name, "line": line})

    for m in TYPE_RE.finditer(stripped):
        name = m.group(1)
        if name in KEYWORDS:
            continue
        line = stripped.count("\n", 0, m.start()) + 1
        if (line, name) in def_lines:
            continue
        refs.append({"name": name, "line": line})

    deps = [m.group(1) for m in USES_RE.finditer(stripped)]

    return defs, refs, deps
