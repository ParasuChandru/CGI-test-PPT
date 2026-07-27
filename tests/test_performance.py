"""Synthetic scale test (spec section 10.4): ~2000 files / ~400K LOC with
cross-file call chains. Verifies cold/incremental indexing behavior and
query latency, and prints timings (demo material per the spec).
"""

import os
import time

import pytest

import indexer
from impact import ImpactEngine

NUM_FILES = 2000
PAD_LINES = 197  # -> ~200 LOC/file, ~400K LOC total


def _write_chain_repo(root, num_files=NUM_FILES, pad_lines=PAD_LINES, pad_value=0):
    for i in range(num_files):
        lines = []
        if i + 1 < num_files:
            lines.append(f"from mod_{i + 1} import step_{i + 1}")
        lines.append(f"def step_{i}():")
        if i + 1 < num_files:
            lines.append(f"    return step_{i + 1}()")
        else:
            lines.append("    return 0")
        for k in range(pad_lines):
            lines.append(f"    _pad_{k} = {k + pad_value}")
        with open(os.path.join(root, f"mod_{i}.py"), "w") as fh:
            fh.write("\n".join(lines) + "\n")


@pytest.fixture(scope="module")
def chain_repo(tmp_path_factory):
    root = tmp_path_factory.mktemp("perf_repo")
    _write_chain_repo(str(root))
    return str(root)


def test_cold_index_completes_and_reports_elapsed(chain_repo, tmp_path_factory):
    db_path = str(tmp_path_factory.mktemp("perf_db") / "graph.db")
    stats = indexer.index_path(db_path, chain_repo)
    print(f"\ncold index: {stats['files_seen']} files, "
          f"{stats['files_changed']} changed, {stats['elapsed']:.3f}s")

    eng = ImpactEngine(db_path)
    full_stats = eng.stats()
    print(f"graph: {full_stats}")

    assert stats["files_seen"] == NUM_FILES
    assert stats["files_changed"] == NUM_FILES
    assert full_stats["loc"] >= 350_000

    # second pass: nothing changed -> should skip everything, and be
    # materially faster than the cold pass
    t0 = time.time()
    stats2 = indexer.index_path(db_path, chain_repo)
    incremental_elapsed = time.time() - t0
    print(f"no-op reindex: {stats2['files_changed']} changed, {incremental_elapsed:.3f}s")
    assert stats2["files_changed"] == 0
    assert incremental_elapsed < stats["elapsed"]

    # single-file change -> exactly one file reindexed
    with open(os.path.join(chain_repo, "mod_0.py"), "a") as fh:
        fh.write("\n# touched\n")
    stats3 = indexer.index_path(db_path, chain_repo)
    print(f"single-file reindex: {stats3['files_changed']} changed, {stats3['elapsed']:.3f}s")
    assert stats3["files_changed"] == 1

    # query latency
    t0 = time.time()
    r = eng.symbol_impact(f"step_{NUM_FILES - 1}")
    query_elapsed = time.time() - t0
    print(f"symbol_impact query: {query_elapsed:.3f}s, "
          f"{len(r['impacted_symbols'])} impacted symbols")
    assert query_elapsed < 1.0
