"""The seam between the run lifecycle and the runtime that starts nodes.

Derived from `runtime_start`, the stage that exercises the real primitives:
process start, node inspection, ownership registration and cleanup binding.
`project/docs/runtime_start_slice_map.md` records why that stage was chosen and
which segments it owns. `cluster_form` extended it by two operations; see
`project/docs/cluster_form_slice_map.md`. `management_matrix` extended it by
three more - stopping and starting one already-known node, and deploying the
local resource sampler; see `project/docs/management_matrix_slice_map.md`.
`fault_matrix` extended it by seven - the actuator - see
`project/docs/fault_matrix_slice_map.md`.

§15 of `docs/scalable_cluster_observability_design.md` fixes how far this seam
reaches. A runtime adapter replaces inventory and endpoint discovery, process
lifecycle, the actuator, sampler deployment and evidence upload. It does not
replace RESP commands or the verification logic, so cluster formation itself -
the MEET fanout, the slot ranges, the replica attach, the convergence waits -
stays in the lifecycle and is not part of this protocol. Nor does it replace
the *observation* of a fault: the actuator injects it, and §9's Sentinel lane,
affected-shard control plane and convergence rule watch what happens, all above
this seam.

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
`logical_node_count`, which the lifecycle fills in once the bundle is written,
and finally `container_id`, `container_ip` and `network_name`, which the
lifecycle records once the nodehost is running. The fault operations read that
last group: isolating a host and putting it back needs to know which scope it
was isolated from and what address to restore, and both are inventory the
lifecycle already holds rather than arguments a caller should be asked for.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Sequence


class ResourceSampler(Protocol):
    """A long-lived local sampler, deployed by a backend, driven by the run.

    §11.1 forbids creating a session per sample, so a backend starts one agent
    on each host and collects it once. The observation layer only needs to
    start it, tell it a planned process exit has begun, and stop it for its
    samples; declaring that here rather than importing the observation layer's
    class keeps this module dependent on nothing.
    """

    def start(self) -> None:
        """Deploy and launch the sampler."""

    def mark_expected_gone_active(self) -> None:
        """Tell the sampler a planned process exit has started."""

    def stop(self) -> dict[str, Any]:
        """Stop the sampler and return the samples it recorded."""


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
        command_kind: str | None = None,
    ) -> str:
        """Run a `valkey-cli` from inside the cluster's own network.

        For the commands the lifecycle cannot issue from outside it: cluster
        creation, which addresses every primary on the cluster network, and any
        client that must follow a `MOVED` to an address the host cannot route.
        `argv` is the `valkey-cli` argument list, so the caller owns `-c`, `-p`
        and `--cluster`; the backend owns only where the client runs.

        `operation_id`, `record_node` and `command_kind` are the command's
        attribution in the recorded evidence. They are the caller's because the
        call sites attributed differently before this seam existed, and quietly
        agreeing them would edit the evidence under cover of a refactor: the
        management workload and the reshard key path classified themselves by
        the Valkey command they were sending, and still must.
        """

    def stop_node(self, node: dict[str, Any], *, command_kind: str) -> list[dict[str, Any]]:
        """Stop the owned Valkey process on one node, and confirm it is gone.

        The backend owns the mechanism and how it observes the process; the
        lifecycle owns when to stop and what stopping means. Confirming is the
        reason this cannot stay above the seam: it reads the host's own process
        table, and there is no `/proc` on the machine this run drives from.

        Not fused with `start_node`. The rolling restart does call them back to
        back, but the remove-and-restore rows stop a node, run `CLUSTER FORGET`
        against every survivor until it is absent and the cluster is clean, and
        only then start it again - a wait bounded at 120s that a single
        `restart_node` could not express.

        Returns one record per command it ran, so the run's evidence keeps
        naming each of them. A record carries `command_kind`, `argv`,
        `started_at_unix_ms`, `ended_at_unix_ms`, `status`, `stdout_tail`,
        `stderr_tail` and `returncode`; the lifecycle adds the ids and the
        attribution. `command_kind` here is the caller's prefix for those
        records, because which management operation asked is not the backend's
        to know.
        """

    def start_node(
        self, node: dict[str, Any], *, fresh_cluster_identity: bool
    ) -> tuple[int, list[dict[str, Any]]]:
        """Start the owned Valkey process on one node and report its new pid.

        With `fresh_cluster_identity`, the node's prior state is discarded first,
        so it rejoins as a new node rather than the one that was forgotten. That
        means its dataset as well as its recorded cluster identity: the only
        reason a caller asks for this is to make the node eligible to be told to
        replicate, and Valkey refuses that for a node that still holds keys. It
        is a flag rather than its own operation because it is only correct while
        the process is stopped, and only the backend knows where that state
        physically lives.

        Returns when the node answers, for the reason `wait_nodes_ready` does:
        a backend is responsible for its own processes being up before it says
        they are. Returns the pid and the command records, as `stop_node` does.
        """

    # The seven operations below are the actuator, which §15 names as one of
    # the five things a runtime adapter replaces. Each returns one record per
    # command it ran, in `stop_node`'s shape plus two fields the fault lane
    # needs and the management lane does not:
    #
    #   `action` - how the backend describes what it did, in one line. The
    #       fault evidence lists these as the owned actions of a scenario, so
    #       the description of a Docker pause belongs to the Docker backend and
    #       not to a stage that must run on both.
    #   `result` - `"OK"`, or why not. §9.1 requires the actuator to record a
    #       result, and requires that failing to act be a tool error rather
    #       than a cluster verdict, so it is reported rather than raised.
    #
    # These records are not command-log rows. The fault lane writes one row per
    # scenario, not one per command, and folds these into that row.

    def kill_node(self, node: dict[str, Any]) -> list[dict[str, Any]]:
        """Terminate the owned process on one node without warning it.

        Not `stop_node` with a flag. `stop_node` asks the server to leave -
        `SHUTDOWN NOSAVE`, then a TERM - and a kill must not, because §9.1's
        planned kill *is* the experiment: warning the process first would
        measure a graceful handoff instead of a failure. The two share only the
        wait for the process to disappear, which is internal here.

        Returns when the process is gone or when the wait runs out; the record
        says which, in `result`, because §9.1 makes the actuator the
        authoritative record of the action and an actuator that could not act
        is a tool error rather than a cluster failure. Raising instead would
        take that away from the caller, which is the one that owns the verdict.
        """

    def pause_node(self, node: dict[str, Any]) -> list[dict[str, Any]]:
        """Suspend the owned process on one node, leaving it in the cluster.

        A suspended node is still a member and still holds its slots; it simply
        stops answering. That is a different fault from stopping it, and the
        stage observes it differently, which is why this is not `stop_node`.
        """

    def resume_node(self, node: dict[str, Any]) -> list[dict[str, Any]]:
        """Resume a process suspended by `pause_node`.

        Separate from `pause_node` for the reason `start_node` is separate from
        `stop_node`, and more strongly: the observation between them may raise,
        and the caller resumes in a `finally`. A scoped pause could not express
        that, and could not express `az_stop`, which suspends N hosts in order
        and resumes them in reverse.
        """

    def pause_nodehost(self, nodehost: dict[str, Any]) -> list[dict[str, Any]]:
        """Suspend a whole host and everything it runs."""

    def resume_nodehost(self, nodehost: dict[str, Any]) -> list[dict[str, Any]]:
        """Resume a host suspended by `pause_nodehost`."""

    def isolate_nodehost(self, nodehost: dict[str, Any]) -> list[dict[str, Any]]:
        """Cut a host off from the run's own network, and confirm it is cut.

        Confirming is part of the operation, not a second call: §9.1 says an
        actuator that cannot actually perform its action is a tool error, so
        only the backend that acted can say whether it did. A backend that
        reported success without checking would let the stage judge a partition
        that never happened.
        """

    def rejoin_nodehost(self, nodehost: dict[str, Any]) -> list[dict[str, Any]]:
        """Put an isolated host back where it was, at the address it announced.

        The address is not an argument. Other nodes reached this host at a
        peer address the backend itself reported when the host started, so
        restoring it is the backend's own bookkeeping; asking the lifecycle to
        pass it back would be asking it to hold a value it cannot interpret.
        """

    def resource_sampler(
        self,
        nodes: list[dict[str, Any]],
        *,
        sampler_id: str,
        processes: Sequence[tuple[str, int]],
        expected_gone: Sequence[tuple[str, int]],
    ) -> ResourceSampler:
        """Deploy the local resource sampler for the host `nodes` share.

        §11.1 puts one long-lived sampler on each host, reading that host's own
        procfs and cgroupfs, and forbids a session per sample; §15 makes
        deploying it the adapter's job. Which logical nodes share a host, and
        which processes are expected to disappear during the window, are
        planning and stay in the lifecycle - so they arrive as plain
        `(logical_id, pid)` pairs and the backend resolves only where to put
        the agent.
        """
