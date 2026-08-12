#!/usr/bin/env python3
"""The set of field paths that differ, per view, using the diff tool's own views.

`diff_stage_artifacts.py` prints unified diffs of pretty-printed JSON, which
reads well and compares badly: two candidates' deltas against the same baseline
cannot be compared to each other, only each to prose. This reduces the same views
to a set of generalised paths - list indices collapsed to `[]` - so the two sets
can be diffed directly.

That is what made roadmap item 1.6's headline result statable. The real fleet's
delta against the frozen Docker exact-50 baseline is the simulated fleet's delta
*path for path*, 111 either way with an empty set difference in both directions,
which no reading of two diff transcripts would have established.

    python3 scripts/diff_delta_paths.py BASELINE CANDIDATE > a.tsv
    python3 scripts/diff_delta_paths.py BASELINE OTHER    > b.tsv
    comm -3 <(sort a.tsv) <(sort b.tsv)

Output is `stage<TAB>view<TAB>path`, one line per differing path, so it sorts and
diffs as plain text. A view that raises on either side is reported as an ERROR
row rather than skipped, because a view that cannot be built is not a view that
matched.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def _load_diff_tool() -> Any:
    """Import `diff_stage_artifacts` by path, so the two stay one definition.

    Re-declaring the views here is the failure this file exists to avoid: a path
    set computed from a *copy* of the views would drift from what the diff
    actually compares, and would do so silently.
    """
    spec = importlib.util.spec_from_file_location(
        "diff_stage_artifacts", ROOT / "diff_stage_artifacts.py"
    )
    if spec is None or spec.loader is None:  # pragma: no cover - packaging accident
        raise SystemExit(f"cannot import {ROOT / 'diff_stage_artifacts.py'}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def differing_paths(left: Any, right: Any, prefix: str = "") -> set[str]:
    """Generalised paths at which `left` and `right` differ.

    A list contributes its own path once if the lengths differ, and then compares
    element-wise under a single `[]` segment: what matters for a delta set is
    *which field* moved, not at which index.
    """

    out: set[str] = set()
    if type(left) is not type(right):
        out.add(prefix or "<root>")
        return out
    if isinstance(left, dict):
        for key in set(left) | set(right):
            path = f"{prefix}.{key}" if prefix else key
            if key not in left:
                out.add(path + "  (added)")
            elif key not in right:
                out.add(path + "  (removed)")
            else:
                out |= differing_paths(left[key], right[key], path)
    elif isinstance(left, list):
        if len(left) != len(right):
            out.add(f"{prefix}[]  (length {len(left)} -> {len(right)})")
        for item, other in zip(left, right):
            out |= differing_paths(item, other, f"{prefix}[]")
    elif left != right:
        out.add(prefix or "<root>")
    return out


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        print("usage: diff_delta_paths.py BASELINE_RUNTIME CANDIDATE_RUNTIME", file=sys.stderr)
        return 2
    diff_tool = _load_diff_tool()
    baseline, candidate = (Path(argument).resolve() for argument in sys.argv[1:3])
    for stage, views in diff_tool.STAGE_VIEWS.items():
        for name, build in views.items():
            try:
                left, right = build(baseline), build(candidate)
            except Exception as error:  # noqa: BLE001 - a view that cannot build is a result
                print(f"{stage}\t{name}\tERROR\t{type(error).__name__}")
                continue
            if left == right:
                continue
            for path in sorted(differing_paths(left, right)):
                print(f"{stage}\t{name}\t{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
