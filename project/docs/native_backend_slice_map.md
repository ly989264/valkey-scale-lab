# Roadmap item 1.2: the native backend

Session M3-A-2. Scope is exactly this item. Written before any code, from the
working Docker implementation, per the project's slice method.

Read `simulated_host_and_native_bundle_map.md` first: it carries the harness and
the bundle this item consumes, and §3 of it fixes the three addresses a host
record carries. Read `seam_completion_slice_map.md` for the protocol this owes.

What this item does **not** own, named here so no later reader mistakes an
omission for an oversight: node-log collection is item 1.3's and its mechanism is
not pre-decided here; the stale-pid teardown finding is item 1.4's; the real
runs, the equivalence diff and the declared vocabulary deltas are item 1.5's.

---

## 1. What "the backend exists" has to mean

`runtime/backends.py` is a data registry and `native_multi_ecs` is absent from it
rather than rejected, so registering a second backend is "an entry there plus a
`NodeBackend`". That sentence is accurate and it is also the whole of what was
inherited: nothing has ever been written against the seam except the Docker
implementation, and a protocol with one implementation is a description of that
implementation until a second one disagrees with it.

So this item is not only twenty-three method bodies. It is the first test of
three inherited claims, and the map records where each one held and where it did
not:

1. **That the seam is complete.** It nearly is. §4 records the one operation
   whose Docker meaning does not survive translation (`create_network`) and the
   three whose arguments turn out to be the *planner's* rather than the
   backend's.
2. **That the lifecycle names no Docker primitive.** True of `lifecycle.py`
   itself. Not true of three sites it calls, which are named in §6 and which are
   what actually decides how much of this item is reachable in one session.
3. **That the inventory vocabulary might be semantically wrong.** §7 decides it.
   It is not.

---

## 2. The transport, measured

The roadmap makes this a decision point and names the measurement: per-operation
overhead against the rolling restart's budget, multiplexed SSH as the simplest
candidate, an extended on-host agent as the fallback if measurement rejects it.

### 2.1 The budget, taken from the run that pays it

Not assumed. The frozen exact-50 baseline's `management_command_log.jsonl`
(1,592 rows) carries every management command with its start and end, and the
rolling restart's two backend operations dominate it:

| Command, all of them a `docker exec` | n | median | p90 | max |
|---|---|---|---|---|
| `owned_valkey_process_restart_stop_shutdown_nosave` | 100 | 71 ms | 86 ms | 97 ms |
| `owned_valkey_process_start` | 104 | 61 ms | 75 ms | 85 ms |

So the per-operation budget a second transport must meet is **~60–75 ms**, and
it is the cost of one `docker exec` round trip, not of Valkey doing anything -
the RESP rows in the same log run at 1–3 ms.

Those are not the only round trips a stop costs. `stop_node` issues the shutdown
and then loops a `/proc/<pid>/stat` readability probe until the process is gone,
and `start_node` adds a `cat` of the pidfile plus a readiness poll. The probe is
the operation with the property the roadmap names - "confirmation that reads the
host's process table" - so it was measured as its own arm.

### 2.2 The spike

Two simulated hosts (`--fleet-id spike --hosts 2`), 60 repetitions per arm,
alternating hosts, measured 2026-08-11 on this Mac. The `docker exec` arm runs
against the same two containers, so the comparison is same-machine and same-hour
rather than against a number recorded in June.

| Transport | median | p90 | max | failures |
|---|---|---|---|---|
| `docker exec`, trivial command | **66.4 ms** | 76.1 | 82.2 | 0 |
| `docker exec`, `/proc` probe | **67.0 ms** | 75.7 | 82.3 | 0 |
| ssh, no multiplexing, trivial | 63.8 ms | 70.7 | 87.9 | 0 |
| ssh, no multiplexing, `/proc` probe | 65.8 ms | 72.7 | 76.1 | 0 |
| ssh, multiplexed, trivial | **10.8 ms** | 13.0 | 14.9 | 0 |
| ssh, multiplexed, `/proc` probe | **14.2 ms** | 17.1 | 19.3 | 0 |

At the run's own parallelism (`CLUSTER_ORCHESTRATION_PARALLELISM = 8`), 60
commands across two hosts:

