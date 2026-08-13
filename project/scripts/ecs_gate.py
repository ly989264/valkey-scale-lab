#!/usr/bin/env python3
"""Run the exact full flow on the ECS fleet, under a file-descriptor limit it sets.

The Gate's catalog runner has no shell, so `ulimit -n 65536` - which every real
exact-200 on the controller has been taken under, and which
`real_fleet_ladder_slice_map.md` §1 records as part of that environment - cannot
be written into a `real.ecs.*` entry. Without it `runtime_fd_limit` refuses the
run: it requires `max(1024, nodes*8 + nodehosts*32)`, which is 1856 at
exact-200, and Debian's default soft limit is 1024.

The limit is raised here rather than on the controller so that
`./gate milestone m3` states its own requirement instead of depending on one
machine having been configured. The preflight is not weakened by this and is not
meant to be: it asks whether *this process* can hold O(N) persistent RESP
connections plus one ssh master per host, and the answer becomes true because
the process really does raise its limit. What it cannot do is exceed the hard
limit, so it asks for what it can get and says what it got - a controller whose
hard limit is too low fails the preflight, loudly, with the numbers in
`resource_preflight.json`.

Everything else is `real.local.full-flow`'s own argv, plus `--backend
native_multi_ecs`. That flag is the assertion that this is a multi-ECS run:
`execution.backend_for_provider` refuses a backend the configuration's
`runtime.provider` does not implement, in both directions, so this entry cannot
pass on Docker whatever configuration it is handed.

    python3 scripts/ecs_gate.py --nodes 50 \
        --config templates/configs/real_ecs_50.yaml \
        --run-id r --ownership-id r --provenance-id r \
        --artifacts-dir out --result-path out/result.json
"""

from __future__ import annotations

import argparse
import os
import resource
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: What the invocation the real baselines were taken under asked for.
WANTED_NOFILE = 65536


def raise_file_descriptor_limit(wanted: int = WANTED_NOFILE) -> tuple[int, int]:
    """Raise this process's soft NOFILE toward `wanted`, and report the result.

    Returns the limit before and after. Never lowers one that is already higher,
    and never asks for more than the hard limit - a request above it raises
    `ValueError` rather than being clamped by the kernel.
    """

    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft == resource.RLIM_INFINITY or soft >= wanted:
        return soft, soft
    target = wanted if hard == resource.RLIM_INFINITY else min(wanted, hard)
    resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
    return soft, target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--definition", required=True)
    parser.add_argument("--nodes", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--ownership-id", required=True)
    parser.add_argument("--provenance-id", required=True)
    parser.add_argument("--artifacts-dir", required=True)
    parser.add_argument("--result-path", required=True)
    args = parser.parse_args()

    before, after = raise_file_descriptor_limit()
    print(f"RLIMIT_NOFILE soft {before} -> {after}", flush=True)

    argv = [
        sys.executable,
        "-m",
        "valkey_scale_lab.cli",
        "gate",
        "execute",
        "--definition",
        args.definition,
        "--nodes",
        str(args.nodes),
        "--config",
        args.config,
        # The entry's own claim that this is a multi-ECS run, refused by
        # `backend_for_provider` if the configuration says otherwise.
        "--backend",
        "native_multi_ecs",
        "--run-id",
        args.run_id,
        "--ownership-id",
        args.ownership_id,
        "--provenance-id",
        args.provenance_id,
        "--artifacts-dir",
        args.artifacts_dir,
        "--result-path",
        args.result_path,
    ]
    # exec rather than spawn: the raised limit is inherited, the run keeps this
    # process's pid and process group, and the Gate's timeout and its
    # SIGTERM-to-the-group both reach the run itself rather than a wrapper.
    os.execv(argv[0], argv)


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
