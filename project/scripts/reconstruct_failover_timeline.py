#!/usr/bin/env python3
"""Derive a past run's failover stage timeline from the rounds it already kept.

    python3 scripts/reconstruct_failover_timeline.py RUNTIME_DIR [RUNTIME_DIR ...]

The 2026-08-13 failover work added `failover_timeline` to a run's own artifacts,
so any run taken since carries it. Runs taken *before* it do not - including both
frozen native baselines at `c58a762a` - and those are exactly the runs a new
measurement has to be compared against.

Nothing new is collected. `_derive_failover_timeline` reads the affected-shard
rounds and Sentinel samples the lane has always retained, which is the property
that made the original retroactive read over 74 runs possible at all. This is
that read, in the repository rather than in a session's scratchpad, because
MR-3 §6.1's r=1 column and §6.2's whole argument are built on it and a later
reader has to be able to reproduce them.

Read the aggregate last. Measured on the real fleet: RTO moves under 2.5 %
between one replica and four while `pfail_to_promotion_ms` moves by a factor of
3.5, and two runs of one configuration gave 6.02 s and 10.55 s. The aggregate
hides the term that moves.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from valkey_scale_lab.runtime.docker_runtime import _derive_failover_timeline


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        print("usage: reconstruct_failover_timeline.py RUNTIME_DIR [RUNTIME_DIR ...]", file=sys.stderr)
        return 2

    for argument in sys.argv[1:]:
        root = Path(argument)
        document = root / "scalable_primary_failover_observation.json"
        if not document.exists():
            print(f"{argument}\tNO OBSERVATION\t{document.name} absent")
            continue
        observation = json.loads(document.read_text(encoding="utf-8"))
        convergence = observation.get("affected_shard_convergence") or {}
        try:
            timeline = _derive_failover_timeline(
                actuator_record=observation["actuator"],
                convergence_result=convergence,
                sentinel_result=observation.get("sentinel_fault_probe") or {},
                observer_interval_ms=float(convergence.get("round_interval_ms") or 500),
            )
        except Exception as error:  # noqa: BLE001 - a run that cannot be derived is a result
            print(f"{argument}\tERROR\t{type(error).__name__}: {error}")
            continue
        values = {row["field"]: row["value_ms"] for row in timeline["intervals"]}
        promoted = (convergence.get("converged_relationship") or {}).get("primary")
        print(
            "%s\tdetect %.2fs\tpfail->promotion %.2fs\tpromotion->slots %.3fs\tRTO %.2fs\tpromoted %s"
            % (
                argument,
                values.get("process_gone_to_pfail_ms", 0) / 1000,
                values.get("pfail_to_promotion_ms", 0) / 1000,
                values.get("promotion_to_slots_covered_ms", 0) / 1000,
                values.get("failure_to_client_recovered_ms", 0) / 1000,
                promoted,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
