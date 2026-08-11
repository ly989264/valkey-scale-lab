"""What the run records about the machines its evidence was produced on.

Roadmap item 1.3. `project/docs/cross_host_evidence_slice_map.md` carries the
derivation; this docstring records what a reader of the code needs.

M3's evidence criterion asks for evidence that is "complete and attributable",
and neither word is checkable until it names what a validator refuses. The
definition this module implements:

  attributable  the run's own evidence names the host a piece of evidence was
                produced on, in the inventory's vocabulary, and names the offset
                between that host's clock and the controller's at the time.

  complete      every node the run observed has a journal, every nodehost has a
                clock reading at both ends of the run, and every host-produced
                surface is claimed by exactly one of them.

Four surfaces a run produces, and where each is produced (measured against the
frozen exact-50 baseline, by reading the producers):

  command logs        controller, controller-clocked, already attributable by
                      `target_logical_id` - untouched here, and that is the
                      honest answer rather than an omission
  resource documents  host, host-clocked, attributed only by `sampler_id`
  memtier JSON + HDR  host, no attribution at all
  node journals       host, not collected before this module existed

So this module claims the last three for a nodehost, and collects the fourth.
Everything above the seam: the backend supplies raw clock exchanges and fetches
a file, and the estimator, the arithmetic and the document are here, so that a
Docker offset and a native offset are the same kind of number.

Deliberately not here: a pull at every stage boundary. A node's journal is
append-only and cumulative across the restarts the run performs, so one pull at
the last boundary where it is complete and still on the host is the whole of it;
pulling at each boundary would re-transfer the same prefix and leave partial
copies to reconcile, which is the spooling the roadmap forbids in the same
sentence that asks for the pull.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from valkey_scale_lab.runtime.host_clock import (
    CLOCK_EXCHANGE_COUNT,
    reduce_clock_exchanges,
)
from valkey_scale_lab.runtime.node_backend import NodeBackend

HOST_EVIDENCE_ARTIFACT = "host_evidence.json"
NODE_JOURNAL_DIRNAME = "node_journals"

#: Where a nodehost with no fleet says it is. Docker runs have exactly one
#: machine and the planner already calls it this, so the vocabulary is the
#: planner's rather than a second word for the same thing.
LOCAL_HOST_ID = "local"


def read_host_clocks(
    backend: NodeBackend, nodehosts: Sequence[Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    """One bounded clock reading per nodehost, keyed by nodehost id.

    Raises `CollectionError` through the backend if a host will not answer. A
    run whose hosts' clocks are unknown cannot say what its host-stamped
    evidence means, and §12.1 puts that on the collector's side of the line.
    """

    readings: dict[str, dict[str, Any]] = {}
    for nodehost in nodehosts:
        source = backend.host_evidence(dict(nodehost))
        readings[str(nodehost["nodehost_id"])] = reduce_clock_exchanges(
            source.clock_exchanges(CLOCK_EXCHANGE_COUNT)
        )
    return readings


def collect_node_journals(
    backend: NodeBackend,
    nodehosts: Sequence[Mapping[str, Any]],
    nodes: Sequence[Mapping[str, Any]],
    journals_dir: Path,
) -> dict[str, list[dict[str, Any]]]:
    """Every node's own log, off its host and into `journals_dir/<host_id>/`.

    The host is in the path because that is attribution a reader cannot lose:
    on a fleet two hosts can carry nodes with adjacent logical ids, and a flat
    directory would say nothing about which machine either came from.

    One transfer per node rather than one directory pull per host. A directory
    pull would bring the dataset and `nodes.conf` back with the log, which the
    run did not ask for, and per-node is what "process journals" means when the
    process is a node.
    """

    by_nodehost: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        by_nodehost.setdefault(str(node.get("nodehost_id", "")), []).append(dict(node))

    collected: dict[str, list[dict[str, Any]]] = {}
    for nodehost in nodehosts:
        nodehost_id = str(nodehost["nodehost_id"])
        host_id = str(nodehost.get("host_id") or LOCAL_HOST_ID)
        source = backend.host_evidence(dict(nodehost))
        rows: list[dict[str, Any]] = []
        for node in sorted(
            by_nodehost.get(nodehost_id, []), key=lambda item: str(item.get("logical_id", ""))
        ):
            logical_id = str(node["logical_id"])
            local_path = journals_dir / host_id / f"{logical_id}.log"
            source.collect_node_journal(node, local_path)
            raw = local_path.read_bytes()
            rows.append(
                {
                    "logical_id": logical_id,
                    "path": f"runtime/{NODE_JOURNAL_DIRNAME}/{host_id}/{logical_id}.log",
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "bytes": len(raw),
                }
            )
        collected[nodehost_id] = rows
    return collected


def build_host_evidence_document(
    *,
    capability_id: str,
    scenario: str,
    run_id: str,
    nodehosts: Sequence[Mapping[str, Any]],
    start_clocks: Mapping[str, Mapping[str, Any]],
    end_clocks: Mapping[str, Mapping[str, Any]],
    journals: Mapping[str, Sequence[Mapping[str, Any]]],
    load_lane_nodehost_id: str | None,
    timing: Mapping[str, Any],
) -> dict[str, Any]:
    """The run's statement about the machines its evidence came from.

    Rows are per nodehost and each names its host. Under a manifest the two
    coincide by refusal - `_place_nodehosts_on_fleet` puts exactly one nodehost
    on a host - and under Docker every row carries `host_id: "local"`, which is
    true and is exactly the reason a Docker run is not cross-host evidence.

    `load_lane_dirs` and `resource_sampler_ids` are claims recorded where the
    choice was made, not observations: the load lane always seeds from the first
    node (`_load_lane_seed`) and a resource sampler is created for the nodes of
    one nodehost, so the run knows the host at the moment it picks it. Writing
    the host into those two artifacts instead would move frozen diff views to
    record something the run already had.
    """

    rows: list[dict[str, Any]] = []
    for nodehost in sorted(nodehosts, key=lambda item: str(item.get("nodehost_id", ""))):
        nodehost_id = str(nodehost["nodehost_id"])
        row: dict[str, Any] = {
            "nodehost_id": nodehost_id,
            "host_id": str(nodehost.get("host_id") or LOCAL_HOST_ID),
            "clock": {
                "start": dict(start_clocks.get(nodehost_id, {})),
                "end": dict(end_clocks.get(nodehost_id, {})),
            },
            "journals": [dict(item) for item in journals.get(nodehost_id, [])],
            # One sampler per nodehost, named by the nodehost, which is the
            # `static.sampler_id` those documents already carry.
            "resource_sampler_ids": [nodehost_id],
            "load_lane_dirs": (
                ["runtime/load_lane"] if nodehost_id == load_lane_nodehost_id else []
            ),
        }
        if nodehost.get("fleet_id"):
            row["fleet_id"] = str(nodehost["fleet_id"])
        if nodehost.get("fleet_manifest_sha256"):
            row["fleet_manifest_sha256"] = str(nodehost["fleet_manifest_sha256"])
        rows.append(row)

    fleet_ids = sorted({row["fleet_id"] for row in rows if row.get("fleet_id")})
    return {
        "schema_version": "v1",
        "artifact_type": "host_evidence",
        "capability_id": capability_id,
        "scenario_name": scenario,
        "run_id": run_id,
        "status": "PASS",
        # A run says which fleet it ran on. It does not say what that fleet was,
        # and cannot: the manifest is forbidden from carrying such a flag, and
        # the harness records its own nature in a sidecar the product never
        # reads. See the slice map §8.
        "fleet_ids": fleet_ids or [LOCAL_HOST_ID],
        "host_count": len({row["host_id"] for row in rows}),
        "hosts": rows,
        "timing": dict(timing),
    }


class CollectionTimer:
    """Seconds spent in each collection step, for the artifact's own record.

    Its own field rather than a `lifecycle_timeline` step: the run's twelve
    steps are the scenario definition's, and adding a thirteenth would change
    what every consumer of that artifact counts, for bookkeeping this document
    can hold.
    """

    def __init__(self) -> None:
        self._values: dict[str, float] = {}

    def measure(self, name: str, operation: Any) -> Any:
        started = time.monotonic()
        try:
            return operation()
        finally:
            self._values[name] = round(
                self._values.get(name, 0.0) + max(time.monotonic() - started, 0.0), 6
            )

    def as_dict(self) -> dict[str, Any]:
        return dict(sorted(self._values.items()))
