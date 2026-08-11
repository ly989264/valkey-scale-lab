"""The seam between the run lifecycle and the runtime that starts nodes.

Derived from `runtime_start`, the stage that exercises the real primitives:
process start, node inspection, ownership registration and cleanup binding.
`project/docs/runtime_start_slice_map.md` records why that stage was chosen and
which segments it owns. `cluster_form` extended it by two operations; see
`project/docs/cluster_form_slice_map.md`. `management_matrix` extended it by
three more - stopping and starting one already-known node, and deploying the
local resource sampler; see `project/docs/management_matrix_slice_map.md`.
`fault_matrix` extended it by seven - the actuator - see
`project/docs/fault_matrix_slice_map.md`. Roadmap item 0.5 then added the two
§15 names that no stage had happened to need, evidence upload and end-of-run
cleanup; see `project/docs/seam_completion_slice_map.md`. Item 1.3 added the one
that item 0.5 found missing and could not supply - the 日志 half of §15's
日志与证据上传, plus the host clock reading that makes cross-host evidence
attributable; see `project/docs/cross_host_evidence_slice_map.md`.

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
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence


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


class LoadLaneHost(Protocol):
    """Where the Load Lane runs, and how what it wrote gets back here.

    §15 keeps the Load Lane itself unchanged across backends and makes 日志与
    证据上传 the adapter's job. Under Docker those two facts collide: memtier in
    cluster mode follows MOVED to the addresses the cluster announces, the macOS
    host cannot route them, so memtier has to run on a nodehost - and then its
    JSON and HDR files are over there and have to come back. Both halves were
    `docker` literals inside `observability/load.py` until this seam member
    existed.

    `seed_host` is how the node this host was chosen for is addressed *from
    here*. It is an attribute rather than a question, for the reason
    `NodehostAddress` carries `address`: the backend knows it when it picks the
    host, and asking again later would ask a caller to hold a value it cannot
    interpret.

    `command` returns the argv to run locally so that `argv` executes on this
    host, with `remote_dir` created first. It returns the argv rather than
    spawning, because the argv is recorded evidence - the load lane reports it,
    and the run's stability observation keeps it.

    `remote_dir` is the lane's own choice of where its output goes, not the
    backend's: it is an ordinary POSIX path and would be the same on any host.
    """

    seed_host: str

    def command(self, argv: Sequence[str], *, remote_dir: str) -> list[str]:
        """The local argv that runs `argv` on this host, with `remote_dir` made."""

    def collect_evidence(self, remote_dir: str, local_dir: Path) -> None:
        """Bring everything this host wrote under `remote_dir` back to `local_dir`."""


class HostEvidence(Protocol):
    """What only the host itself can answer: what its clock says, what it wrote.

    The 日志 half of §15's 日志与证据上传. Item 0.5 gave 证据 a boundary and
    recorded that the 日志 half had no implementation on either backend; this is
    it, in the adapter category §15 already assigns.

    One object with two verbs rather than two operations, for the reason
    `LoadLaneHost` is one - and they are literally the same two verbs applied to
    a different subject: run something over there, fetch something from over
    there. Both answers are about one host reached over the one channel the
    backend has to it, so a caller holding a handle to pass into two operations
    would be holding a value it cannot interpret.
    """

    def clock_exchanges(self, count: int) -> list[dict[str, Any]]:
        """`count` bracketed readings of this host's clock, unreduced.

        Each row carries `controller_before_unix_ms`, `host_unix_ms`,
        `host_monotonic_seconds` and `controller_after_unix_ms`: the raw
        exchange, with the controller's clock read either side of the one
        command that read the host's.

        Deliberately not reduced to an offset here. The estimator - which of the
        readings to keep, and how to turn a bracket into an offset and its
        uncertainty - stays above this seam, so that a Docker offset and a
        native offset are the same kind of number rather than two backends'
        arithmetic. A host's monotonic clock has an arbitrary per-boot origin
        and is reported beside its wall clock rather than compared to anything.
        """

    def collect_node_journal(self, node: Mapping[str, Any], local_path: Path) -> None:
        """Fetch one node's own log file into `local_path`.

        Where a node's log physically lives is the backend's knowledge, the same
        way the location of its prior state is; the node record carries
        `log_file` and the backend knows how to reach it. The local destination
        is the lifecycle's, because it is the run's own artifact tree.

        Raises `CollectionError` if it cannot fetch it. §12.1 puts 必要证据无法
        写入 on the collector's side of the line, so a journal that could not be
        copied is a tool error and never a cluster verdict.
        """


@dataclass(frozen=True)
class RunTeardown:
    """What a backend did when the run released it, and what it found left.

    Carries no status. Whether a teardown passed is a verdict, and verdicts stay
    above this seam; the lifecycle applies one rule to whatever any backend
    reports here.

    `actions` are the report's ordered rows, in the shape `cleanup_report`
    already records - `type`, `id`, `action`, `status`, and whatever else that
    kind of action observed. `resources_remaining` is the residue scan, which is
    the criterion "no managed process or host resource behind" measured rather
    than asserted. `timing` is the backend's own; the lifecycle only fills in
    the second-valued keys a backend did not measure.
    """

    actions: list[dict[str, Any]]
    resources_remaining: list[dict[str, Any]]
    timing: dict[str, Any]
    errors: list[str]


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
        """Remove anything this run owns from a previous attempt.

        This is *pre-run* cleanup, and `release_run` below is teardown. The two
        are not one operation with a flag: this one runs before any state
        exists, so it can only work from the run's ownership labels and has no
        pid to signal and nothing to report; teardown's whole product is the
        record of what it did.
        """

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

        The samples this returns are the one piece of §15's evidence upload that
        was already behind the seam before item 0.5: deploying the sampler and
        collecting what it wrote turned out to be the same member, which is why
        the missing category went unnoticed for three slices.
        """

    def load_lane_host(self, node: dict[str, Any]) -> LoadLaneHost:
        """Choose where the Load Lane runs for `node`, and how to collect it.

        The other half of §15's evidence upload, and the only evidence a run
        pulls off a host that `resource_sampler` does not already cover. See
        `LoadLaneHost` for why it is one object rather than three calls.

        §8 fixes the Load Lane's tool and parameters and §15 keeps the lane
        itself unchanged across backends, so a backend chooses the host and
        nothing else. It does not decide how much load, for how long, or what
        counts as a passing window.
        """

    def host_evidence(self, nodehost: dict[str, Any]) -> HostEvidence:
        """Reach the host this nodehost runs on, for what only it can answer.

        A nodehost rather than a node because a clock belongs to a host, and a
        nodehost is how this protocol names a host the lifecycle has started
        something on - the same argument `pause_nodehost` and `isolate_nodehost`
        were derived on.

        See `HostEvidence`. Added by roadmap item 1.3; the derivation is in
        `project/docs/cross_host_evidence_slice_map.md` §4, including why the
        existing `load_lane_host` could not carry it.
        """

    def release_run(self, state: Mapping[str, Any]) -> RunTeardown:
        """Release everything this run owns, and report what was left behind.

        End-of-run cleanup, as against `reclaim_run`'s pre-run cleanup. The
        backend owns the mechanism - stopping the processes it started,
        confirming they are gone, removing the host resources it created, and
        scanning for residue - and the lifecycle owns what the result means and
        writes the report.

        `state` is the run's own state mapping with `capability_id` resolved,
        which is to say the backend's
        own bookkeeping handed back: the handles in it (`container_id`, `pid`,
        `nodehost_container_name`) are values the backend wrote and only the
        backend can interpret. That is the argument `rejoin_nodehost` was
        derived on, applied to teardown.

        Raising is for a refusal - state that does not describe resources this
        run owns. A resource that would not release is an `action` row with a
        non-PASS status, because the report is what the cleanup criterion is
        measured on and an exception erases it.
        """
