#!/usr/bin/env python3
"""The set of generalised key paths each run's artifacts use, compared.

`diff_stage_artifacts.py` scores views and `diff_delta_paths.py` reduces those
views to differing paths. Both compare runs of the *same shape*. Neither can
compare runs whose shape differs - change the shard count or the replica count
and 22 of 25 views differ, every one of them for a declared reason, so the score
carries no information.

What stays comparable across a shape change is the **vocabulary**: which keys
each artifact uses, with values and identities generalised away. A path present
on one side and absent on the other is a shape change and therefore a finding; a
path present on both with different values is the configuration doing its job.

    python3 scripts/diff_artifact_vocabulary.py RUNTIME_A RUNTIME_B

Output is `KIND<TAB>artifact<TAB>path`, or a single line saying the vocabularies
are identical.

This is the instrument behind MR-2 §5.3 and MR-3 §6.3/§8.2, and it is in the
repository rather than in a session's scratchpad because both of those cite
numbers a later reader has to be able to reproduce. What it measured on the real
fleet, and why the numbers are worth knowing before using it: a 25x1-50 control
and a 10x4-50 candidate differ in **one** path, while **two runs of the same
10x4-50 configuration differ in sixteen**. Every differing path in either
direction is a `cluster_stats_messages_<type>_sent`/`_received` counter - which
Valkey emits only once it has sent a message of that type - or
`sentinel_fault_probe.samples[].errors.control`. So a handful of differing paths
is the expected noise floor of *any* two runs, and the question to ask of a
result is not whether the set is empty but whether anything in it is outside
that family.
"""

from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterator

# Identities that name a particular node, host or run must not make two
# artifacts look like they use different keys, because they appear *as keys* in
# several artifacts. Integers are generalised for the same reason: a map keyed
# by port or ordinal is one shape, not N.
LOGICAL_ID = re.compile(r"shard-\d{4}-(?:primary|replica-\d{2})")
NODEHOST_ID = re.compile(r"nodehost-az-[a-z]+-\d+")
HOST_ID = re.compile(r"vslab-host-[a-z]+-\d+")
NODE_ID = re.compile(r"\b[0-9a-f]{40}\b")
INTEGER = re.compile(r"^\d+$")


def generalise(key: str) -> str:
    key = LOGICAL_ID.sub("<node>", key)
    key = NODEHOST_ID.sub("<nodehost>", key)
    key = HOST_ID.sub("<host>", key)
    key = NODE_ID.sub("<nodeid>", key)
    return "<int>" if INTEGER.match(key) else key


def paths(value: Any, prefix: str = "") -> Iterator[str]:
    """Every leaf's path, with list indices collapsed so length is not shape."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield from paths(item, f"{prefix}.{generalise(str(key))}")
    elif isinstance(value, list):
        for item in value:
            yield from paths(item, prefix + "[]")
    else:
        yield prefix or "<root>"


def read(path: Path) -> Any:
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return json.loads(path.read_text(encoding="utf-8"))


def artifact_names(root: Path) -> set[str]:
    return {path.name for path in root.glob("*.json")} | {path.name for path in root.glob("*.jsonl")}


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        print("usage: diff_artifact_vocabulary.py RUNTIME_A RUNTIME_B", file=sys.stderr)
        return 2
    a, b = (Path(argument).resolve() for argument in sys.argv[1:3])
    findings: list[tuple[str, str, str]] = []
    totals: collections.Counter[str] = collections.Counter()

    for name in sorted(artifact_names(a) | artifact_names(b)):
        left, right = a / name, b / name
        if not right.exists():
            findings.append(("ARTIFACT ONLY IN A", name, ""))
            continue
        if not left.exists():
            findings.append(("ARTIFACT ONLY IN B", name, ""))
            continue
        try:
            # A view that cannot be built is a result, not something to skip.
            set_a, set_b = set(paths(read(left))), set(paths(read(right)))
        except Exception as error:  # noqa: BLE001
            findings.append(("UNREADABLE", name, f"{type(error).__name__}: {error}"))
            continue
        totals["a"] += len(set_a)
        totals["b"] += len(set_b)
        totals["artifacts"] += 1
        findings.extend(("ONLY IN A", name, path) for path in sorted(set_a - set_b))
        findings.extend(("ONLY IN B", name, path) for path in sorted(set_b - set_a))

    print(
        f"{totals['artifacts']} artifacts compared, "
        f"{totals['a']} paths in A, {totals['b']} in B"
    )
    if not findings:
        print("VOCABULARY IDENTICAL - zero paths either way")
    for kind, name, path in findings:
        print(f"{kind}\t{name}\t{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
