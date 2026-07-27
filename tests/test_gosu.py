import os

import gosu_parser

from conftest import SAMPLE_DIR


def _read(name):
    with open(os.path.join(SAMPLE_DIR, "gosu", name), encoding="utf-8") as fh:
        return fh.read()


def test_commented_out_declaration_not_extracted():
    text = _read("CommentEdgeCases.gs")
    defs, refs, deps = gosu_parser.extract(text)
    names = {d["name"] for d in defs}
    assert "commentedOut" not in names


def test_string_literal_function_name_not_a_reference():
    text = _read("CommentEdgeCases.gs")
    defs, refs, deps = gosu_parser.extract(text)
    ref_names = {r["name"] for r in refs}
    assert "notAReference" not in ref_names


def test_block_comment_does_not_shift_line_numbers():
    text = _read("CommentEdgeCases.gs")
    defs, refs, deps = gosu_parser.extract(text)
    by_name = {d["name"]: d for d in defs}
    assert "FakeClass" not in by_name
    assert "fake" not in by_name
    assert by_name["checkThing"]["line"] == 20
    assert by_name["checkThing"]["end_line"] == 22


def test_keywords_excluded_from_references():
    text = """
    class K {
      function m() : boolean {
        if (true) {
          while (true) {
            for (var i in {1}) {
              return true
            }
          }
        }
        return false
      }
    }
    """
    defs, refs, deps = gosu_parser.extract(text)
    ref_names = {r["name"] for r in refs}
    assert not ({"if", "while", "for"} & ref_names)


def test_new_produces_reference_to_constructed_type():
    text = _read("PolicyService.gs")
    defs, refs, deps = gosu_parser.extract(text)
    assert any(r["name"] == "PolicyUtil" for r in refs)


def test_brace_depth_attributes_to_innermost_function():
    text = """
    class Outer {
      function outerFn() : boolean {
        function innerHelper() : boolean {
          return leafCall()
        }
        return innerHelper()
      }
    }
    """
    defs, refs, deps = gosu_parser.extract(text)
    by_name = {d["name"]: d for d in defs}
    inner = by_name["innerHelper"]
    leaf_ref = next(r for r in refs if r["name"] == "leafCall")
    assert inner["line"] <= leaf_ref["line"] <= inner["end_line"]


def test_uses_statement_captured_as_dep():
    text = _read("PolicyService.gs")
    defs, refs, deps = gosu_parser.extract(text)
    assert "PolicyUtil" in deps


def test_property_get_and_construct_kind_mapping():
    text = _read("PolicyUtil.gs")
    defs, refs, deps = gosu_parser.extract(text)
    by_name = {d["name"]: d for d in defs}
    assert by_name["PolicyNumber"]["kind"] == "property"
    assert by_name["validate"]["kind"] == "function"
