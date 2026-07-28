"""End-to-end integration test against a real repository (spec section 10.3).

Requires network access to clone https://github.com/psf/requests.git; skips
cleanly if that is unavailable rather than failing the whole suite.
"""

import subprocess

import pytest

import indexer
from impact import ImpactEngine


@pytest.fixture(scope="module")
def requests_repo(tmp_path_factory):
    root = tmp_path_factory.mktemp("requests_repo")
    dest = str(root / "requests")
    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "50", "https://github.com/psf/requests.git", dest],
            capture_output=True, text=True, timeout=120,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        pytest.skip(f"could not clone psf/requests (no network?): {e}")
    if result.returncode != 0:
        pytest.skip(f"could not clone psf/requests (no network?): {result.stderr[-300:]}")
    return dest


@pytest.fixture(scope="module")
def requests_engine(tmp_path_factory, requests_repo):
    db_path = str(tmp_path_factory.mktemp("requests_db") / "graph.db")
    stats = indexer.index_path(db_path, requests_repo)
    print(f"\nindexed psf/requests: {stats}")
    return ImpactEngine(db_path), stats


def test_stats_roughly_match_reference(requests_engine):
    eng, index_stats = requests_engine
    stats = eng.stats()
    print("stats():", stats)
    assert stats["files"] == pytest.approx(37, abs=5)
    assert stats["loc"] == pytest.approx(12000, abs=2000)
    assert stats["symbols"] == pytest.approx(800, abs=150)


def test_to_native_string_impact_is_wide(requests_engine):
    eng, _ = requests_engine
    r = eng.symbol_impact("to_native_string")
    print("to_native_string impacted_files:", len(r["impacted_files"]), "entry_points:", r["entry_points"])
    assert len(r["impacted_files"]) >= 15
    assert len(r["entry_points"]) > 0


def test_default_headers_impact_is_narrower(requests_engine):
    eng, _ = requests_engine
    small = eng.symbol_impact("default_headers")
    r = eng.symbol_impact("to_native_string")
    print("default_headers impacted_files:", len(small["impacted_files"]))
    assert len(small["impacted_files"]) < len(r["impacted_files"])


def test_diff_mode_against_real_commit(requests_repo, requests_engine):
    import diffmap

    eng, _ = requests_engine
    # HEAD~1 alone is frequently just a CI/dependency-bump commit in this
    # repo's history; HEAD~15 reliably spans real source changes.
    con = indexer.open_db(eng.db_path)
    try:
        mapped = diffmap.map_diff(con, git_ref="HEAD~15", repo_dir=requests_repo)
    finally:
        con.close()

    print("diff HEAD~15 seeds:", mapped["seed_symbols"])
    if not mapped["seed_symbols"]:
        pytest.skip("HEAD~15 touched no attributable Python symbols in this snapshot")

    union = eng.multi_symbol_impact(mapped["seed_symbols"])
    # impacted_symbols excludes the seeds themselves (spec section 6); the
    # full retest list is seeds + impacted_symbols, which is trivially a
    # superset of the seeds. Confirm the union is wired correctly instead.
    assert union["seeds"] == sorted(set(mapped["seed_symbols"]))
    assert set(mapped["seed_symbols"]).isdisjoint(set(union["impacted_symbols"]))
    print(f"blast radius covers {len(set(mapped['seed_symbols']) | set(union['impacted_symbols']))} symbols total")
