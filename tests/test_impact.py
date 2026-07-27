import os

import pytest

import indexer
from impact import ImpactEngine

from conftest import SAMPLE_DIR


@pytest.fixture(scope="module")
def sample_engine(tmp_path_factory):
    db_path = str(tmp_path_factory.mktemp("impact_db") / "graph.db")
    indexer.index_path(db_path, SAMPLE_DIR)
    return ImpactEngine(db_path)


def test_stats_non_empty(sample_engine):
    s = sample_engine.stats()
    assert s["files"] > 0
    assert s["symbols"] > 0
    assert s["refs"] > 0
    assert s["loc"] > 0


def test_stats_empty_db_returns_zero(tmp_path):
    db_path = str(tmp_path / "empty.db")
    indexer.open_db(db_path).close()
    eng = ImpactEngine(db_path)
    s = eng.stats()
    assert s == {"files": 0, "loc": 0, "symbols": 0, "refs": 0}


def test_search_finds_and_limits(sample_engine):
    results = sample_engine.search("user")
    names = {r["name"] for r in results}
    assert "get_user" in names
    assert "create_user" in names
    assert len(results) <= 50


def test_leaf_symbol_impact_includes_every_layer_above(sample_engine):
    r = sample_engine.symbol_impact("format_name")
    assert set(r["impacted_symbols"]) >= {
        "get_user", "create_user", "handle_get_user", "handle_create_user", "main",
    }
    assert r["target"] == "format_name"


def test_shallow_symbol_yields_smaller_set_than_leaf(sample_engine):
    leaf = sample_engine.symbol_impact("format_name")
    shallow = sample_engine.symbol_impact("handle_get_user")
    assert len(shallow["impacted_symbols"]) < len(leaf["impacted_symbols"])


def test_symbol_with_module_level_only_caller_has_empty_impact(sample_engine):
    r = sample_engine.symbol_impact("main")
    assert r["impacted_symbols"] == []
    assert r["entry_points"] == []
    assert "<module-level>" in r["impacted_files"].get("py/app.py", [])


def test_entry_points_include_test_functions(sample_engine):
    r = sample_engine.symbol_impact("get_user")
    assert "test_get_user" in r["entry_points"]


def test_cyclic_call_graph_terminates(tmp_path):
    repo = tmp_path / "cyclic"
    repo.mkdir()
    (repo / "a.py").write_text("from b import b_func\n\n\ndef a_func():\n    return b_func()\n")
    (repo / "b.py").write_text("from a import a_func\n\n\ndef b_func():\n    return a_func()\n")
    db_path = str(tmp_path / "cyclic.db")
    indexer.index_path(db_path, str(repo))
    eng = ImpactEngine(db_path)
    r = eng.symbol_impact("a_func", max_depth=50, max_nodes=1000)
    assert not r["truncated"]
    assert set(r["impacted_symbols"]) == {"b_func"}


def _make_chain_repo(root, length):
    for i in range(length):
        callee = f"f{i + 1}" if i + 1 < length else None
        body = f"    return f{i + 1}()\n" if callee else "    return 0\n"
        (root / f"f{i}.py").write_text(f"def f{i}():\n{body}")


def test_max_depth_truncates(tmp_path):
    repo = tmp_path / "chain"
    repo.mkdir()
    _make_chain_repo(repo, 10)
    db_path = str(tmp_path / "chain.db")
    indexer.index_path(db_path, str(repo))
    eng = ImpactEngine(db_path)
    r = eng.symbol_impact("f9", max_depth=2, max_nodes=1000)
    assert r["truncated"] is True
    assert r["depth_reached"] <= 2


def test_max_nodes_truncates(tmp_path):
    repo = tmp_path / "chain2"
    repo.mkdir()
    _make_chain_repo(repo, 10)
    db_path = str(tmp_path / "chain2.db")
    indexer.index_path(db_path, str(repo))
    eng = ImpactEngine(db_path)
    r = eng.symbol_impact("f9", max_depth=50, max_nodes=2)
    assert r["truncated"] is True
    assert len(r["impacted_symbols"]) <= 2


def test_multi_symbol_impact_unions_and_excludes_seeds(sample_engine):
    r = sample_engine.multi_symbol_impact(["format_name", "get_connection"])
    assert r["seeds"] == ["format_name", "get_connection"]
    assert "format_name" not in r["impacted_symbols"]
    assert "get_connection" not in r["impacted_symbols"]
    assert "query" in r["impacted_symbols"]
    assert "get_user" in r["impacted_symbols"]


def test_file_impact_transitive(sample_engine):
    r = sample_engine.file_impact("py/utils.py")
    assert r["target_file"] == "py/utils.py"
    deps = set(r["dependent_files"])
    assert {"py/db.py", "py/services.py", "py/api.py", "py/app.py", "py/test_services.py"} <= deps
