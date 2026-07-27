import os
import sqlite3

import pytest

import indexer

from conftest import SAMPLE_DIR


def _index(tmp_path, root=SAMPLE_DIR):
    db_path = str(tmp_path / "graph.db")
    stats = indexer.index_path(db_path, root)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return db_path, stats, con


def _symbols(con, path=None):
    if path is None:
        return [dict(r) for r in con.execute("SELECT s.*, f.path FROM symbols s JOIN files f ON f.id = s.file_id")]
    return [
        dict(r)
        for r in con.execute(
            "SELECT s.*, f.path FROM symbols s JOIN files f ON f.id = s.file_id WHERE f.path = ?",
            (path,),
        )
    ]


def test_language_definition_counts(tmp_path):
    _, stats, con = _index(tmp_path)
    assert stats["by_lang"]["python"] == 6
    assert stats["by_lang"]["java"] == 3
    assert stats["by_lang"]["gosu"] == 4

    py_defs = {s["name"] for s in _symbols(con) if s["path"].startswith("py/")}
    assert {"format_name", "now", "get_connection", "query", "get_user", "create_user",
            "handle_get_user", "handle_create_user", "main", "test_get_user"} <= py_defs

    java_defs = {s["name"] for s in _symbols(con) if s["path"].startswith("java/")}
    assert {"Utils", "formatName", "Service", "getUser", "fetchRaw", "Api", "handleGetUser"} <= java_defs

    gosu_defs = {s["name"] for s in _symbols(con) if s["path"].startswith("gosu/")}
    assert {"PolicyUtil", "validate", "PolicyNumber", "PolicyService", "process",
            "PolicyHandler", "handle"} <= gosu_defs


def test_enclosing_symbol_attribution(tmp_path):
    _, _, con = _index(tmp_path)
    row = con.execute(
        "SELECT r.name, r.src_symbol_id, s.name AS enclosing "
        "FROM refs r JOIN files f ON f.id = r.file_id "
        "LEFT JOIN symbols s ON s.id = r.src_symbol_id "
        "WHERE f.path = 'py/services.py' AND r.name = 'query' AND r.line = 6"
    ).fetchone()
    assert row is not None
    assert row[2] == "get_user"


def test_module_level_call_has_null_src_symbol(tmp_path):
    _, _, con = _index(tmp_path)
    row = con.execute(
        "SELECT r.src_symbol_id FROM refs r JOIN files f ON f.id = r.file_id "
        "WHERE f.path = 'py/app.py' AND r.name = 'main' AND r.line = 10"
    ).fetchone()
    assert row is not None
    assert row[0] is None


def test_reindex_with_no_changes_is_noop(tmp_path):
    db_path, stats, con = _index(tmp_path)
    con.close()
    stats2 = indexer.index_path(db_path, SAMPLE_DIR)
    assert stats2["files_changed"] == 0
    assert stats2["files_seen"] == stats["files_seen"]


def test_reindex_after_modifying_one_file(tmp_path):
    import shutil
    target = tmp_path / "workcopy"
    shutil.copytree(SAMPLE_DIR, target)
    db_path = str(tmp_path / "graph.db")

    stats0 = indexer.index_path(db_path, str(target))
    assert stats0["files_changed"] == stats0["files_seen"]

    stats1 = indexer.index_path(db_path, str(target))
    assert stats1["files_changed"] == 0

    utils_path = target / "py" / "utils.py"
    utils_path.write_text(utils_path.read_text() + "\ndef extra():\n    return 1\n")
    stats2 = indexer.index_path(db_path, str(target))
    assert stats2["files_changed"] == 1

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    names = [s["name"] for s in _symbols(con, "py/utils.py")]
    assert names.count("extra") == 1
    assert names.count("format_name") == 1  # old symbols not duplicated


def test_malformed_file_does_not_abort_run(tmp_path):
    target = tmp_path / "badrepo"
    target.mkdir()
    (target / "bad.py").write_bytes(b"\xff\xfe not valid utf8 \x00\x01 def f(:\n")
    (target / "good.py").write_text("def good():\n    return 1\n")
    db_path = str(tmp_path / "graph.db")
    stats = indexer.index_path(db_path, str(target))
    assert stats["files_seen"] == 2
    con = sqlite3.connect(db_path)
    names = [r[0] for r in con.execute("SELECT name FROM symbols")]
    assert "good" in names


def test_skips_ignored_directories(tmp_path):
    target = tmp_path / "repo"
    (target / ".git").mkdir(parents=True)
    (target / ".git" / "hooks.py").write_text("def hooked():\n    pass\n")
    (target / "node_modules" / "pkg").mkdir(parents=True)
    (target / "node_modules" / "pkg" / "index.py").write_text("def ignored():\n    pass\n")
    (target / "src").mkdir()
    (target / "src" / "main.py").write_text("def real_one():\n    pass\n")
    db_path = str(tmp_path / "graph.db")
    stats = indexer.index_path(db_path, str(target))
    assert stats["files_seen"] == 1
    con = sqlite3.connect(db_path)
    names = [r[0] for r in con.execute("SELECT name FROM symbols")]
    assert names == ["real_one"]
