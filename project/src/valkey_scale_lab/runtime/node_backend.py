"""The seam between the run lifecycle and the runtime that starts nodes.

Derived from `runtime_start`, the stage that exercises the real primitives:
process start, node inspection, ownership registration and cleanup binding.
`project/docs/runtime_start_slice_map.md` records why that stage was chosen and
which segments it owns.

The lifecycle keeps everything that is not I/O against a runtime: planning which
logical nodes live on which nodehost, generating configuration, writing bundles,
the setup timeline segments and the state write. A backend implements only the
operations below, and replacing it replaces nothing else.

Two of the seven operations are a pair of calls rather than one. The lifecycle
sends every bundle before installing any, and starts every nodehost before
collecting any pid, because those barriers are what the `docker_cp_bundle` /
`nodehost_bundle_install` and `nodehost_start_all` / `pidfile_collect` timeline
segments measure. A backend that fused each pair would erase that evidence.

A nodehost is passed as the mapping the density planner produced. A backend
reads `nodehost_id`, `container_name` (the planned name for the nodehost), and
`ports` when it starts one, then `bundle_artifact_dir`, `remote_bundle_dir` and
`logical_node_count`, which the lifecycle fills in once the bundle is written.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class NodehostAddress:
    """Where a started nodehost is, in the backend's own terms.

    `handle` identifies the started nodehost to the backend that started it.
    `address` is what the nodes it hosts announce to the rest of the cluster.
    """

    handle: str
    address: str


class NodeBackend(Protocol):
    """The operations `runtime_start` needs from whatever runs the nodes."""

    def verify_image(self, image: str) -> dict[str, Any]:
        """Verify the pinned runtime image and return the preflight evidence."""

    def reclaim_run(self, *, capability_id: str, run_id: str) -> None:
        """Remove anything this run owns from a previous attempt."""

    def create_network(self, *, network_name: str, capability_id: str, run_id: str) -> None:
        """Create the run's own network, labelled as owned by this run."""

    def start_nodehost(
        self,
        nodehost: dict[str, Any],
        *,
        network_name: str,
        image: str,
        capability_id: str,
        scenario: str,
        run_id: str,
    ) -> NodehostAddress:
        """Start one nodehost and report where it is."""

    def send_bundle(self, nodehost: dict[str, Any]) -> None:
        """Place the prepared bundle on a nodehost."""

    def install_bundle(self, nodehost: dict[str, Any]) -> None:
        """Run the bundle's install step on a nodehost."""

    def start_node_processes(self, nodehost: dict[str, Any]) -> None:
        """Start every node process the bundle installed on a nodehost."""

    def collect_node_pids(self, nodehost: dict[str, Any]) -> dict[str, int]:
        """Report the pid of each node process started on a nodehost."""

    def wait_nodes_ready(self, nodes: list[dict[str, Any]], *, timeout: float) -> None:
        """Wait until every started node answers, or raise once `timeout` passes."""
