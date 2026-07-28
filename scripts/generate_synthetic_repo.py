#!/usr/bin/env python3
"""Generate a large synthetic Python codebase for testing Impact Studio at
scale (default target: ~1,000,000 LOC across a few thousand files).

Not committed as part of the app itself -- this is a standalone dev tool.
Run it locally, then point Impact Studio's "local path" field at the
output directory. Nothing here needs network access or the app running.

Unlike a single long call chain, this generates a layered fan-in/fan-out
shape so the demo has real contrast once indexed:

  core.py         K shared "leaf" utility functions
  worker_*.py     N files, each with a handler that calls a couple of the
                  core utilities (so those utilities end up with a wide
                  blast radius -- the "expensive change" story)
  test_worker_*.py   one test function per worker, calling its handler
                  directly (so workers show up as entry points too)

Usage:
    python3 scripts/generate_synthetic_repo.py --out ./big_repo
    python3 scripts/generate_synthetic_repo.py --out ./big_repo --workers 6000 --pad-lines 150
"""

import argparse
import os


def _padded_body(pad_lines, start=0):
    return "\n".join(f"    _pad_{k} = {k + start}" for k in range(pad_lines))


def generate(out_dir, num_workers, num_core_utils, pad_lines):
    os.makedirs(out_dir, exist_ok=True)

    # core.py: K shared utility functions, each called by many workers.
    core_lines = []
    for u in range(num_core_utils):
        core_lines.append(f"def util_{u}(x):")
        core_lines.append(f"    result = x + {u}")
        core_lines.append(_padded_body(pad_lines, start=u))
        core_lines.append("    return result")
        core_lines.append("")
    with open(os.path.join(out_dir, "core.py"), "w") as fh:
        fh.write("\n".join(core_lines) + "\n")

    # worker_i.py: a handler that calls one utility spread uniformly across
    # the core set (u1), plus util_0 for most workers (u_hot) -- so util_0
    # ends up with a much wider blast radius than the rest, giving a real
    # "expensive vs. cheap change" contrast once indexed, instead of every
    # utility looking equally hot.
    for i in range(num_workers):
        u1 = i % num_core_utils
        call_hot = u1 != 0 and (i % 5 != 0)
        if call_hot:
            lines = [
                f"from core import util_{u1}, util_0",
                "",
                f"def handler_{i}(x):",
                f"    a = util_{u1}(x)",
                f"    b = util_0(a)",
                _padded_body(pad_lines, start=i),
                "    return b",
                "",
            ]
        else:
            lines = [
                f"from core import util_{u1}",
                "",
                f"def handler_{i}(x):",
                f"    a = util_{u1}(x)",
                _padded_body(pad_lines, start=i),
                "    return a",
                "",
            ]
        with open(os.path.join(out_dir, f"worker_{i}.py"), "w") as fh:
            fh.write("\n".join(lines) + "\n")

        test_lines = [
            f"from worker_{i} import handler_{i}",
            "",
            f"def test_handler_{i}():",
            f"    assert handler_{i}(1) is not None",
        ]
        with open(os.path.join(out_dir, f"test_worker_{i}.py"), "w") as fh:
            fh.write("\n".join(test_lines) + "\n")

    total_files = 1 + num_workers * 2
    approx_loc = (
        num_core_utils * (pad_lines + 4)
        + num_workers * (pad_lines + 7)
        + num_workers * 4
    )
    print(f"Generated {total_files} files, ~{approx_loc:,} LOC, in {out_dir}")
    print(f"  core.py: {num_core_utils} shared utilities")
    print(f"  {num_workers} workers, each calling 1-2 shared utilities")
    print(f"  {num_workers} matching test files")
    print()
    print("Point Impact Studio's 'local path' field at:")
    print(f"  {os.path.abspath(out_dir)}")
    print()
    print("Try searching e.g. 'util_0' for a wide blast radius, and a")
    print("higher-numbered util_N (less-used) for contrast.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="./synthetic_repo", help="output directory")
    parser.add_argument("--workers", type=int, default=5000, help="number of worker files (x2 with tests)")
    parser.add_argument("--core-utils", type=int, default=20, help="number of shared utility functions")
    parser.add_argument("--pad-lines", type=int, default=190, help="filler lines per function, to control LOC/file")
    args = parser.parse_args()
    generate(args.out, args.workers, args.core_utils, args.pad_lines)
