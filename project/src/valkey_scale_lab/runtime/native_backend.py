"""The `NodeBackend` for Valkey processes on hosts the run does not own.

The second implementation of the seam, and the first thing to test whether the
seam is a protocol or a description of the Docker backend. The derivation is in
`project/docs/native_backend_slice_map.md`; this docstring records only what a
reader of the code needs in order not to misread it.

Three things are worth knowing before reading a method:

**A nodehost is a host, exactly one per host.** Under Docker a nodehost is
created by `start_nodehost` and is its own container, so a nodehost and a fault
domain coincide by construction. Here the host exists before the run, so
`start_nodehost` means *claim and prepare*, and the placement in
`nodehost_density.py` refuses to put two nodehosts on one host - otherwise
`pause_nodehost` would take out a domain the plan believed was independent. See
slice map §3.

**The run's ownership mark on a host is a path, except for firewall rules.**
Everything a run puts on a host lives under `/tmp/valkey-scale-lab/<run_id>` (the
data dirs the lifecycle already computes) or is named after the run. That is what
`reclaim_run` and `release_run` work from, in place of Docker's labels. A
*process* is this run's when its working directory is inside that tree, which is
the only mark that survives - Valkey rewrites its process title, so the path is
not in a live node's argv. A *firewall rule* cannot carry the mark in its chain
name, because iptables caps that at 28 characters and a run id is 42, so the
jumps carry it in a comment instead. Roadmap item 1.4 measured all three; see
`project/docs/distributed_cleanup_slice_map.md`.

**The pinned binaries arrive as a bundle, and the run bundle assumes them on
`PATH`.** `start_all.sh` invokes bare `valkey-server`, so the install happens in
`start_nodehost` - before any run bundle is sent - and `PATH` is supplied to each
command rather than written into the host's profile, because a run must not leave
a host's environment changed behind it.

What this module does *not* do, so that a later reader does not mistake it for an
omission: no fault path checks ownership, which is an accepted absence recorded
in CLAUDE.md and not quietly changed here - the run mark item 1.4 put on the
actuator's rules records whose a rule is, and does not make `isolate_nodehost`
refuse a host that is not this run's. And nothing removes the Load Lane's remote
directory, whose location the seam gives to the lane rather than to a backend;
see the slice map §8.4.
"""

from __future__ import annotations

import json
import shlex
import socket
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from valkey_scale_lab.observability.contracts import CollectionError
from valkey_scale_lab.runtime.backends import BackendSpec, register_backend
from valkey_scale_lab.runtime.command_recorder import current_command_recorder
from valkey_scale_lab.runtime.host_clock import HOST_CLOCK_ARGV, parse_host_clock
from valkey_scale_lab.runtime.host_inventory import (
    HostInventory,
    control_endpoint_of,
    load_host_inventory,
)
from valkey_scale_lab.runtime.host_transport import (
    CommandResult,
    HostTransport,
    MultiplexedSshTransport,
    TransportError,
)
from valkey_scale_lab.runtime.native_bundle import (
    NativeBundleError,
    verify_native_bundle,
)
from valkey_scale_lab.runtime.node_backend import NodehostAddress, RunTeardown
from valkey_scale_lab.valkey.resp import encode_command, read_response

#: Where a pinned bundle is unpacked. Addressed by the archive digest, not by the
#: run: two runs of the same build share one install, and a build that differs by
#: a byte lands somewhere else. Run-agnostic on purpose - a fleet is reused
#: during development and re-shipping 14 MB per host per run proves nothing.
NATIVE_INSTALL_ROOT = "/opt/valkey-scale-lab/bundles"

#: The run's own tree. `_process_data_dir` puts every node's data dir under
#: `/tmp/valkey-scale-lab/<run_id>/<logical_id>`, so this prefix is the run's
#: ownership mark on a host and both cleanup operations work from it.
RUN_STATE_ROOT = "/tmp/valkey-scale-lab"

#: The run bundle lands here, matching `PROCESS_BUNDLE_ROOT` in the lifecycle.
BUNDLE_DROP_ROOT = "/tmp"

#: Where the resource agent's copy of the package goes, *under the run root*.
#: It sat at `/tmp/vslab-resource-agent` until roadmap item 1.4, matching the
#: Docker backend's `RESOURCE_AGENT_DIR` - which is correct under Docker, where
#: removing the container removes it, and leaves a package copy and a directory
#: per sampler on every host of a native run forever. The agent is invoked
#: identically either way; only the root moved. Under the run root it needs no
#: removal step of its own, and a sampler still running after an abort is found
#: by the cwd scan below like any other process of the run.
RESOURCE_AGENT_SUBDIR = ".resource-agent"

_DEFAULT_TIMEOUT = 60.0


class NativeRuntimeError(RuntimeError):
    """A native runtime operation could not be performed."""


def _unix_ms() -> int:
    return int(time.time() * 1000)


def _safe_token(value: Any, field: str) -> str:
    token = str(value)
    if not token or any(character in token for character in " \t\n'\"$`\\;|&<>()") or token in {".", ".."}:
        raise NativeRuntimeError(f"unsafe native runtime {field}: {token!r}")
    return token


def _safe_pid(value: Any) -> str:
    token = str(value).strip()
    if isinstance(value, bool) or not token.isdigit() or int(token) <= 0:
        raise NativeRuntimeError(f"unsafe native runtime pid: {value!r}")
    return token


def run_state_root(run_id: Any) -> str:
    """This run's own tree on a host, which is its ownership mark."""
    return f"{RUN_STATE_ROOT}/{_safe_token(run_id, 'run_id')}"


def fault_rule_tag(run_id: Any) -> str:
    """The mark a firewall rule carries, since a chain name cannot carry one.

    Measured on a host during roadmap item 1.4: `iptables` accepts a chain name
    of 28 characters and refuses 29, and a run id is 42 - so the chain keeps a
    readable name derived from the nodehost and is a handle, the way
    `container_name` is, while the two jump rules that activate it carry this.
    A comment holds 256 characters, and `iptables -S` prints it, which is what
    makes a rule attributable to a run that did not create it.
    """
    return f"vslab-run={_safe_token(run_id, 'run_id')}"


def _owned_process_walk(run_root: str, *, body: str) -> str:
    """Shell that runs `body` for every process running out of `run_root`.

    The ownership evidence is the process's *working directory*, not its command
    line. Measured during roadmap item 1.4: Valkey rewrites its process title, so
    a live node's argv is `valkey-server 0.0.0.0:31000 [cluster]` and the run
    root is nowhere in it - the scan this replaces matched nothing at all while
    two nodes of the run were running. The generated config sets `dir
    <data_dir>`, Valkey chdirs there, and `/proc/<pid>/cwd` still says so after a
    restart has given the node a new pid.

    The comparison appends a separator to both sides. Without it, a run whose id
    is a prefix of another's claims that other run's processes - measured, with
    `run-alpha` reporting `run-alpha-2`'s node as its own residue.

    `exe` is read and reported, never used to filter. Filtering on it would drop
    exactly the process a reader most needs to hear about: something unexpected,
    running out of this run's own tree. `$pid`, `$cwd` and `$exe` are in scope
    for `body`.
    """
    return (
        f"root={shlex.quote(run_root)}; "
        "for entry in /proc/[0-9]*; do "
        '  pid=${entry#/proc/}; '
        '  cwd=$(readlink "$entry/cwd" 2>/dev/null) || continue; '
        '  case "$cwd/" in "$root"/*) ;; *) continue;; esac; '
        '  exe=$(readlink "$entry/exe" 2>/dev/null); '
        f"  {body} "
        "done; "
    )


def _signal_owned_processes(run_root: str, signal: str, *, resume_first: bool = False) -> str:
    """Signal every process of the run and report each one that was signalled.

    `resume_first` sends `CONT` before the signal. A process the fault actuator
    suspended cannot act on `TERM` until it is running again, so a run aborted
    with a nodehost paused would sit out the whole termination wait and be killed
    at the end of it. Teardown's business, not the actuator's: the actuator is
    entitled to leave a domain suspended, and cleanup is what has to cope.

    Enumeration and signal are one script so that the window between deciding a
    pid is ours and signalling it is as small as it can be made. A pid read on
    the controller and signalled a round trip later is a pid that may have been
    reused, which is the flaw in terminating by `state.json` and in terminating
    by a pidfile alike.

    Returns a fragment, not a whole script: `reclaim_run` continues after it in
    the same session, and a caller that wants it alone terminates it.
    """
    body = (
        ('kill -CONT "$pid" 2>/dev/null || true; ' if resume_first else "")
        + f'if kill -{signal} "$pid" 2>/dev/null; then '
        '  printf "%s\\t%s\\t%s\\n" "$pid" "$cwd" "$exe"; '
        "fi;"
    )
    return _owned_process_walk(run_root, body=body)


def _list_owned_processes(run_root: str) -> str:
    """Report every process of the run, signalling nothing."""
    body = 'printf "%s\\t%s\\t%s\\n" "$pid" "$cwd" "$exe";'
    return _owned_process_walk(run_root, body=body) + "exit 0"


