"""The seam between the run lifecycle and the runtime that starts nodes.

Derived from `runtime_start`, the stage that exercises the real primitives:
process start, node inspection, ownership registration and cleanup binding.
`project/docs/runtime_start_slice_map.md` records why that stage was chosen and
which segments it owns. `cluster_form` extended it by two operations; see
`project/docs/cluster_form_slice_map.md`.

§15 of `docs/scalable_cluster_observability_design.md` fixes how far this seam
reaches. A runtime adapter replaces inventory and endpoint discovery, process
lifecycle, the actuator, sampler deployment and evidence upload. It does not
replace RESP commands or the verification logic, so cluster formation itself -
the MEET fanout, the slot ranges, the replica attach, the convergence waits -
stays in the lifecycle and is not part of this protocol.

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

    def client_host(self, node: dict[str, Any]) -> str:
        """The address this process connects to in order to speak RESP to a node.

        This is not the address other nodes use to reach it. Under Docker the
        two differ: the run connects to a published port on loopback, while the
        cluster announces the nodehost's address on its own network, because
        the macOS host cannot route it. A backend that returned one where the
        other was meant would produce a cluster that forms but cannot be
        reached, or one that is reachable and never forms.

        The peer address is not a method here. It is already inventory: it
        arrives as `NodehostAddress.address` when a nodehost starts, and the
        lifecycle records it on every node the nodehost holds. This is the same
        kind of value, so the lifecycle records it the same way, once, rather
        than calling back per command.
        """

    def run_cluster_admin(
        self,
        node: dict[str, Any],
        argv: list[str],
        *,
        timeout: float,
        operation_id: str,
        record_node: dict[str, Any] | None = None,
    ) -> str:
        """Run a `valkey-cli` from inside the cluster's own network.

        For the commands the lifecycle cannot issue from outside it: cluster
        creation, which addresses every primary on the cluster network, and any
        client that must follow a `MOVED` to an address the host cannot route.
        `argv` is the `valkey-cli` argument list, so the caller owns `-c`, `-p`
        and `--cluster`; the backend owns only where the client runs.

        `operation_id` and `record_node` are the command's attribution in the
        recorded evidence. They are the caller's because the two call sites
        attributed differently before this seam existed, and quietly agreeing
        them would edit the evidence under cover of a refactor.
        """