| Transport | median | wall | throughput |
|---|---|---|---|
| `docker exec` | 63.5 ms | 546.6 ms | 109.8 /s |
| ssh, no multiplexing | 55.6 ms | 453.7 ms | 132.2 /s |
| ssh, multiplexed | **11.9 ms** | **101.0 ms** | **594.1 /s** |

Opening a master costs 65.3 ms and 57.1 ms - one handshake per host, once.

Two things in this table are worth stating rather than leaving to be read off.
**Un-multiplexed ssh already meets the budget**, which is a fact about how
expensive `docker exec` is rather than about how cheap ssh is: both pay a
process spawn and a socket round trip to a daemon on the same machine.
And **multiplexing is where the win is** - 6.2× under budget serially, 5.3×
under it at parallelism 8.

### 2.3 The decision

**Multiplexed SSH.** The measurement does not reject it; it clears the budget by
more than five times, so the extended on-host agent is not built. Recorded per
the roadmap's decision-point rule, and **provisional**: these are simulated
numbers, therefore lower bounds, and the point closes for real in M3-B (item 1.6)
where a VPC round trip is added to every one of them. The transport stays behind
the backend so a later switch is cheap, which is the roadmap's own condition.

What the numbers do *not* license is a claim about a real fleet's absolute times.
What they do license is the shape: the per-command cost of a multiplexed session
is dominated here by the local `ssh` client's own process spawn, and the
throughput plateau in §2.4 is that spawn, not the network. On a real fleet the
network term is added to the per-command latency and the plateau moves.

### 2.4 Two constraints the spike found that reading could not

- **`ControlPath` is capped at 104 bytes.** The first spike run failed outright:
  `ControlPath too long ('/private/tmp/.../scratchpad/mux/cm-sim-host-00' >= 104
  bytes)`. It is the `sockaddr_un` limit, so it is a property of the platform and
  not of this harness. The run's own artifacts directory is a long path under a
  long project path, so the mux socket **cannot live beside the run's artifacts**;
  it goes in a short run-scoped directory, and the backend fails with a stated
  reason rather than a truncated socket if the path it computes is over the
  limit.
- **`MaxSessions` is 10 and does not fail - it queues.** The simulated host's
  sshd reports the stock `maxsessions 10`, which a real ECS host also ships. One
  master, one host, rising concurrency, 60–128 commands per level:

  | parallelism | 1 | 4 | 8 | 10 | 16 | 32 |
  |---|---|---|---|---|---|---|
  | median | 10.6 ms | 8.8 | 11.8 | 13.7 | 17.3 | 23.0 |
  | p90 | 13.0 ms | 10.3 | 15.5 | 19.1 | 33.3 | 45.8 |
  | throughput | 92.3 /s | 429.7 | 598.3 | 606.8 | 606.5 | 603.5 |
  | failures | 0 | 0 | 0 | 0 | 0 | **0** |

  Past `MaxSessions` the client waits rather than erroring: latency rises and
  throughput plateaus at ~600 /s from parallelism 8 onward. So the limit is a
  latency term, not a failure mode, and the backend does not need its own
  session semaphore. It is still worth recording, because at exact-200 the run's
  parallelism of 8 is spread over the *fleet* while the session limit is
  *per host* - a two-host fleet puts 4 of the 8 on each master, and a fleet of
  one would put all 8 on one.

### 2.5 Transfer, measured for the same reason

`send_bundle` and the evidence pull move files rather than run commands, so they
were measured separately: a real nodehost config bundle from the frozen baseline
(29.4 KB, 25 node configs plus three scripts) and the pinned native bundle
archive (14.16 MB).

| | scp cold | scp muxed | `docker cp` |
|---|---|---|---|
| config bundle, 29.4 KB | 108.5 ms | 48.4 ms | 22.4 ms |
| native bundle archive, 14.16 MB | – | **116.1 ms** | 149.7 ms |

