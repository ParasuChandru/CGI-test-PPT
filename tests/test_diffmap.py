import os

import pytest

import diffmap
import indexer

from conftest import SAMPLE_DIR

DIFFS_DIR = os.path.join(SAMPLE_DIR, "diffs")


def _read(name):
    with open(os.path.join(DIFFS_DIR, name), encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def sample_con(tmp_path_factory):
    db_path = str(tmp_path_factory.mktemp("diffmap_db") / "graph.db")
    indexer.index_path(db_path, SAMPLE_DIR)
    con = indexer.open_db(db_path)
    yield con
    con.close()


def test_change_inside_one_function_seeds_exactly_that_function(sample_con):
    text = _read("change_inside_one_function.diff")
    r = diffmap.map_diff(sample_con, diff_text=text)
    assert r["seed_symbols"] == ["get_user"]


def test_change_spanning_two_functions_seeds_both(sample_con):
    text = _read("change_spanning_two_functions.diff")
    r = diffmap.map_diff(sample_con, diff_text=text)
    assert set(r["seed_symbols"]) == {"get_user", "create_user"}


def test_import_only_change_is_unattributed(sample_con):
    text = _read("import_only_change.diff")
    r = diffmap.map_diff(sample_con, diff_text=text)
    assert r["seed_symbols"] == []
    assert "py/api.py" in r["unattributed_files"]


def test_new_file_seeds_nothing_and_is_informational(sample_con):
    text = _read("new_file.diff")
    r = diffmap.map_diff(sample_con, diff_text=text)
    assert "py/new_module.py" in r["new_files"]
    assert r["seed_symbols"] == []


def test_deleted_function_appears_in_deleted_symbols(sample_con):
    text = _read("deleted_function.diff")
    r = diffmap.map_diff(sample_con, diff_text=text)
    assert "legacy_lookup" in r["deleted_symbols"]


def test_malformed_diff_raises_clean_error(sample_con):
    with pytest.raises(diffmap.DiffParseError):
        diffmap.map_diff(sample_con, diff_text="this is not a diff at all\njust some text\n")


def test_empty_diff_raises_clean_error(sample_con):
    with pytest.raises(diffmap.DiffParseError):
        diffmap.map_diff(sample_con, diff_text="")


def test_hunk_header_single_line_form_no_comma():
    changed_lines, new_files, hunk_defs = diffmap.parse_unified_diff(
        "--- a/x.py\n+++ b/x.py\n@@ -6 +6 @@\n-old\n+new\n"
    )
    assert changed_lines["x.py"] == {6}


def test_hunk_header_with_comma_form():
    changed_lines, new_files, hunk_defs = diffmap.parse_unified_diff(
        "--- a/x.py\n+++ b/x.py\n@@ -6,2 +6,3 @@\n-old\n-old2\n+new\n+new2\n+new3\n"
    )
    assert changed_lines["x.py"] == {6, 7, 8}
