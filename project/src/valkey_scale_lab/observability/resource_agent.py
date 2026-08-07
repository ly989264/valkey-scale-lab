"""The nodehost-local resource sampler process.

One of these runs on each nodehost for the lifetime of an observation window,
reading that nodehost's own procfs and cgroupfs. It exists so the sampler runs
where the design places it: a single long-lived local sampler per nodehost,
rather than a session created from outside for every sample.

It builds the same `LocalResourceSampler` and `ResourceSamplerRunner` the rest
of the product uses, on their defaults, so the sampling fields, intervals and
self-overhead accounting are the ones the sampler already implements. The agent
adds only a process around them: read a spec, run until signalled, write the
batch out once.
"""

from __future__ import annotations

import argparse
import json
import signal
import threading
from pathlib import Path
from typing import Any

from valkey_scale_lab.observability.resources import (
    ExpectedGoneProcess,
    LocalResourceSampler,
    ProcessSpec,
    ResourceSamplerRunner,
)


def build_runner(
    spec: dict[str, Any], *, expected_gone_active_file: Path | None = None
) -> ResourceSamplerRunner:
    """A runner reading this nodehost's own procfs, on the sampler defaults."""
    # The orchestrator marks an expected-gone window by creating this file, so
    # the sampler learns about it without a session per sample.
    active = (
        (lambda: expected_gone_active_file.exists())
        if expected_gone_active_file is not None
        else None
    )
    sampler = LocalResourceSampler(
        sampler_id=str(spec["sampler_id"]),
        processes=[
            ProcessSpec(str(row["logical_id"]), int(row["pid"]))
            for row in spec.get("processes", [])
        ],
        expected_gone_processes=[
            ExpectedGoneProcess(str(row["logical_id"]), int(row["pid"]))
            for row in spec.get("expected_gone_processes", [])
        ],
        expected_gone_active=active,
    )
    return ResourceSamplerRunner(sampler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expected-gone-active-file", type=Path, default=None)
    args = parser.parse_args(argv)

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    runner = build_runner(
        spec, expected_gone_active_file=args.expected_gone_active_file
    )

    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())

    runner.start()
    stopped.wait()
    document = runner.stop()

    # Written whole, then moved into place, so a reader never sees a partial
    # batch if it looks while the agent is still finishing.
    args.out.parent.mkdir(parents=True, exist_ok=True)
    partial = args.out.with_suffix(args.out.suffix + ".partial")
    partial.write_text(
        json.dumps(document, sort_keys=True, default=str), encoding="utf-8"
    )
    partial.replace(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