scp over an existing master is 2.2× the cost of `docker cp` for the small
bundle - once per nodehost, so under half a second across an exact-200 fleet -
and is *faster* than `docker cp` for the 14 MB archive. Transfer is not a
constraint on this item and no streaming or batching is built. (Evidence volume
stays the roadmap's open decision point, resolved at the end of M3.)

---

## 3. What a native "nodehost" is, and the constraint that follows

Under Docker a nodehost is created by `start_nodehost` and destroyed by
`release_run`. Under a manifest the host exists before the run and outlives it,
so `start_nodehost` cannot mean "create"; it means **claim an existing host for
this run and make it able to hold node processes**.

That distinction is not cosmetic, and it produces the item's sharpest derived
constraint. The density planner emits nodehosts as *fault domains*: it refuses a
plan where a shard's primary and replica share one (`_primary_replica_nodehost_
safe`), and the fault actuator acts on them - `pause_nodehost` suspends "a whole
host and everything it runs", `isolate_nodehost` "cuts a host off". Under Docker
each nodehost is its own container, so nodehost and fault domain coincide by
construction. Under a manifest they only coincide if the placement makes them.

**Therefore a native run places exactly one nodehost per manifest host, and
refuses a plan that would place two.** Two nodehosts on one host would make
`pause_nodehost` suspend a domain the planner believed was independent, and the
placement check that the planner performs would be checking something that is no
longer true. This is a refusal rather than a silent merge because a plan whose
fault domains are not real produces fault-lane evidence that means nothing.

Its consequence is arithmetic and belongs to item 1.5 rather than here: with
`max_logical_nodes_per_nodehost` at 25, a two-host fleet holds exact-50 exactly
and cannot hold exact-200. That is the roadmap's own density question (item 0.7)
arriving early, and this item's job is to make it a stated refusal instead of a
surprise at run time.

---

## 4. The twenty-three operations, derived

Grouped by what translation actually costs, not by the order they appear in.

### 4.1 The eleven that are a transport substitution and nothing more

`send_bundle`, `install_bundle`, `start_node_processes`, `collect_node_pids`,
`run_cluster_admin`, `stop_node`, `start_node`, `kill_node`, `pause_node`,
`resume_node`, `wait_nodes_ready`.

Each is `docker exec <container> <argv>` or `docker cp` today, and each becomes
the same argv over the host's control endpoint. The record shapes are unchanged:
`_exec_record`'s seven fields, and `_fault_record`'s two more. Three details
carry over exactly and are worth naming because each was itself a measured fix:

- `stop_node` keeps `SHUTDOWN NOSAVE`, then a `TERM` fallback, then the
  `/proc/<pid>/stat` wait, including the two-syscall race `4dd0fa1b` fixed - the
  probe text is copied rather than rewritten, because it is the success condition
  taking the error path that made an exact-200 fail.
- `start_node(fresh_cluster_identity=True)` removes `nodes.conf` **and**
  `dump.rdb`, per `313cacc9`, and keeps the command kind
  `owned_valkey_process_discard_prior_state`. A native backend that removed only
  `nodes.conf` would reintroduce a defect that took three commits to find.
- `kill_node` records the signal it sent, not the transport that carried it, so
  its `argv` field stays `["sh", "-c", "kill -KILL <pid>"]` and only `action`
  differs between backends. This is already how the Docker backend behaves and
  it is why the fault evidence compares across backends at all.

There is no `kill` binary in the pinned image, so the Docker backend sends every
signal through the shell builtin. A simulated host has coreutils, so a native
backend *could* use `/bin/kill`. It does not: `sh -c "kill -KILL <pid>"` works on
both, and having the two backends emit different `argv` for the same action would
put a difference into the fault evidence that says nothing about the runtime.

### 4.2 The five where the host is the unit, not the process

`start_nodehost`, `pause_nodehost`, `resume_nodehost`, `isolate_nodehost`,
`rejoin_nodehost`.

- **`start_nodehost`** claims the host named by the placement (§3), verifies it
  is reachable and empty of a prior run's residue, installs the pinned bundle
  (§5), creates the run-scoped state root, and returns
  `NodehostAddress(handle, address)`. `handle` is the run-scoped claim - the same
  string the planner already produces as `container_name` - and `address` is the
  host's `data_address` from the manifest, which is what `cluster-announce-ip`
  will carry.
- **`pause_nodehost` / `resume_nodehost`** are `docker pause` today, which
  freezes the container's whole cgroup. There is no cgroup to freeze on a host
  the run does not own, so the native form signals `STOP`/`CONT` to **the
  processes this run started on that host**, which is the set the run's own state
  names. This is a mechanism difference with the same observable contract, which
  is what §15 permits and what M3's thesis requires. It is *not* the same as
  suspending the host - a real host suspension would take sshd with it and the
  actuator could not undo it - and the map says so rather than letting a later
  reader assume `docker pause`'s exact semantics were reproduced.
- **`isolate_nodehost` / `rejoin_nodehost`** use `iptables` under `NET_ADMIN`,
  which item 1.0 verified works inside a simulated host. The observable contract
  is fixed by `85d5096a` and is a cross-backend invariant: the isolated side must
  be **unreachable**, and the partition probe must be fail-closed with a recorded
  reason. `isolate_nodehost` confirms its own action before returning and undoes
  itself if it could not act, exactly as the Docker one does, because §9.1 makes
  an actuator that could not act a tool error rather than a cluster verdict.

  One asymmetry has to be handled deliberately: Docker's `network disconnect`
  severs the published-port path too, so the controller loses the isolated node
  as well - that is the measured 33 s timeout in the environment facts. An
  iptables rule that drops only peer traffic would leave the controller able to
  reach the node, and the partition scenarios would then observe a node that is
  isolated from its cluster but answering the controller, which is a *different
  fault* from the one the Docker baseline recorded. So the rule set must drop the
  control-plane path as well, and the `isolated_unreachable_reason` evidence must
  be produced the same way. This is the single place where "same observable
  contract, backend's own mechanism" takes the most care, and item 1.5's
  equivalence diff is where it is proven rather than here.

### 4.3 `create_network` - the one operation with no native meaning

`create_network(network_name, capability_id, run_id)` creates a Docker network
labelled as owned by the run. A fleet described by a manifest has a network
already; the product provisions nothing, which is the roadmap's own "null
choice".

The temptation is to make this a no-op. It is not one, and treating it as one
would lose something real: `network_name` is what `isolate_nodehost` isolates
*from* and what `rejoin_nodehost` restores *into*, and the lifecycle records it on
every nodehost for exactly that reason. Under a native backend the equivalent
scope is the fleet's own data network, which the manifest describes through the
hosts' `data_address` values.

So the native `create_network` **records the run's network scope and verifies it,
rather than creating it**: it resolves the scope from the placed hosts'
`data_address` values, checks they are mutually reachable, and refuses if they
are not. That keeps the operation honest - it still establishes the fact the
fault operations depend on - and it fails a run at the right moment if a fleet
was handed to it whose hosts cannot see each other, which on a real fleet is a
security-group mistake and is exactly the kind of thing that would otherwise be
discovered as an unexplained formation failure ten minutes later.

### 4.4 `verify_image` - the bundle, and what the image string is for

`verify_image(image)` is called with `config["runtime"]["valkey_image"]` before
any host is touched, and its result is stamped on every observed node through
`_write_cluster_myslots_report`'s read of `image_preflight["valkey_server_sha256"]`.

`runtime/native_bundle.py::verify_native_bundle` already answers the bundle half
and returns that key; this item gives it its first caller. What is left is the
image string, and the honest use for it is **identity**: the Docker preflight
checks that the pinned image is the pinned build, so the native one checks that
the bundle it is about to ship is the same *version* the run's configuration
names. `valkey-scale-lab/valkey:9.1.0-myslots` yields `9.1.0`; the bundle
manifest records `valkey_version: 9.1.0`; a mismatch is a refusal. Ignoring the
string would let a run configured for one build silently ship another.

The bundle's `not_verified.cluster_myslots_command` travels into the run's
evidence unchanged. Item 1.5 owes declaring it as a vocabulary delta against the
Docker baseline, which `simulated_host_and_native_bundle_map.md` §9 already
predicted.

### 4.5 `resource_sampler`, `load_lane_host`, `reclaim_run`, `release_run`,
`client_host`

- **`resource_sampler`** must put the same `LocalResourceSampler` on the host and
  collect it once - §11.1 forbids a session per sample and that is unchanged by
  the transport. The Docker agent `docker cp`s the whole `valkey_scale_lab`
  package into the container and launches `python3 -m
  valkey_scale_lab.observability.resource_agent`. The native form ships the same
  package over the same transport and launches the same module; the simulated
  host keeps `python3` for exactly this reason, and a provisioned ECS host would
  too. Nothing about the sampler itself changes.
- **`load_lane_host`** returns an object whose `command(argv, remote_dir)` gives
  *local* argv that runs `argv` on the chosen host. Under Docker that is
  `docker exec … sh -c "mkdir -p … && exec …"`; natively it is the ssh argv with
  the same shell. `seed_host` is the address the chosen node answers on **from
  that host**, which is the host's own loopback, because memtier runs beside the
  node and follows `MOVED` on the fleet's data network. `collect_evidence` is the
  transfer measured in §2.5.
- **`reclaim_run`** is pre-run cleanup and has no state to work from - under
  Docker it is a label query. Natively the equivalent is the run-scoped path: a
  run's state root on a host is named by the run, so reclaiming is "on every host
  in the fleet, stop anything running out of this run's state root and remove
  it". That is why the state root is named by the run rather than by the node.
- **`release_run(state)`** is the end-of-run counterpart and is given the state
  mapping. Everything it needs must therefore be *in* state, which decides §6.2.
  It refuses a state that does not describe resources this run owns - the
  `4f54442a` refusal - and reports rows rather than raising for a resource that
  would not release.

  It inherits the known stale-pid defect: at cleanup, state's recorded pids are
  the bootstrap pids and the rolling restart and fault matrix have replaced every
  one of them, so under Docker `docker rm -f` is what actually stops the fleet.
  **A native backend has no such backstop.** Per the operator's decision that is
  item 1.4's to answer, and this item must not answer it silently: the native
  `release_run` implemented here does what the Docker one does and no more, and
  item 1.4 makes it terminate what is actually alive.
- **`client_host`** returns the address this process speaks RESP to. It is the
  manifest's `client_endpoint.address`, which under the harness is loopback and
  on a real fleet is the host's own address. The *port* is not part of this
  operation - the node's `client_port` is planning - which produces the check in
  §6.3.

---

## 5. Installing the bundle, and why it is `start_nodehost`'s

The run bundle's `start_all.sh` invokes bare `valkey-server`
(`docker_runtime.py:1737`). Under Docker that resolves because the pinned image
carries the binary. A manifest host does not, and item 1.0 deliberately deleted
the inherited binaries from the simulated host so that a bundle install cannot be
unfalsifiable.

So something must install the pinned bundle before `start_node_processes` runs,
and the seam has exactly one operation between claiming a host and sending the
run bundle: `start_nodehost`. Putting it there rather than inside `install_bundle`
keeps the `docker_cp_bundle` / `nodehost_bundle_install` timeline segments
measuring what they have always measured - the *run's* bundle, one per nodehost -
rather than silently including a 14 MB archive in one of them.

The install is content-addressed and idempotent: the archive is unpacked under a
path named by the bundle's own digest, and a host that already has that digest
skips the transfer. A fleet is reused across runs during development, and re-
shipping 14 MB per host per run to prove nothing is waste; skipping on a digest
match is not a cache, it is the same check `verify_native_bundle` makes, made on
the host.

The layout M3-A-1 used by hand (`/opt/valkey-scale-lab` plus symlinks into
`/usr/local/bin`) is explicitly not a contract. The mechanism chosen here is a
run-agnostic install root with the digest in the path, and `PATH` supplied to the
run bundle's scripts by the backend rather than by mutating the host's profile -
a run must not leave a host's `PATH` changed after `release_run`, which is what
"no host resource behind" means for something that is not a process.

---

## 6. Three sites above the seam that are not backend-neutral

These are what decides how much of this item fits in one session, so they are
stated with what was measured rather than as a list of chores.

### 6.1 The backend is constructed, not resolved

`_execute_runtime` opens with `backend: NodeBackend = DockerNodeBackend()` and
then branches on `if backend_id == "docker_process"` twice - once to add cluster
bus ports to the preflight list, once to choose `_create_process_scenario`.
`runtime/backends.py` is a registry with a `node_backend` factory and
`teardown.py` already uses it; the run path does not.

That is the single change that makes the registry's claim true, and it is small.
It is also where a second question surfaces: `BackendSpec.node_backend` is
`Callable[[], Any]`, which suits a Docker backend that needs nothing and does not
suit a native one that needs to know which fleet and which bundle. Teardown must
keep working from a state file alone, so the factory keeps a zero-argument form
and gains the run's runtime configuration where a run constructs it.

### 6.2 The placement join belongs to the planner, and the artifact proves it

The density planner emits `host_id` defaulted to `"local"` and `az_id` per
nodehost; the manifest carries `host_id` and `availability_zone` per host. The
join is az-to-az, and the derivation of *where* it happens is settled by an
artifact rather than by taste:

`_write_nodehost_density_plan_artifact` writes `nodehost_density_plan.json`
**before** `start_nodehost` is called - lifecycle line 188 against line 193. If
the backend performed the join, that artifact would record `host_id: "local"` for
every nodehost of a run that placed them on named hosts, which is a false
statement in the run's own evidence. So **placement is planning**, it happens in
`build_nodehost_density_plan`, and the backend is handed nodehosts that already
say where they are - the same way it is already handed nodehosts that say what
they will be called.

This also makes §4.5's `release_run` work: nodehosts go into state, so the
control endpoint a teardown needs is there without teardown reading a manifest.

The planner keeps its present behaviour when no fleet is supplied - `host_id`
stays `"local"` and every Docker run is unaffected - and the one-nodehost-per-host
refusal of §3 lives here, where the plan is validated.

### 6.3 Two lifecycle preflights are Docker-shaped

- **`_check_ports_free(ports)` binds every node port on the controller's
  loopback.** Under Docker and under the simulated harness that is correct,
  because every node port is published on `127.0.0.1`. On a real fleet the ports
  live on the hosts and the controller's loopback says nothing about them. It is
  not wrong today and it is wrong at M3-B; recorded, not changed.
- **The node ports must fall inside the host's `client_endpoint.port_range`.**
  The manifest states a contiguous range because a real host states the same
  thing as a security-group range, and the run's `cluster.port_base` is chosen by
  configuration with no knowledge of it. Nothing joins the two today. A run whose
  ports fall outside the range would form a cluster the controller cannot reach -
  precisely the failure `NodeBackend.client_host` warns about - so the placement
  check refuses it, with both the range and the requested ports named.

  This one is *found by derivation and confirmed only by a run*; item 1.5 is
  where it is confirmed.

### 6.4 The configuration contract refuses a native run

Measured, not assumed: `config/validation.py:421` errors `RUNTIME_PROVIDER` for
any `runtime.provider` other than `docker`, and `execution.py` already declares
`native_multi_ecs` with provider `ecs`. So the two halves of the product
disagree, and no configuration can currently select the backend this item builds.

This is a validation-contract change, which the working rules say to report
rather than make quietly. It is reported in §9 as the item's one semantic change,
it is the minimum that makes the item's own acceptance reachable, and it widens
rather than loosens: `docker` keeps every rule it has, and `ecs` gets its own
required fields - the fleet manifest and the bundle directory - which are errors
when absent.

---

## 7. The inventory field vocabulary, decided

The roadmap leaves this open to be closed here, locally, and sets the test:
rename only if the fields turn out **semantically wrong, not just misnamed**.

| Field | Set from | What it means | Native meaning |
|---|---|---|---|
| `container_id` | `NodehostAddress.handle` | identifies the started nodehost to the backend that started it | the run's claim on a host |
| `container_ip` | `NodehostAddress.address` | what this nodehost's processes announce to peers | the host's `data_address` |
| `container_name` | the planner | the run-scoped name of this nodehost | the run-scoped state root's name |

All three survive translation with their meaning intact. `container_ip` in
particular is *already* neutral in substance - `_process_config_text` writes it
into `cluster-announce-ip`, and it is the peer address by construction on either
backend. `container_name` is the least obvious and is the strongest case: it is
not a Docker handle at all, it is a run-scoped unique name the planner produces,
which Docker spends on a container and a native backend spends on a directory.

**Decision: keep them.** They are backend-owned handles, which is the outcome the
roadmap's own decision table names. Renaming would move `state.json`, the
`cleanup_report`, the artifact schemas and four of the five diff views, would turn
every frozen Docker baseline red on a change that means nothing, and would do it
for readability. The one cost of keeping them is that a native run's state says
`container_*` about things that are not containers; that is a naming debt, it is
recorded here, and it is not paid by a schema pass in the middle of a runtime
item.

Provisional until the implementation contradicts it. §10 records whether it did.

---

## 8. Hermetic proof, and what a fake transport can and cannot show

The item's acceptance names hermetic backend tests against a fake transport. The
seam this creates is deliberate and narrow: the backend speaks to hosts through a
`HostTransport` - run a command, put a file, get a file - and nothing else. That
is what makes the tests possible and it is also what makes the M3-B transport
switch cheap, which is the roadmap's stated condition on this decision point.

A fake transport proves: the argv the backend builds for every operation, the
record shapes it returns, the ownership and refusal paths, the placement join and
both of its refusals, the digest-skip on bundle install, and that `release_run`
reports rather than raises. Those are the parts a real fleet would prove slowly
and a fake proves exhaustively.

It cannot prove that the argv does what it says on a host. That is item 1.5's
ladder, and this map does not claim otherwise. The one thing worth doing here
that is neither is the §2 spike, which is why it was taken against real hosts.

---

## 9. What this item changes outside itself

Stated in advance so that nothing arrives as drift:

1. `runtime/backends.py` gains a `native_multi_ecs` entry and its factory learns
   the run's runtime configuration (§6.1).
2. `_execute_runtime` resolves the backend from the registry instead of
   constructing `DockerNodeBackend` (§6.1). No behaviour change for Docker.
3. `nodehost_density.py` gains optional fleet placement (§6.2). Absent a fleet,
   byte-identical output.
4. `config/validation.py` admits `runtime.provider: ecs` with its own required
   fields (§6.4). **This is the item's one validation-semantics change and the
   one thing in this map that is reported rather than merely recorded.**
5. `_process_runtime_state` writes `backend_id` and `runtime.type` as literals
   `"docker_process"`; a native run needs its own. This is the same class of
   defect `4f54442a` found in `cleanup_scenario`, in the sibling function.

No artifact schema changes, no diff-view changes, no baseline changes. Every
Docker run must be byte-identical, and that is what the Docker suite proves.

---

## 10. Result

The item landed in five commits. What follows is what the implementation said
back, including where it disagreed with this map.

### 10.1 The seam held

**Nothing in the protocol had to change to admit a second implementation.** All
twenty-three operations are implemented with their declared signatures and their
declared return shapes, and the two record shapes - `_exec_record`'s seven fields
and the actuator's two more - carried over without alteration. That is the
strongest single result here, because it was not guaranteed: a protocol with one
implementation is a description of that implementation until a second one
disagrees with it, and this one did not.

Three predictions in this map were wrong or incomplete, and each is corrected in
place above rather than left standing:

- **§6.1 understated the constructor problem.** It is not only that the run path
  builds `DockerNodeBackend()` by name; it is that teardown and a run need
  *different* construction. `cli gate cleanup` is handed a state file and no
  configuration, so the zero-argument factory has to keep working, while a run
  needs the fleet and the pinned build. `BackendSpec` therefore has two
  factories, not one with a new argument, and each has a caller that cannot use
  the other.
- **§4.2 missed that the native actuator cannot sever every path.** Docker's
  partition reaches the container through the daemon, so it can afford to detach
  the network completely. This actuator reaches the host *over* the network it is
  cutting, so a rule set with no exception could not be undone. The control port
  is spared - and it is read from the session rather than assumed, because the
  manifest's port is the forwarded one. Measured on a live host:
  `SSH_CONNECTION=[172.18.0.1 60310 172.18.0.2 22]`, so the manifest says 22200
  where the host says 22.
- **§3's port check was too wide as first written.** A nodehost's `ports` list
  mixes client and cluster-bus ports, and requiring both inside the host's
  published client range would refuse every correct configuration -
  `cluster_bus_port_base` sits ten thousand above `port_base` by convention. Only
  the client ports are the controller's business; the bus is peer traffic on the
  fleet's own network, about which a published client range says nothing.

### 10.2 §7's decision stands: the fields are misnamed, not wrong

The implementation used all three as backend-owned handles without once wanting
to mean something else. `container_ip` carries the host's `data_address` into
`cluster-announce-ip`, which is the peer address on either backend;
`container_id` carries the run's claim; `container_name` names the run-scoped
state root, which is the same run-scoped unique name Docker spends on a
container. **Keep them.** The naming debt is recorded here and is not paid by a
schema pass inside a runtime item.

### 10.3 What was measured, and what was not

Proven: `repository.all` **91/91**, from 90 - one new Test, three numbers moved.
51 hermetic checks against a fake transport. The transport spike of §2, on two
real simulated hosts.

**Not proven, and this is the honest boundary of the item:** no argv in this
backend has been run against a host *through the product*. A fake transport
proves what the backend would run; it cannot prove the host answers. The
development ladder (item 1.5) is where that is found, and §11 proposes bringing
the smallest part of it forward rather than letting a first native run be
attempted at exact-30 with every operation unexercised.

### 10.4 The Docker path, measured rather than asserted

§9 claimed every Docker run stays byte-identical. Five of this item's changes are
on a real run's path - registry-resolved backend construction, the planner's new
argument, the state builder's two literals, the guarded port preflight, and the
conditional node field - so the claim was measured on real exact-50 runs against
the frozen baseline, with the diff calibrated baseline-to-baseline first (all
five stages, every comparable view identical).

### 10.5 The two exact-50 runs

**PASS 872.72s** and **PASS 872.62s**, both 12 of 12 steps, `cleanup_report`
PASS with zero residue, and the string `ERROR` in no artifact of either.

Diffed against the frozen `exact-50-6b6f57fd` baseline, both runs identically:

| stage | mark | pass mark |
|---|---|---|
| `runtime_start` | **7/7** | 7/7 |
| `cluster_form` | **5/5** | 5/5 |
| `cleanup` | **2/2** | 2/2 |
| `management_matrix` | **6/8** | 6/8 |
| `fault_matrix` | **5/6** | 5/6 |

Both declared deltas at their declared shapes, in both runs, with no third:

- `management_matrix`: row count **1592 → 1606, exactly +14**;
  `cluster_migrate_keys` **4 → 18**; **three row kinds changed and fourteen
  unchanged**, the third being the `owned_valkey_process_remove_nodes_conf` →
  `owned_valkey_process_discard_prior_state` rename, which moves no rows. The
  sequence artifact's command ids grow by the same 14.
- `fault_matrix`: confined to `fault_sequence` and the three partition
  scenarios' isolated side - `isolated_reachable_from_this_side` and
  `isolated_unreachable_reason` added (x3), `isolated_cluster_info` no longer
  observed (x3), `isolated_cluster_state_ok` true→false (x1).

The cross-backend invariants held: **9 fault scenarios, 12 command rows, 15
workload windows** in both runs. Primary-kill RTO **47.995s** and **46.555s**,
inside the 45-50s exact-50 band.

So §9's claim is measured rather than asserted: **the Docker path is unchanged
by this item.** The diff was calibrated baseline-to-baseline first, all five
stages, every comparable view identical, so a normalisation loose enough to hide
these runs' differences would have shown up there.

---

## 11. What this item says about its own boundaries

The roadmap preconditions exit report expected item 1.2 to be the one most likely
to want splitting once its map existed. It did not need splitting to be *done* - it is
done, in one session, at its declared hard stop. But the derivation found one
genuine gap in the roadmap's sequencing, and it is worth naming rather than
letting a later session discover it:

**Between "the backend exists, hermetically proven" and item 1.5's ladder, there
is no step where a single native operation has ever touched a host through the
product.** Item 1.5 begins at a two-host exact-30 smoke, which exercises every
one of the twenty-three operations at once, on a fleet, through the full
lifecycle. A first native run that fails there gives an unhelpfully wide search
space: any of twenty-three unexercised argv, the placement, the config path, or
the fleet.

The cheap fix is a **native bring-up smoke** ahead of the ladder: bring up two
simulated hosts, and drive the backend directly - claim a host, install the
bundle, start and stop one process, isolate and rejoin, release the run - without
a Gate run, a cluster, or a scenario. It is an afternoon, it needs nothing item
1.3 or 1.4 owns, and it converts the twenty-three argv from "hermetically
correct" to "observed working". Whether it is the front of item 1.5 or a small
item 1.2b is the operator's call; the map's recommendation is the front of 1.5,
because it is the ladder's own first rung and belongs with the runs.