def _scan_run_residue(run_root: str) -> str:
    """Both filesystem-level residues of a run in one question to the host.

    The tree, and every process still running out of it. One session rather than
    two because they are one question - "is anything of this run still here" -
    and because a scan that answered them a round trip apart could report a tree
    removed between the two answers.
    """
    return (
        f'[ -e {shlex.quote(run_root)} ] && printf "state\\n"; ' + _list_owned_processes(run_root)
    )


def _await_owned_processes_gone(run_root: str, *, attempts: int) -> str:
    """Wait on the host for the run's processes to exit, then report the rest.

    The waiting happens on the host rather than as a controller-side poll: the
    same answer costs one session instead of `attempts` of them, and this runs
    once per host at teardown when nothing else needs the channel.
    """
    listing = _list_owned_processes(run_root)
    return (
        f"attempt=0; while [ $attempt -lt {int(attempts)} ]; do "
        f'  left=$(sh -c {shlex.quote(listing)} | wc -l); '
        '  [ "$left" -eq 0 ] && break; '
        "  sleep 0.5; attempt=$((attempt + 1)); "
        "done; "
        f"sh -c {shlex.quote(listing)}; "
        "exit 0"
    )


def _parse_owned_processes(stdout: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 2 or not parts[0].strip().isdigit():
            continue
        rows.append(
            {
                "pid": int(parts[0].strip()),
                "cwd": parts[1].strip(),
                "exe": parts[2].strip() if len(parts) > 2 else "",
            }
        )
    return rows


def _remove_fault_rules(run_id: Any) -> str:
    """Remove every firewall rule this run marked, and the chains they target.

    Nothing removed these before roadmap item 1.4: only `rejoin_nodehost` did,
    so a run that aborted while a host was isolated left a DROP chain and its two
    jumps installed - measured, and inherited by whatever ran there next.

    Found by the run's own mark rather than by the chain name, because the name
    cannot carry one. The chains are flushed and deleted after their jumps are
    gone, since `iptables -X` refuses a chain that is still referenced.
    """
    tag = shlex.quote(fault_rule_tag(run_id))
    return (
        f"tag={tag}; chains=''; "
        # `-A` only: the policy lines `iptables -S` also prints carry no jump.
        'for spec in $(iptables -S 2>/dev/null | awk -v t="$tag" '
        "'index($0, t) > 0 && $1 == \"-A\" {print $2 \"|\" $NF}'); do "
        '  parent=${spec%%|*}; chain=${spec##*|}; '
        '  iptables -D "$parent" -m comment --comment "$tag" -j "$chain" 2>/dev/null || true; '
        '  printf "jump\\t%s\\t%s\\n" "$parent" "$chain"; '
        '  case " $chains " in *" $chain "*) ;; *) chains="$chains $chain";; esac; '
        "done; "
        "for chain in $chains; do "
        '  iptables -F "$chain" 2>/dev/null || true; '
        '  if iptables -X "$chain" 2>/dev/null; then printf "chain\\t%s\\n" "$chain"; '
        '  else printf "held\\t%s\\n" "$chain"; fi; '
        "done; "
        "exit 0"
    )


def _scan_fault_rules(run_id: Any, chains: Sequence[str]) -> str:
    """What firewall state of this run's is still installed.

    Two questions, because one does not cover the other: any rule still carrying
    the run's mark, and any chain the run is known to have created that still
    exists. A chain outlives its mark once its jumps are gone, so a chain whose
    `-X` was refused would be invisible to the first question alone.
    """
    tag = shlex.quote(fault_rule_tag(run_id))
    # `''` rather than an empty expansion: `for chain in ; do` is a syntax error.
    named = " ".join(shlex.quote(str(chain)) for chain in chains) or "''"
    return (
        f"tag={tag}; "
        'iptables -S 2>/dev/null | awk -v t="$tag" '
        "'index($0, t) > 0 {print \"rule\\t\" $0}'; "
        f"for chain in {named}; do "
        '  [ -n "$chain" ] || continue; '
        '  if iptables -S "$chain" >/dev/null 2>&1; then printf "chain\\t%s\\n" "$chain"; fi; '
        "done; "
        "exit 0"
    )


class NativeMultiEcsBackend:
    """Runs the seam's node operations as processes on manifest-described hosts.

    Every argument is optional because two different callers construct this. A
    run builds it from the run's configuration and needs all three; `cli gate
    cleanup` and the Gate's teardown build it with none and hand it a state
    mapping, which carries each nodehost's control endpoint precisely so that
    releasing a run never has to find a manifest again.
    """

    backend_id = "native_multi_ecs"

    def __init__(
        self,
        *,
        transport: HostTransport | None = None,
        bundle_dir: str | Path | None = None,
        inventory_path: str | Path | None = None,
    ) -> None:
        self._transport = transport
        self._bundle_dir = Path(bundle_dir) if bundle_dir is not None else None
        self._inventory_path = Path(inventory_path) if inventory_path is not None else None
        self._inventory: HostInventory | None = None
        self._bundle_evidence: dict[str, Any] | None = None
        # Filled by `start_nodehost`. `client_host` is asked about a node before
        # the lifecycle has copied any nodehost field onto it, so the only thing
        # it can resolve from is `nodehost_id`.
        self._placed: dict[str, dict[str, Any]] = {}
        self._network_scope: str | None = None

    # ---- what the backend was given ------------------------------------

    @property
    def transport(self) -> HostTransport:
        if self._transport is None:
            self._transport = MultiplexedSshTransport()
        return self._transport

    def inventory(self) -> HostInventory:
        if self._inventory is None:
            if self._inventory_path is None:
                raise NativeRuntimeError(
                    "this native backend was built without a fleet manifest, so it can only "
                    "release a run whose state names its hosts"
                )
            self._inventory = load_host_inventory(self._inventory_path)
        return self._inventory

    def fleet_placement_records(self) -> list[dict[str, Any]]:
        """What the planner needs in order to place nodehosts on this fleet."""
        return self.inventory().placement_records()

    # ---- the transport, wrapped so every call produces a record ---------

    def _run(
        self,
        control_endpoint: Mapping[str, Any],
        argv: Sequence[str],
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        install_path: str | None = None,
    ) -> CommandResult:
        """One command on one host, with the pinned bundle on `PATH` if asked.

        `PATH` is prefixed per command rather than written into the host's
        profile: the run bundle's `start_all.sh` invokes bare `valkey-server`,
        and a run that edited a host's environment would leave a host resource
        behind that `release_run` has no row for.
        """
        if install_path:
            joined = shlex.join([str(item) for item in argv])
            argv = ["sh", "-c", f"PATH={shlex.quote(install_path)}:$PATH; {joined}"]
        return self.transport.run(control_endpoint, argv, timeout=timeout)

    def _record(
        self,
        command_kind: str,
        result: CommandResult,
        *,
        check: bool = False,
    ) -> dict[str, Any]:
        """`_exec_record`'s shape, which the run's command log already stores.

        Same seven fields as the Docker backend's, because the lifecycle adds the
        ids and the attribution to whatever a backend returns and the acceptance
        diff compares the result.
        """
        if check and result.returncode != 0:
            raise NativeRuntimeError(
                f"native command failed {command_kind}: {result.stderr.strip()[:500]}"
            )
        return {
            "command_kind": command_kind,
            "argv": list(result.argv),
            "started_at_unix_ms": result.started_at_unix_ms,
            "ended_at_unix_ms": result.ended_at_unix_ms,
            "status": "PASS" if result.returncode == 0 else "FAIL",
            "stdout_tail": result.stdout[-500:],
            "stderr_tail": result.stderr[-500:],
            "returncode": result.returncode,
        }

    def _fault_record(
        self,
        command_kind: str,
        result: CommandResult,
        *,
        action: str,
        result_text: str | None = None,
    ) -> dict[str, Any]:
        """`_record` plus the two fields §9.1 requires of an actuator.

        `action` describes what this backend did in one line, and belongs to the
        backend rather than to the stage for the reason the Docker sibling gives:
        a stage that must run on both cannot know how either describes itself.
        """
        record = self._record(command_kind, result)
        record["action"] = action
        record["result"] = result_text or (
            "OK" if result.returncode == 0 else f"returncode={result.returncode}"
        )
        record["status"] = "PASS" if record["result"] == "OK" else "FAIL"
        return record

    def _endpoint(self, nodehost_or_node: Mapping[str, Any]) -> dict[str, Any]:
        """The control endpoint for whatever this is - a nodehost or a node.

        A node carries its nodehost's endpoint because the lifecycle copies it
        across in `_prepare_process_node_metadata`, the same way it copies the
        container fields.
        """
        if "host_control_endpoint" in nodehost_or_node:
            return control_endpoint_of(nodehost_or_node)
        nodehost_id = str(nodehost_or_node.get("nodehost_id", ""))
        placed = self._placed.get(nodehost_id)
        if placed is not None:
            return dict(placed["host_control_endpoint"])
        raise NativeRuntimeError(
            f"no control endpoint for {nodehost_or_node.get('logical_id') or nodehost_id or '?'}; "
            "a nodehost carries one once it has been placed on a fleet host"
        )

    def _install_bin(self, nodehost_or_node: Mapping[str, Any]) -> str:
        digest = nodehost_or_node.get("native_bundle_digest")
        if not digest:
            nodehost_id = str(nodehost_or_node.get("nodehost_id", ""))
            placed = self._placed.get(nodehost_id) or {}
            digest = placed.get("native_bundle_digest")
        if not digest:
            digest = (self._bundle_evidence or {}).get("archive_sha256")
        if not digest:
            raise NativeRuntimeError(
                "the pinned bundle digest is not known, so the installed binaries cannot be located"
            )
        return f"{NATIVE_INSTALL_ROOT}/{str(digest)[:16]}/bin"

    # ---- preflight ------------------------------------------------------

    def verify_image(self, image: str) -> dict[str, Any]:
        """Verify the pinned build products this fleet will run.

        The Docker sibling checks that an image is the pinned build. There is no
        image here, so this checks the bundle - and then checks the bundle
        against `image`, which is the run configuration's name for the build it
        asked for. Ignoring that string would let a run configured for one build
        silently ship another; the digests would still be internally consistent
        and would be consistent about the wrong thing.
        """
        if self._bundle_dir is None:
            raise NativeRuntimeError(
                "a native run needs runtime.native_bundle_dir; build one with "
                "scripts/build_native_bundle.py"
            )
        try:
            evidence = verify_native_bundle(self._bundle_dir)
        except NativeBundleError as error:
            raise NativeRuntimeError(str(error)) from error

        requested = str(image).rsplit(":", 1)[-1]
        version = str(evidence["valkey_version"])
        if not requested.startswith(version):
            raise NativeRuntimeError(
                f"the run asks for {image!r} and the bundle is Valkey {version}: "
                "the pinned build the configuration names is not the one that would be shipped"
            )
        evidence["image"] = str(image)
        self._bundle_evidence = evidence
        return evidence

    # ---- ownership ------------------------------------------------------

    def reclaim_run(self, *, capability_id: str, run_id: str) -> None:
        """Remove anything this run owns from a previous attempt, fleet-wide.

        Docker reclaims by label query. There are no labels on a host that is not
        ours, so this reclaims by the run's own path: stop whatever is running
        out of this run's state root, remove the tree, and remove any firewall
        rule the run marked. `capability_id` is not part of the path - `run_id`
        already contains it, being `<capability>-<scenario>-<date>` - and is
        accepted because the protocol passes it and a later run-id scheme might
        need it.

        It shares `release_run`'s notion of what is running, which roadmap item
        1.4 unified: this used to kill by reading each `<root>/*/valkey.pid` and
        teardown used to kill by `state.json`, two answers in one backend, and
        measurement showed neither is what is actually alive. One enumeration
        answers both. What stays different is what the seam already says is
        different - this one has no state to report from and nothing to report
        to, so it signals `KILL` outright: these are a previous attempt's
        processes, and there is nothing left to shut down gracefully for.

        The firewall removal is new here. Nothing removed those rules at all
        before, so a run that aborted while a host was isolated left a DROP chain
        installed and the next run on that host inherited it - which is the
        `reclaim` half of the roadmap's "the residue check covers rule-level
        state".
        """
        run_root = run_state_root(run_id)
        bundle_glob = f"{BUNDLE_DROP_ROOT}/vslab-bundle-{_safe_token(run_id, 'run_id')}-*"
        script = (
            _signal_owned_processes(run_root, "KILL")
            + f"rm -rf {shlex.quote(run_root)}; "
            + f"rm -rf {bundle_glob}; "
            + _remove_fault_rules(run_id)
        )
        errors: list[str] = []
        for host in self.inventory().hosts:
            try:
                result = self._run(host.control_endpoint, ["sh", "-c", script], timeout=120)
            except TransportError as error:
                errors.append(f"{host.host_id}: {error}")
                continue
            if result.returncode != 0:
                errors.append(f"{host.host_id}: {result.stderr.strip()[:200]}")
        if errors:
            raise NativeRuntimeError(
                "pre-run reclaim could not clear every host: " + "; ".join(errors)
            )

    def create_network(self, *, network_name: str, capability_id: str, run_id: str) -> None:
        """Record the run's network scope, and check the fleet actually has one.

        There is nothing to create: the product provisions no hosts and no
        network. The operation is not a no-op either, because `network_name` is
        what `isolate_nodehost` isolates *from* and the lifecycle records it on
        every nodehost for that reason.

        So this establishes the fact the fault operations depend on - that these
        hosts can reach each other on the fleet's own network - by asking each
        host for a route to every peer. A route is less than reachability and
        this claims no more than a route; what it buys is that a fleet whose
        hosts cannot see each other fails here, named, instead of ten minutes
        later as an unexplained formation timeout.
        """
        hosts = self.inventory().hosts
        unreachable: list[str] = []
        for host in hosts:
            peers = [peer for peer in hosts if peer.host_id != host.host_id]
            for peer in peers:
                result = self._run(
                    host.control_endpoint,
                    ["sh", "-c", f"ip route get {shlex.quote(peer.data_address)} >/dev/null 2>&1"],
                    timeout=30,
                )
                if result.returncode != 0:
                    unreachable.append(f"{host.host_id} has no route to {peer.host_id}")
        if unreachable:
            raise NativeRuntimeError(
                f"the fleet is not one network scope for {network_name}: " + "; ".join(unreachable)
            )
        self._network_scope = network_name

    # ---- bringing a host into the run -----------------------------------

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
        """Claim the host this nodehost was placed on and make it able to hold nodes.

        The placement already chose the host - see slice map §6.2 for why that is
        planning and not this - so what is left is: check the host is reachable
        and carries no residue of this run, install the pinned bundle, create the
        run's state root, and report where the host is.

        The handle is the run-scoped name the planner produced, which under
        Docker names a container and here names this run's claim. The address is
        the host's `data_address`, which is what `cluster-announce-ip` carries and
        what peers dial.
        """
        endpoint = control_endpoint_of(nodehost)
        run_root = f"{RUN_STATE_ROOT}/{_safe_token(run_id, 'run_id')}"

        probe = self._run(
            endpoint,
            ["sh", "-c", f"ls -A {shlex.quote(run_root)} 2>/dev/null | head -n 1"],
            timeout=30,
        )
        if probe.returncode == 0 and probe.stdout.strip():
            raise NativeRuntimeError(
                f"host {nodehost.get('host_id')} already carries state for run {run_id} at "
                f"{run_root}; reclaim before starting"
            )

        digest = self._install_native_bundle(endpoint)
        prepared = self._run(
            endpoint, ["mkdir", "-p", run_root], timeout=30
        )
        if prepared.returncode != 0:
            raise NativeRuntimeError(
                f"could not create the run state root on {nodehost.get('host_id')}: "
                f"{prepared.stderr.strip()[:200]}"
            )

        nodehost["native_bundle_digest"] = digest
        self._placed[str(nodehost["nodehost_id"])] = {
            "host_control_endpoint": dict(endpoint),
            "host_client_address": str(nodehost["host_client_address"]),
            "native_bundle_digest": digest,
        }
        return NodehostAddress(
            handle=str(nodehost["container_name"]),
            address=str(nodehost["host_data_address"]),
        )

    def _install_native_bundle(self, endpoint: Mapping[str, Any]) -> str:
        """Put the pinned binaries on a host, once per digest rather than per run.

        Content-addressed: the archive unpacks under a path named by its own
        sha256, so a host that already has that digest skips a 14 MB transfer.
        That is not a cache - it is `verify_native_bundle`'s own check, made on
        the host, and a build that differs by one byte installs elsewhere.
        """
        if self._bundle_evidence is None:
            raise NativeRuntimeError(
                "the pinned bundle has not been verified; verify_image runs before any host is touched"
            )
        assert self._bundle_dir is not None  # verify_image would have refused otherwise
        digest = str(self._bundle_evidence["archive_sha256"])
        install_dir = f"{NATIVE_INSTALL_ROOT}/{digest[:16]}"
        marker = f"{install_dir}/.installed-{digest}"

        present = self._run(endpoint, ["test", "-f", marker], timeout=30)
        if present.returncode == 0:
            return digest

        archive_name = f"{self._bundle_evidence['bundle']}.tar.gz"
        archive = self._bundle_dir / archive_name
        if not archive.is_file():
            raise NativeRuntimeError(f"the verified bundle has no archive at {archive}")

        staged = f"{BUNDLE_DROP_ROOT}/{archive_name}"
        made = self._run(endpoint, ["mkdir", "-p", install_dir], timeout=30)
        if made.returncode != 0:
            raise NativeRuntimeError(
                f"could not create {install_dir}: {made.stderr.strip()[:200]}"
            )
        self.transport.put(endpoint, archive, staged, timeout=300)

        # Hashed on the host, against the digest the manifest recorded here.
        # Verifying the bytes that arrived is the whole reason the bundle has a
        # digest; trusting the transfer would leave the check theoretical.
        install = (
            f"set -e; "
            f"actual=$(sha256sum {shlex.quote(staged)} | cut -d' ' -f1); "
            f'if [ "$actual" != {shlex.quote(digest)} ]; then '
            f'  echo "bundle arrived as $actual, expected {digest}" >&2; exit 65; '
            "fi; "
            f"tar -xzf {shlex.quote(staged)} -C {shlex.quote(install_dir)}; "
            f"rm -f {shlex.quote(staged)}; "
            f"touch {shlex.quote(marker)}"
        )
        result = self._run(endpoint, ["sh", "-c", install], timeout=300)
        if result.returncode != 0:
            raise NativeRuntimeError(
                f"could not install the pinned bundle: {result.stderr.strip()[:300]}"
            )
        return digest

    def send_bundle(self, nodehost: dict[str, Any]) -> None:
        self.transport.put(
            self._endpoint(nodehost),
            Path(str(nodehost["bundle_artifact_dir"])),
            f"{BUNDLE_DROP_ROOT}/",
            timeout=300,
        )

    def install_bundle(self, nodehost: dict[str, Any]) -> None:
        result = self._run(
            self._endpoint(nodehost),
            ["sh", f"{nodehost['remote_bundle_dir']}/install.sh"],
            timeout=120,
        )
        if result.returncode != 0:
            raise NativeRuntimeError(
                f"bundle install failed on {nodehost.get('host_id')}: {result.stderr.strip()[:300]}"
            )

    def start_node_processes(self, nodehost: dict[str, Any]) -> None:
        result = self._run(
            self._endpoint(nodehost),
            ["sh", f"{nodehost['remote_bundle_dir']}/start_all.sh"],
            timeout=max(30.0, float(nodehost.get("logical_node_count", 1)) * 3.0),
            install_path=self._install_bin(nodehost),
        )
        if result.returncode != 0:
            raise NativeRuntimeError(
                f"process start failed on {nodehost.get('host_id')}: {result.stderr.strip()[:300]}"
            )

    def collect_node_pids(self, nodehost: dict[str, Any]) -> dict[str, int]:
        result = self._run(
            self._endpoint(nodehost),
            ["sh", f"{nodehost['remote_bundle_dir']}/collect_pidfiles.sh"],
            timeout=max(45.0, float(nodehost.get("logical_node_count", 1)) * 3.0),
        )
        if result.returncode != 0:
            raise NativeRuntimeError(
                f"pidfile collection failed on {nodehost.get('host_id')}: "
                f"{result.stderr.strip()[:300]}"
            )
        collected: dict[str, int] = {}
        for line in result.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) != 2:
                continue
            logical_id = _safe_token(parts[0], "logical_id")
            try:
                collected[logical_id] = int(parts[1])
            except ValueError as error:
                raise NativeRuntimeError(
                    f"invalid pidfile value for {logical_id}: {parts[1]!r}"
                ) from error
        return collected

    def client_host(self, node: dict[str, Any]) -> str:
        """Where this process speaks RESP to the node.

        Not the address peers use. The manifest distinguishes the two and under
        the development harness they genuinely differ; on a real fleet they
        coincide and the manifest repeats one address. Returning one where the
        other was meant produces a cluster that forms but cannot be reached, or
        one reachable and never formed - which is why this comes from the
        `client_endpoint` field and never from `data_address`.
        """
        nodehost_id = str(node.get("nodehost_id", ""))
        placed = self._placed.get(nodehost_id)
        if placed is None:
            raise NativeRuntimeError(
                f"node {node.get('logical_id', '?')} names nodehost {nodehost_id!r}, which this "
                "run has not started"
            )
        return str(placed["host_client_address"])

    # ---- cluster administration ----------------------------------------

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
        """Run a `valkey-cli` from inside the fleet's own network.

        For the commands the lifecycle cannot issue from outside it - cluster
        creation, which addresses every primary on the fleet network, and any
        client that must follow a `MOVED` to an address the controller may not
        route. The caller owns the argument list; this owns only where it runs.
        """
        endpoint = self._endpoint(node)
        full_argv = ["valkey-cli", *[str(item) for item in argv]]
        bounded = max(1.0, min(900.0, float(timeout)))
        recorder = current_command_recorder()
        result = self._run(
            endpoint, full_argv, timeout=bounded, install_path=self._install_bin(node)
        )
        if recorder is not None:
            recorder.record_result(
                operation_id=operation_id,
                step_id=command_kind or "cluster_admin",
                command_kind=command_kind or "cluster_admin",
                argv=full_argv,
                started_at_unix_ms=result.started_at_unix_ms,
                ended_at_unix_ms=result.ended_at_unix_ms,
                exit_code=result.returncode,
                stdout=result.stdout.strip(),
                stderr=result.stderr.strip(),
                timeout_ms=int(bounded * 1000),
                status="PASS" if result.returncode == 0 else "FAIL",
                error_type="" if result.returncode == 0 else "NativeRuntimeError",
                node=record_node,
            )
        if result.returncode != 0:
            raise NativeRuntimeError(
                f"valkey-cli failed on {node.get('logical_id', '?')}: {result.stderr.strip()[:300]}"
            )
        return result.stdout.strip()

    # ---- one node's process ---------------------------------------------

    def stop_node(self, node: dict[str, Any], *, command_kind: str) -> list[dict[str, Any]]:
        """Ask the server to leave, then confirm the process is gone.

        The shape is the Docker backend's, deliberately: shutdown, a `TERM`
        fallback if it is still there, and the process-table wait. Confirming is
        the reason this cannot live above the seam - it reads the host's own
        process table, and there is no `/proc` on the machine the run drives
        from.
        """
        endpoint = self._endpoint(node)
        pid = _safe_pid(node["pid"])
        records = [
            self._record(
                f"{command_kind}_shutdown_nosave",
                self._run(
                    endpoint,
                    ["valkey-cli", "-p", str(node["client_port"]), "SHUTDOWN", "NOSAVE"],
                    timeout=10,
                    install_path=self._install_bin(node),
                ),
            )
        ]
        if self._wait_pid_gone(endpoint, pid, timeout=10.0):
            return records
        records.append(
            self._record(
                f"{command_kind}_kill_term_fallback",
                self._run(endpoint, ["sh", "-c", f"kill -TERM {pid}"], timeout=10),
            )
        )
        if not self._wait_pid_gone(endpoint, pid, timeout=30.0):
            raise NativeRuntimeError(
                f"owned process {node['logical_id']} pid={pid} did not stop"
            )
        return records

    def _wait_pid_gone(self, endpoint: Mapping[str, Any], pid: str, *, timeout: float) -> bool:
        """Poll the host's process table until the pid is gone or time runs out.

        The probe text is the Docker backend's, character for character, and it
        is copied rather than rewritten for a measured reason: the readability
        test and the read are two syscalls, and a process exiting between them
        made `awk` fail and the probe exit 70 - the success condition taking the
        error path. It needed exact-200's stop and kill traffic to show up
        (`4dd0fa1b`), and a second implementation reaching the same conclusion
        independently is not something to rely on.
        """
        script = (
            f"if [ ! -r /proc/{pid}/stat ]; then printf VSLAB_GONE; exit 0; fi; "
            f"s=$(awk '{{print $3}}' /proc/{pid}/stat 2>/dev/null) || "
            f"{{ [ -e /proc/{pid}/stat ] && exit 70; printf VSLAB_GONE; exit 0; }}; "
            'case "$s" in Z|X) printf VSLAB_GONE;; *) printf VSLAB_ALIVE;; esac'
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self._run(endpoint, ["sh", "-c", script], timeout=10)
            if result.returncode == 0 and "VSLAB_GONE" in result.stdout:
                return True
            time.sleep(0.5)
        return False

    def start_node(
        self, node: dict[str, Any], *, fresh_cluster_identity: bool
    ) -> tuple[int, list[dict[str, Any]]]:
        """Start the owned process again and report its new pid.

        `fresh_cluster_identity` removes the dataset as well as the recorded
        cluster identity. Both, not just `nodes.conf`: the generated config sets
        `appendonly no` and no `save` directive, so Valkey's default save policy
        lands a `dump.rdb` during any workload, and `CLUSTER REPLICATE` refuses a
        node that still holds keys. That was a real exact-50 failure
        (`313cacc9`), it looked intermittent because the RDB is only sometimes on
        disk, and the command kind below is the one the evidence already names.
        """
        endpoint = self._endpoint(node)
        records: list[dict[str, Any]] = []
        if fresh_cluster_identity:
            records.append(
                self._record(
                    "owned_valkey_process_discard_prior_state",
                    self._run(
                        endpoint,
                        [
                            "rm",
                            "-f",
                            f"{node['data_dir']}/nodes.conf",
                            f"{node['data_dir']}/dump.rdb",
                        ],
                        timeout=10,
                    ),
                    check=True,
                )
            )
        records.append(
            self._record(
                "owned_valkey_process_start",
                self._run(
                    endpoint,
                    ["valkey-server", str(node["config_file"])],
                    timeout=30,
                    install_path=self._install_bin(node),
                ),
                check=True,
            )
        )
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            try:
                if self._ping(node) == "PONG":
                    read = self._run(endpoint, ["cat", str(node["pid_file"])], timeout=10)
                    if read.returncode == 0 and read.stdout.strip().isdigit():
                        return int(read.stdout.strip()), records
            except Exception:  # noqa: BLE001 - not up yet is the normal case here
                pass
            time.sleep(0.5)
        raise NativeRuntimeError(f"owned process {node['logical_id']} did not restart")

    # ---- readiness -------------------------------------------------------

    def _ping(self, node: Mapping[str, Any], *, timeout: float = 2.0) -> str:
        """One RESP `PING` over the node's client endpoint.

        Over the client endpoint and nothing else. §16.2 forbids reaching a
        node's protocol through a runtime transport, and the Docker backend's
        `docker exec` fallback for exactly this poll was measured and removed in
        roadmap item 0.3 - a second backend must not reintroduce it as an ssh
        fallback, which would be the same defect wearing a different transport.
        """
        host = self.client_host(dict(node))
        with socket.create_connection((host, int(node["client_port"])), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(encode_command(["PING"]))
            return str(read_response(sock.makefile("rb"))).strip()

    def wait_nodes_ready(self, nodes: list[dict[str, Any]], *, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        last_ready = 0
        while time.monotonic() < deadline:
            ready = 0
            for node in nodes:
                try:
                    if self._ping(node) == "PONG":
                        ready += 1
                except Exception:  # noqa: BLE001
                    pass
            if ready == len(nodes):
                return
            last_ready = ready
            time.sleep(1)
        raise NativeRuntimeError(
            f"native runtime nodes ready timeout reached {last_ready}/{len(nodes)}"
        )

    # ---- the actuator ----------------------------------------------------

    def kill_node(self, node: dict[str, Any]) -> list[dict[str, Any]]:
        """Terminate the owned process without warning it.

        Not `stop_node` with a flag: §9.1's planned kill *is* the experiment, and
        warning the process first would measure a graceful handoff instead of a
        failure.
        """
        endpoint = self._endpoint(node)
        pid = _safe_pid(node["pid"])
        argv = ["sh", "-c", f"kill -KILL {pid}"]
        result = self._run(endpoint, argv, timeout=10)
        gone = self._wait_pid_gone(endpoint, pid, timeout=30.0)
        record = self._fault_record(
            "actuator_kill_primary",
            result,
            action=f"kill -KILL {pid} on {node.get('host_id') or node.get('nodehost_id')}",
            result_text=(
                "OK"
                if result.returncode == 0 and gone
                else f"returncode={result.returncode}, process_gone={gone}"
            ),
        )
        return [record]

    def pause_node(self, node: dict[str, Any]) -> list[dict[str, Any]]:
        pid = _safe_pid(node["pid"])
        return [
            self._fault_record(
                "owned_valkey_process_pause",
                self._run(self._endpoint(node), ["sh", "-c", f"kill -STOP {pid}"], timeout=30),
                action=f"kill -STOP {pid} on {node.get('host_id') or node.get('nodehost_id')}",
            )
        ]

    def resume_node(self, node: dict[str, Any]) -> list[dict[str, Any]]:
        pid = _safe_pid(node["pid"])
        return [
            self._fault_record(
                "owned_valkey_process_resume",
                self._run(self._endpoint(node), ["sh", "-c", f"kill -CONT {pid}"], timeout=30),
                action=f"kill -CONT {pid} on {node.get('host_id') or node.get('nodehost_id')}",
            )
        ]

    def pause_nodehost(self, nodehost: dict[str, Any]) -> list[dict[str, Any]]:
        """Suspend everything this run started on the host.

        `docker pause` freezes a container's whole cgroup. There is no cgroup to
        freeze on a host the run does not own, and suspending the host itself
        would take sshd with it and leave the actuator unable to undo its own
        action. So the unit is *the processes this run started there*, which is
        the same observable fault - the host's nodes stop answering while
        remaining cluster members - by a mechanism the backend owns, which is
        what §15 permits. It is not a claim that a whole machine was frozen.
        """
        return [self._signal_run_processes(nodehost, "STOP", "owned_nodehost_pause")]

    def resume_nodehost(self, nodehost: dict[str, Any]) -> list[dict[str, Any]]:
        return [self._signal_run_processes(nodehost, "CONT", "owned_nodehost_resume")]

    def _signal_run_processes(
        self, nodehost: dict[str, Any], signal: str, command_kind: str
    ) -> dict[str, Any]:
        run_root = run_state_root(nodehost.get("run_id") or self._run_id_from(nodehost))
        # Still by pidfile, deliberately. Roadmap item 1.4 replaced this notion
        # of "what is running" in both cleanup paths and left the actuator's
        # alone: a pidfile is current for a node that *is* running, which is the
        # only case pause and resume act on, and changing the fault path is a
        # fault-lane behaviour change that belongs to the item whose runs
        # exercise the fault lane. See `distributed_cleanup_slice_map.md` §8.5.
        script = (
            f"root={shlex.quote(run_root)}; signalled=0; "
            'for pidfile in "$root"/*/valkey.pid; do '
            '  [ -f "$pidfile" ] || continue; '
            '  pid=$(cat "$pidfile" 2>/dev/null) || continue; '
            '  case "$pid" in ""|*[!0-9]*) continue;; esac; '
            f'  kill -{signal} "$pid" 2>/dev/null && signalled=$((signalled + 1)); '
            "done; "
            'printf "%s" "$signalled"'
        )
        result = self._run(self._endpoint(nodehost), ["sh", "-c", script], timeout=30)
        return self._fault_record(
            command_kind,
            result,
            action=f"kill -{signal} every owned Valkey process on {nodehost.get('host_id')}",
        )

    @staticmethod
    def _node_run_root(node: Mapping[str, Any]) -> str:
        """This run's tree on the host holding `node`.

        A node carries `run_id` because `_prepare_process_node_metadata` writes
        it, which is a stronger source than `_run_id_from`'s bundle-name parse -
        that one exists because a *nodehost* record has no `run_id` of its own.
        """
        run_id = str(node.get("run_id") or "")
        if not run_id:
            raise NativeRuntimeError(
                f"node {node.get('logical_id', '?')} does not say which run it belongs to, "
                "so nothing placed beside it on the host could be released with the run"
            )
        return run_state_root(run_id)

    @staticmethod
    def _run_id_from(nodehost: Mapping[str, Any]) -> str:
        """The run this nodehost belongs to, read off its bundle name.

        `container_name` is `vslab-<run_id>-<nodehost_id>` and `bundle_name` is
        `vslab-bundle-<run_id>-<nodehost_id>`, both produced by the lifecycle. A
        nodehost record does not carry `run_id` on its own, and asking the
        lifecycle to add one would be widening the protocol to avoid reading a
        name the lifecycle already guarantees.
        """
        bundle_name = str(nodehost.get("bundle_name", ""))
        nodehost_id = str(nodehost.get("nodehost_id", ""))
        prefix = "vslab-bundle-"
        suffix = f"-{nodehost_id}"
        if bundle_name.startswith(prefix) and bundle_name.endswith(suffix):
            return bundle_name[len(prefix) : -len(suffix)]
        raise NativeRuntimeError(
            f"cannot tell which run nodehost {nodehost_id!r} belongs to from {bundle_name!r}"
        )

    def _fault_chain(self, nodehost: Mapping[str, Any]) -> str:
        return f"VSLAB-{str(nodehost.get('nodehost_id', 'unknown')).upper().replace('_', '-')}"

    def isolate_nodehost(self, nodehost: dict[str, Any]) -> list[dict[str, Any]]:
        """Cut the host off from everything except the channel that can undo it.

        The observable contract is fixed by `85d5096a` and is a cross-backend
        invariant: the isolated side must be *unreachable*, and the partition
        probe must be fail-closed with a recorded reason. Docker gets that by
        detaching the container from the run's network, which severs the
        published-port path too.

        The one difference this mechanism cannot avoid, stated rather than
        hidden: **the control channel stays open.** Docker's actuator reaches the
        container through the daemon and so can afford to sever every network
        path; this actuator reaches the host over the network it is cutting, and
        a rule set with no exception could not be undone. So the rules drop
        everything except this host's ssh port, which is not a path any cluster
        peer or any RESP client uses. Confirming the cut is part of the operation
        because §9.1 makes an actuator that could not act a tool error, and only
        the backend that acted can tell.
        """
        endpoint = self._endpoint(nodehost)
        chain = self._fault_chain(nodehost)
        # The port to spare is the one sshd is listening on *as the host sees
        # it*, which is not the port in the manifest: under the development
        # harness the control endpoint's port is published on the controller and
        # forwarded, so it is 22200 there and 22 here. Measured on a live host -
        # `SSH_CONNECTION=[172.18.0.1 60310 172.18.0.2 22]` - and the same
        # expression is correct on a real fleet, where the two coincide. Reading
        # it from the session is the difference between a rule that spares the
        # control channel and one that locks the actuator out of the host it
        # just partitioned.
        # The chain name is a handle; the comment below is the ownership mark.
        # Measured during roadmap item 1.4: iptables caps a chain name at 28
        # characters and a run id is 42, so the run cannot be in the name - and
        # without it in the rule, nothing finding these rules later can tell
        # whose they are. It goes on the jumps, which are what activate the
        # chain, and it is what `reclaim_run` and `release_run` search for.
        tag = shlex.quote(fault_rule_tag(nodehost.get("run_id") or self._run_id_from(nodehost)))
        marked = f"-m comment --comment {tag}"
        script = (
            "set -e; "
            'ctl=$(printf "%s" "$SSH_CONNECTION" | awk "{print \\$4}"); '
            'case "$ctl" in ""|*[!0-9]*) echo "cannot determine the control port" >&2; exit 64;; esac; '
            f"iptables -N {chain} 2>/dev/null || iptables -F {chain}; "
            f'iptables -A {chain} -p tcp --dport "$ctl" -j RETURN; '
            f'iptables -A {chain} -p tcp --sport "$ctl" -j RETURN; '
            f"iptables -A {chain} -j DROP; "
            f"iptables -C INPUT {marked} -j {chain} 2>/dev/null || iptables -I INPUT 1 {marked} -j {chain}; "
            f"iptables -C OUTPUT {marked} -j {chain} 2>/dev/null || iptables -I OUTPUT 1 {marked} -j {chain}"
        )
        result = self._run(endpoint, ["sh", "-c", script], timeout=60)
        record = self._fault_record(
            "owned_nodehost_network_disconnect",
            result,
            action=f"iptables chain {chain} dropping all but the control port on {nodehost.get('host_id')}",
        )
        if result.returncode != 0:
            self.rejoin_nodehost(nodehost)
            raise NativeRuntimeError(
                f"could not isolate {nodehost.get('host_id')}: {result.stderr.strip()[:300]}"
            )
        installed = self._run(
            endpoint,
            [
                "sh",
                "-c",
                f"iptables -C INPUT {marked} -j {chain} && iptables -C OUTPUT {marked} -j {chain}",
            ],
            timeout=30,
        )
        if installed.returncode != 0:
            self.rejoin_nodehost(nodehost)
            raise NativeRuntimeError(
                f"the isolation rules for {nodehost.get('host_id')} are not installed, so the "
                "partition did not happen"
            )
        return [record]

    def rejoin_nodehost(self, nodehost: dict[str, Any]) -> list[dict[str, Any]]:
        """Put the host back where it was.

        Removing the chain restores the address the host announced, which is why
        the address is not an argument here any more than it is for the Docker
        sibling: peers reached this host at an address this backend reported when
        the host was claimed, and restoring it is the backend's own bookkeeping.
        """
        endpoint = self._endpoint(nodehost)
        chain = self._fault_chain(nodehost)
        # Deleted by the same match that installed them - an `iptables -D` names
        # the whole rule, comment included, and one that omitted it would not
        # find the rule `isolate_nodehost` inserted.
        tag = shlex.quote(fault_rule_tag(nodehost.get("run_id") or self._run_id_from(nodehost)))
        marked = f"-m comment --comment {tag}"
        script = (
            f"iptables -D INPUT {marked} -j {chain} 2>/dev/null || true; "
            f"iptables -D OUTPUT {marked} -j {chain} 2>/dev/null || true; "
            f"iptables -F {chain} 2>/dev/null || true; "
            f"iptables -X {chain} 2>/dev/null || true; "
            "exit 0"
        )
        return [
            self._fault_record(
                "owned_nodehost_network_connect",
                self._run(endpoint, ["sh", "-c", script], timeout=60),
                action=f"remove iptables chain {chain} on {nodehost.get('host_id')}",
            )
        ]

    # ---- evidence --------------------------------------------------------

    def resource_sampler(
        self,
        nodes: list[dict[str, Any]],
        *,
        sampler_id: str,
        processes: Sequence[tuple[str, int]],
        expected_gone: Sequence[tuple[str, int]],
    ) -> "NativeResourceAgent":
        """Deploy §11.1's long-lived sampler on the host these nodes share.

        The sampler itself is unchanged - the same module, reading that host's own
        procfs and cgroupfs - because §11.1 forbids a session per sample and that
        is a property of the sampler, not of the transport. Two sessions per
        window: one to start it, one to stop and collect it.
        """
        if not nodes:
            raise NativeRuntimeError("a resource sampler needs at least one node to locate its host")
        return NativeResourceAgent(
            backend=self,
            control_endpoint=self._endpoint(nodes[0]),
            sampler_id=sampler_id,
            # Under the run's own root, so the agent needs no removal step of
            # its own and a sampler still running after an abort is found by the
            # same cwd scan as every other process of the run. `sampler_id` is
            # the `nodehost_id` and names no run, so its old root left a
            # directory per sampler on every host forever. See
            # `distributed_cleanup_slice_map.md` §2.4.
            run_root=self._node_run_root(nodes[0]),
            processes=list(processes),
            expected_gone=list(expected_gone),
        )

    def load_lane_host(self, node: dict[str, Any]) -> "NativeLoadLaneHost":
        """Where the Load Lane runs, and how what it writes gets back here.

        On the node's own host, for the reason the Docker sibling gives: memtier
        in cluster mode follows `MOVED` to the addresses the cluster announces,
        and a host on the fleet network can route them whether or not the
        controller can. §8 fixes the lane's tool and parameters; a backend
        chooses the host and nothing else.
        """
        return NativeLoadLaneHost(
            backend=self,
            control_endpoint=self._endpoint(node),
            install_path=self._install_bin(node),
        )

    def host_evidence(self, nodehost: dict[str, Any]) -> "NativeHostEvidence":
        """The host itself, for what only it can answer: its clock and its logs.

        No install path: reading a clock and copying a file need nothing the
        pinned bundle provides, and a run whose bundle install failed must still
        be able to say what its hosts' clocks said.
        """
        return NativeHostEvidence(backend=self, control_endpoint=self._endpoint(nodehost))

    # ---- teardown --------------------------------------------------------

    #: How long `verify_exit` waits on a host for the run's processes to go,
    #: in half-second attempts. Sized on what it is waiting for: a Valkey node
    #: that has been asked to exit writes its RDB if one is due and closes its
    #: files, which is the same wait `_wait_container_pids_gone` gives the Docker
    #: path.
    RELEASE_EXIT_ATTEMPTS = 60

    def release_run(self, state: Mapping[str, Any]) -> RunTeardown:
        """Release everything this run owns on every host, and report the residue.

        Works from `state` alone, which is what makes `cli gate cleanup` able to
        release a run this process did not start: placement wrote each nodehost's
        control endpoint into the plan, and the plan is in state.

        It terminates **what is alive and provably this run's**, not what state
        remembers. Roadmap item 1.4 measured why the alternatives do not work:
        `state.json` is last written before the management matrix, so the rolling
        restart and the fault matrix have replaced every pid in it by the time
        cleanup runs (fifty pids, zero overlap, on both frozen baselines); and a
        pidfile is not current either, because a SIGKILLed node leaves one
        holding a dead pid while a cleanly stopped node removes its own. Both
        would have teardown signal numbers that now belong to somebody else.

        What is alive and ours is read from the host: every process whose working
        directory is inside this run's state root. See `_owned_process_walk` for
        why that is the mark and `ps` is not.

        There is no `docker rm -f` here to stop the fleet if the signalling
        misses, so the scan at the end is the operation's honest part: it asks
        the host again, and what it reports becomes `resources_remaining`.
        """
        runtime = state.get("runtime") if isinstance(state.get("runtime"), dict) else {}
        run_id = str(runtime.get("run_id") or "")
        if not run_id:
            raise NativeRuntimeError("cleanup requires runtime ownership with an explicit run_id in state")
        nodehosts = [row for row in state.get("nodehosts", []) if isinstance(row, dict)]
        if not nodehosts:
            raise NativeRuntimeError(
                f"state for run {run_id} names no nodehosts, so it does not describe a native fleet "
                "this backend can release"
            )

        nodes_by_nodehost: dict[str, list[dict[str, Any]]] = {}
        for node in state.get("nodes", []):
            if isinstance(node, dict) and node.get("nodehost_id"):
                nodes_by_nodehost.setdefault(str(node["nodehost_id"]), []).append(node)

        actions: list[dict[str, Any]] = []
        errors: list[str] = []
        resources_remaining: list[dict[str, Any]] = []
        timing: dict[str, Any] = {"parallelism": 1, "bounded_parallelism": False}
        elapsed: dict[str, float] = {}

        run_root = run_state_root(run_id)
        for nodehost in sorted(nodehosts, key=lambda item: str(item.get("nodehost_id", ""))):
            nodehost_id = str(nodehost.get("nodehost_id", "?"))
            try:
                endpoint = control_endpoint_of(nodehost)
            except Exception as error:  # noqa: BLE001 - reported, not raised
                errors.append(f"{nodehost_id}: {error}")
                continue
            hosted = nodes_by_nodehost.get(nodehost_id, [])
            state_pids = [
                node
                for node in hosted
                if str(node.get("pid", "")).strip().isdigit() and int(node["pid"]) > 0
            ]
            steps = (
                (
                    "cleanup_terminate_processes_seconds",
                    lambda: self._release_terminate(
                        endpoint, nodehost_id, nodehost, run_root, len(state_pids)
                    ),
                ),
                (
                    "cleanup_verify_process_exit_seconds",
                    lambda: self._release_verify_exit(endpoint, nodehost_id, nodehost, run_root),
                ),
                (
                    "cleanup_remove_firewall_rules_seconds",
                    lambda: self._release_remove_rules(endpoint, nodehost_id, nodehost, run_id),
                ),
                (
                    "cleanup_remove_run_state_seconds",
                    lambda: self._release_remove_state(endpoint, nodehost_id, nodehost, run_root),
                ),
            )
            for key, step in steps:
                started = time.monotonic()
                actions.append(step())
                elapsed[key] = elapsed.get(key, 0.0) + max(time.monotonic() - started, 0.0)

            started = time.monotonic()
            remaining, scan_action = self._release_scan(
                endpoint, nodehost_id, nodehost, run_root, run_id
            )
            elapsed["cleanup_residual_scan_seconds"] = elapsed.get(
                "cleanup_residual_scan_seconds", 0.0
            ) + max(time.monotonic() - started, 0.0)
            actions.append(scan_action)
            resources_remaining.extend(remaining)

        timing.update({key: round(value, 6) for key, value in elapsed.items()})
        return RunTeardown(
            actions=actions,
            resources_remaining=resources_remaining,
            timing=timing,
            errors=errors,
        )

    def _release_terminate(
        self,
        endpoint: Mapping[str, Any],
        nodehost_id: str,
        nodehost: Mapping[str, Any],
        run_root: str,
        state_pid_count: int,
    ) -> dict[str, Any]:
        """`TERM` every process of this run on this host, and say which.

        `pid_count` is what was signalled and `state_pid_count` is what
        `state.json` believed was running. They are both recorded because the gap
        between them is the evidence for the staleness this operation stopped
        trusting, and a reader should be able to see it in the artifact rather
        than in a document.
        """
        result = self._run(
            endpoint,
            [
                "sh",
                "-c",
                _signal_owned_processes(run_root, "TERM", resume_first=True) + "exit 0",
            ],
            timeout=120,
        )
        signalled = _parse_owned_processes(result.stdout)
        return {
            "type": "nodehost_valkey_processes",
            "id": nodehost_id,
            "container_name": str(nodehost.get("container_name", "")),
            "action": "terminate",
            "status": "PASS" if result.returncode == 0 else "FAIL",
            "reason": "" if result.returncode == 0 else "The process enumeration could not be run on this host.",
            "pid_count": len(signalled),
            "state_pid_count": state_pid_count,
            "processes": signalled,
            "stderr": result.stderr.strip(),
        }

    def _release_verify_exit(
        self,
        endpoint: Mapping[str, Any],
        nodehost_id: str,
        nodehost: Mapping[str, Any],
        run_root: str,
    ) -> dict[str, Any]:
        """Wait for them to go, then `KILL` whatever would not.

        `TERM` then `KILL` rather than `KILL` outright: a node asked to exit
        closes its files and removes its own pidfile. The escalation exists
        because teardown has to finish, and what it escalates against is reported
        rather than swallowed.
        """
        waited = self._run(
            endpoint,
            ["sh", "-c", _await_owned_processes_gone(run_root, attempts=self.RELEASE_EXIT_ATTEMPTS)],
            timeout=60 + self.RELEASE_EXIT_ATTEMPTS,
        )
        survivors = _parse_owned_processes(waited.stdout)
        killed: list[dict[str, Any]] = []
        if survivors:
            forced = self._run(
                endpoint,
                ["sh", "-c", _signal_owned_processes(run_root, "KILL") + "exit 0"],
                timeout=120,
            )
            killed = _parse_owned_processes(forced.stdout)
        return {
            "type": "nodehost_valkey_processes",
            "id": nodehost_id,
            "container_name": str(nodehost.get("container_name", "")),
            "action": "verify_exit",
            "status": "PASS" if waited.returncode == 0 and not survivors else "SKIPPED_WITH_REASON",
            "reason": (
                ""
                if waited.returncode == 0 and not survivors
                else "Processes of this run were still running after termination; they were killed and the residual scan determines the outcome."
            ),
            "alive_pid_count": len(survivors),
            "alive_processes": survivors,
            "killed_pid_count": len(killed),
            "stderr": waited.stderr.strip(),
        }

    def _release_remove_rules(
        self,
        endpoint: Mapping[str, Any],
        nodehost_id: str,
        nodehost: Mapping[str, Any],
        run_id: str,
    ) -> dict[str, Any]:
        """Remove the firewall state the actuator may have left on this host."""
        result = self._run(endpoint, ["sh", "-c", _remove_fault_rules(run_id)], timeout=60)
        removed = [line.split("\t") for line in result.stdout.splitlines() if "\t" in line]
        return {
            "type": "nodehost_firewall_rules",
            "id": nodehost_id,
            "container_name": str(nodehost.get("container_name", "")),
            "action": "remove",
            "status": "PASS" if result.returncode == 0 else "FAIL",
            "jump_count": sum(1 for row in removed if row[0] == "jump"),
            "chain_count": sum(1 for row in removed if row[0] == "chain"),
            "chains_held": [row[1] for row in removed if row[0] == "held"],
            "stderr": result.stderr.strip(),
        }

    def _release_remove_state(
        self,
        endpoint: Mapping[str, Any],
        nodehost_id: str,
        nodehost: Mapping[str, Any],
        run_root: str,
    ) -> dict[str, Any]:
        bundle_dir = str(nodehost.get("remote_bundle_dir", "")).strip()
        removals = [run_root] + ([bundle_dir] if bundle_dir else [])
        script = "; ".join(f"rm -rf {shlex.quote(path)}" for path in removals) + "; exit 0"
        result = self._run(endpoint, ["sh", "-c", script], timeout=60)
        return {
            "type": "nodehost_run_state",
            "id": nodehost_id,
            "container_name": str(nodehost.get("container_name", "")),
            "action": "remove",
            "status": "PASS" if result.returncode == 0 else "FAIL",
            "paths": removals,
            "stderr": result.stderr.strip(),
        }

    def _release_scan(
        self,
        endpoint: Mapping[str, Any],
        nodehost_id: str,
        nodehost: Mapping[str, Any],
        run_root: str,
        run_id: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """What is still there, which is the criterion measured rather than asserted.

        All three kinds of residue the roadmap names for this item: a process
        still running out of this run's tree, the tree itself, and rule-level
        state. Each is a fresh question to the host rather than a restatement of
        what the steps above believe they did - a backend that reported its own
        `rm` as proof would be asserting the criterion instead of measuring it,
        and there is no `docker rm -f` here to make the assertion true anyway.
        """
        host_id = str(nodehost.get("host_id", ""))
        remaining: list[dict[str, Any]] = []
        failures: list[str] = []

        tree_scan = self._run(endpoint, ["sh", "-c", _scan_run_residue(run_root)], timeout=60)
        if tree_scan.returncode != 0:
            failures.append("process")
        if any(line.strip() == "state" for line in tree_scan.stdout.splitlines()):
            remaining.append(
                {
                    "type": "nodehost_run_state",
                    "id": nodehost_id,
                    "host_id": host_id,
                    "path": run_root,
                }
            )
        for row in _parse_owned_processes(tree_scan.stdout):
            remaining.append(
                {
                    "type": "valkey_process",
                    "id": nodehost_id,
                    "host_id": host_id,
                    "pid": row["pid"],
                    "cwd": row["cwd"],
                    "exe": row["exe"],
                }
            )

        rule_scan = self._run(
            endpoint,
            ["sh", "-c", _scan_fault_rules(run_id, [self._fault_chain(nodehost)])],
            timeout=60,
        )
        if rule_scan.returncode != 0:
            failures.append("firewall")
        for line in rule_scan.stdout.splitlines():
            kind, _, detail = line.partition("\t")
            if kind not in {"rule", "chain"} or not detail.strip():
                continue
            remaining.append(
                {
                    "type": "nodehost_firewall_rule",
                    "id": nodehost_id,
                    "host_id": host_id,
                    "kind": kind,
                    "detail": detail.strip()[:200],
                }
            )

        return remaining, {
            "type": "nodehost_residual_scan",
            "id": nodehost_id,
            "container_name": str(nodehost.get("container_name", "")),
            "action": "scan",
            "status": "PASS" if not failures else "FAIL",
            "scanned": ["state", "process", "firewall"],
            "unscannable": failures,
            "found": len(remaining),
        }


class NativeResourceAgent:
    """§11.1's sampler, on a host, started once and collected once."""

    def __init__(
        self,
        *,
        backend: NativeMultiEcsBackend,
        control_endpoint: Mapping[str, Any],
        sampler_id: str,
        run_root: str,
        processes: list[tuple[str, int]],
        expected_gone: list[tuple[str, int]],
    ) -> None:
        self._backend = backend
        self._endpoint = dict(control_endpoint)
        self.sampler_id = sampler_id
        self._processes = processes
        self._expected_gone = expected_gone
        self._root = f"{run_root}/{RESOURCE_AGENT_SUBDIR}"
        self._dir = f"{self._root}/{_safe_token(sampler_id, 'sampler_id')}"
        self._out = f"{self._dir}/resource_samples.json"
        self._pidfile = f"{self._dir}/agent.pid"
        self._active_file = f"{self._dir}/expected_gone_active"
        self._started = False

    def start(self) -> None:
        if self._started:
            raise NativeRuntimeError(f"resource agent for {self.sampler_id} is already running")
        spec = {
            "sampler_id": self.sampler_id,
            "processes": [
                {"logical_id": logical_id, "pid": pid} for logical_id, pid in self._processes
            ],
            "expected_gone_processes": [
                {"logical_id": logical_id, "pid": pid} for logical_id, pid in self._expected_gone
            ],
        }
        package = Path(__file__).resolve().parents[1]
        made = self._backend._run(self._endpoint, ["mkdir", "-p", self._dir], timeout=60)
        if made.returncode != 0:
            raise NativeRuntimeError(f"could not create {self._dir}: {made.stderr.strip()[:200]}")
        self._backend.transport.put(
            self._endpoint, package, f"{self._root}/valkey_scale_lab", timeout=300
        )
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(spec, handle, sort_keys=True)
            spec_path = handle.name
        try:
            self._backend.transport.put(
                self._endpoint, Path(spec_path), f"{self._dir}/spec.json", timeout=60
            )
        finally:
            Path(spec_path).unlink(missing_ok=True)
        launch = (
            f"cd {shlex.quote(self._root)} && "
            f"PYTHONPATH={shlex.quote(self._root)} "
            "nohup python3 -m valkey_scale_lab.observability.resource_agent "
            f"--spec {shlex.quote(self._dir)}/spec.json "
            f"--out {shlex.quote(self._out)} "
            f"--expected-gone-active-file {shlex.quote(self._active_file)} "
            f">{shlex.quote(self._dir)}/agent.log 2>&1 & echo $! > {shlex.quote(self._pidfile)}"
        )
        result = self._backend._run(self._endpoint, ["sh", "-c", launch], timeout=120)
        if result.returncode != 0:
            raise NativeRuntimeError(f"could not launch the resource agent: {result.stderr.strip()[:300]}")
        self._started = True

    def mark_expected_gone_active(self) -> None:
        self._backend._run(self._endpoint, ["touch", self._active_file], timeout=60)

    def stop(self) -> dict[str, Any]:
        if not self._started:
            raise NativeRuntimeError(f"resource agent for {self.sampler_id} was never started")
        stop_script = (
            f"pid=$(cat {shlex.quote(self._pidfile)}) && kill -TERM \"$pid\" && "
            f"for _ in $(seq 1 30); do "
            f"  [ -f {shlex.quote(self._out)} ] && exit 0; sleep 1; done; "
            f"cat {shlex.quote(self._dir)}/agent.log >&2; exit 1"
        )
        result = self._backend._run(self._endpoint, ["sh", "-c", stop_script], timeout=180)
        if result.returncode != 0:
            raise NativeRuntimeError(
                f"resource agent {self.sampler_id} did not write its samples: "
                f"{result.stderr.strip()[:500]}"
            )
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "resource_samples.json"
            self._backend.transport.get(self._endpoint, self._out, local, timeout=120)
            return json.loads(local.read_text(encoding="utf-8"))


class NativeLoadLaneHost:
    """A fleet host, as a place to run the Load Lane and collect what it wrote."""

    def __init__(
        self,
        *,
        backend: NativeMultiEcsBackend,
        control_endpoint: Mapping[str, Any],
        install_path: str,
    ) -> None:
        self._backend = backend
        self._endpoint = dict(control_endpoint)
        self._install_path = install_path
        # The node this host was chosen for answers on the host's own loopback,
        # because that is where its process listens. An attribute rather than a
        # question for the reason `NodehostAddress` carries `address`: the
        # backend knows it when it picks the host.
        self.seed_host = "127.0.0.1"

    def command(self, argv: Sequence[str], *, remote_dir: str) -> list[str]:
        """The *local* argv that runs `argv` on this host, `remote_dir` made first.

        Returns the argv rather than spawning, because the argv is recorded
        evidence: the load lane reports it and the stability observation keeps
        it.
        """
        remote = (
            f"PATH={shlex.quote(self._install_path)}:$PATH; "
            f"mkdir -p {shlex.quote(remote_dir)} && "
            f"exec {shlex.join([str(item) for item in argv])}"
        )
        transport = self._backend.transport
        ssh_argv = getattr(transport, "_ssh_argv", None)
        if ssh_argv is None:
            raise NativeRuntimeError(
                "this transport cannot express a load-lane command as a local argv"
            )
        return list(ssh_argv(self._endpoint)) + ["sh", "-c", shlex.quote(remote)]

    def collect_evidence(self, remote_dir: str, local_dir: Path) -> None:
        local_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._backend.transport.get(
                self._endpoint, f"{remote_dir}/.", local_dir, timeout=300
            )
        except TransportError as error:
            # §12.1 puts 必要证据无法写入 on the collector's side of the line, and
            # the Docker sibling has always raised this class here. Letting a
            # `TransportError` out instead reported a failed copy as `FAIL` - the
            # claim that the cluster was observed and found wanting - because
            # `is_collection_failure` answers False for anything it cannot place.
            raise CollectionError(
                f"could not collect load lane evidence from {remote_dir}: {error}"
            ) from error


class NativeHostEvidence:
    """A fleet host, as the machine whose clock and node journals are wanted."""

    def __init__(
        self,
        *,
        backend: NativeMultiEcsBackend,
        control_endpoint: Mapping[str, Any],
    ) -> None:
        self._backend = backend
        self._endpoint = dict(control_endpoint)

    def clock_exchanges(self, count: int) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for _ in range(max(1, int(count))):
            before = _unix_ms()
            try:
                result = self._backend._run(self._endpoint, list(HOST_CLOCK_ARGV), timeout=30)
            except TransportError as error:
                raise CollectionError(f"could not read a host clock: {error}") from error
            after = _unix_ms()
            if result.returncode != 0:
                raise CollectionError(
                    f"could not read a host clock: {result.stderr.strip()[:300]}"
                )
            wall, monotonic = parse_host_clock(result.stdout)
            rows.append(
                {
                    "controller_before_unix_ms": before,
                    "host_unix_ms": wall * 1000.0,
                    "host_monotonic_seconds": monotonic,
                    "controller_after_unix_ms": after,
                }
            )
        return rows

    def collect_node_journal(self, node: Mapping[str, Any], local_path: Path) -> None:
        log_file = str(node.get("log_file") or "")
        if not log_file:
            raise CollectionError(
                f"node {node.get('logical_id', '?')} has no recorded log file to collect"
            )
        local_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._backend.transport.get(self._endpoint, log_file, local_path, timeout=300)
        except TransportError as error:
            raise CollectionError(
                f"could not collect the journal of {node.get('logical_id', '?')} "
                f"from {log_file}: {error}"
            ) from error


#: The runtime configuration keys a native run needs and a Docker run has no use
#: for. Both are paths: the fleet the run was given, and the pinned build it
#: ships. Neither is discovered - the product provisions nothing and builds
#: nothing at run time.
NATIVE_INVENTORY_CONFIG_KEY = "host_inventory_path"
NATIVE_BUNDLE_CONFIG_KEY = "native_bundle_dir"


def build_native_backend_for_run(runtime_config: Mapping[str, Any]) -> NativeMultiEcsBackend:
    """Construct the backend from a run's `runtime` configuration.

    Refuses rather than defaults. A native run with no fleet named would
    otherwise fall through to an empty inventory and fail much later, as a
    placement error about a fleet nobody asked for.
    """
    inventory_path = runtime_config.get(NATIVE_INVENTORY_CONFIG_KEY)
    bundle_dir = runtime_config.get(NATIVE_BUNDLE_CONFIG_KEY)
    missing = [
        key
        for key, value in (
            (NATIVE_INVENTORY_CONFIG_KEY, inventory_path),
            (NATIVE_BUNDLE_CONFIG_KEY, bundle_dir),
        )
        if not value
    ]
    if missing:
        raise NativeRuntimeError(
            "a native run needs " + " and ".join(f"runtime.{key}" for key in missing)
        )
    return NativeMultiEcsBackend(inventory_path=str(inventory_path), bundle_dir=str(bundle_dir))


# The registry entry `native_multi_ecs` was absent from until now. The scenario
# set is the one `docker_process` carries, because M3's thesis is the same
# lifecycle semantics on a different runtime and a scenario this backend refused
# would be a semantic difference rather than a runtime one. No Docker daemon is
# required, which is the whole point of the Gate check having become a backend
# property at `39e31b1a`.
NATIVE_MULTI_ECS_BACKEND = register_backend(
    BackendSpec(
        backend_id="native_multi_ecs",
        profiles=frozenset({"small-real"}),
        profile_prefixes=("exact-",),
        scenarios=frozenset(
            {
                "local_full_flow",
                "management_matrix",
                "fault_matrix",
                "failover",
                "failover_latency_curve",
                "failover_timeline",
                "clean_gate_diagnostics",
                "cluster_timeout",
                "server_profile",
                "nodehost_density",
            }
        ),
        node_backend=lambda: NativeMultiEcsBackend(),
        node_backend_for_run=build_native_backend_for_run,
        requires_local_docker_daemon=False,
    )
)
