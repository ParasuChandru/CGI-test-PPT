#!/usr/bin/env python3
"""Generate a large synthetic Python codebase for testing Impact Studio at
scale (default target: ~1,000,000 LOC across a few thousand files).

Not committed as part of the app itself -- this is a standalone dev tool.
Run it locally, then point Impact Studio's "local path" field at the
output directory. Nothing here needs network access or the app running.

Four real layers, each file depending on named files in the layer below
it -- not just a flat star where every file only touches core.py:

  core.py           K shared "leaf" utility functions
  mid_*.py          M files, each imports core.py and calls 1-2 utilities
  handler_*.py      M files, each imports its OWN mid_i AND mid_0 (a
                    shared "hot" mid used by most handlers, for blast-
                    radius contrast) -- so handler_i.py has real,
                    file-visible dependencies on two other generated files
  test_handler_*.py one test per handler, importing and calling it

So a single change at the bottom (a core util, or the hot mid) ripples
up through mid -> handler -> test, a 4-hop chain across many files, the
same shape as a real layered app (utils -> services -> api -> app).

Usage:
    python3 scripts/generate_synthetic_repo.py --out ./big_repo
    python3 scripts/generate_synthetic_repo.py --out ./big_repo --handlers 3000 --pad-lines 150
"""

import argparse
import os


def _padded_body(pad_lines, start=0):
    return "\n".join(f"    _pad_{k} = {k + start}" for k in range(pad_lines))


def generate(out_dir, num_handlers, num_core_utils, pad_lines):
    os.makedirs(out_dir, exist_ok=True)

    # Layer 0: core.py -- K shared utility functions.
    core_lines = []
    for u in range(num_core_utils):
        core_lines.append(f"def util_{u}(x):")
        core_lines.append(f"    result = x + {u}")
        core_lines.append(_padded_body(pad_lines, start=u))
        core_lines.append("    return result")
        core_lines.append("")
    with open(os.path.join(out_dir, "core.py"), "w") as fh:
        fh.write("\n".join(core_lines) + "\n")

    # Layer 1: mid_i.py -- one per handler, each depends on core.py.
    for i in range(num_handlers):
        u1 = i % num_core_utils
        lines = [
            f"from core import util_{u1}",
            "",
            f"def mid_{i}(x):",
            f"    a = util_{u1}(x)",
            _padded_body(pad_lines, start=i),
            "    return a",
            "",
        ]
        with open(os.path.join(out_dir, f"mid_{i}.py"), "w") as fh:
            fh.write("\n".join(lines) + "\n")

    # Layer 2: handler_i.py -- depends on its own mid_i, plus mid_0 for
    # most handlers (a shared "hot" dependency, so mid_0/util_0 end up with
    # a much wider blast radius than the rest -- real expensive-vs-cheap
    # contrast, not every symbol looking equally hot).
    for i in range(num_handlers):
        call_hot = i != 0 and (i % 5 != 0)
        if call_hot:
            lines = [
                f"from mid_{i} import mid_{i}",
                "from mid_0 import mid_0",
                "",
                f"def handler_{i}(x):",
                f"    a = mid_{i}(x)",
                f"    b = mid_0(a)",
                _padded_body(pad_lines, start=i),
                "    return b",
                "",
            ]
        else:
            lines = [
                f"from mid_{i} import mid_{i}",
                "",
                f"def handler_{i}(x):",
                f"    a = mid_{i}(x)",
                _padded_body(pad_lines, start=i),
                "    return a",
                "",
            ]
        with open(os.path.join(out_dir, f"handler_{i}.py"), "w") as fh:
            fh.write("\n".join(lines) + "\n")

        # Layer 3: one test per handler.
        test_lines = [
            f"from handler_{i} import handler_{i}",
            "",
            f"def test_handler_{i}():",
            f"    assert handler_{i}(1) is not None",
        ]
        with open(os.path.join(out_dir, f"test_handler_{i}.py"), "w") as fh:
            fh.write("\n".join(test_lines) + "\n")

    total_files = 1 + num_handlers * 3
    approx_loc = (
        num_core_utils * (pad_lines + 4)
        + num_handlers * (pad_lines + 5)   # mid_i.py
        + num_handlers * (pad_lines + 6)   # handler_i.py
        + num_handlers * 4                 # test_handler_i.py
    )
    print(f"Generated {total_files} files, ~{approx_loc:,} LOC, in {out_dir}")
    print(f"  core.py: {num_core_utils} shared utilities")
    print(f"  {num_handlers} mid_*.py, each depending on core.py")
    print(f"  {num_handlers} handler_*.py, each depending on its own mid_i.py"
          f" and (mostly) mid_0.py")
    print(f"  {num_handlers} matching test files")
    print()
    print("Point Impact Studio's 'local path' field at:")
    print(f"  {os.path.abspath(out_dir)}")
    print()
    print("Try searching 'util_0' or 'mid_0' for a wide, multi-hop blast")
    print("radius (test -> handler -> mid -> core), and a higher-numbered")
    print("util_N/mid_N for contrast -- same shape as a real layered app.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="./synthetic_repo", help="output directory")
    parser.add_argument("--handlers", type=int, default=3300, help="number of handler files (x3 with mid + test layers)")
    parser.add_argument("--core-utils", type=int, default=20, help="number of shared utility functions")
    parser.add_argument("--pad-lines", type=int, default=145, help="filler lines per function, to control LOC/file")
    args = parser.parse_args()
    generate(args.out, args.handlers, args.core_utils, args.pad_lines)
