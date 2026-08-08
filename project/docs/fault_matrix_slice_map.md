# Slice 4 map: `fault_matrix`

Written before moving any code, for the reason Slices 1, 2 and 3 worked: the
seam is argued from the timeline, the artifacts and a real calibration run
first, so a design surprise surfaces while it is still cheap.
`docs/runtime_start_slice_map.md` carries the accepted `NodeBackend` seam and
the rule that a timeline barrier splits an operation;
`docs/cluster_form_slice_map.md` carries §15's boundary and the rule that a
predicted operation which turns out to be inventory dissolves;
`docs/management_matrix_slice_map.md` carries the three process-lifecycle
operations and the reduced-to-verdicts view style this stage reuses.

Slice 1's surprise was that seven operations had to become nine methods. Slice
2's was that the stage had two branches with different segment sets. Slice 3's
was that four fifths of the predicted surface dissolved and that six functions
in the region were dead. This slice has five of its own, all recorded below:

1. The stage is **one timeline span at every scale, with the same shape at
   every scale** - 9 fault scenarios, 12 command rows, 15 workload windows at
   30, 50 and 200 nodes - and it is the only stage whose duration does not grow
   with scale. So the acceptance bar loses nothing to a segment branch, and
   gains an unusually strong structural check.
2. **A six-node smoke is impossible here for a measured structural reason, not
   a scale guard.** CLAUDE.md records that the product refuses this lifecycle
   below 30. That is not what the code does, and the real blocker is sharper
   and belongs to this stage - see "What stands in for the six-node smoke".
3. The stage grows the seam by **seven operations, the largest growth of any
   slice** (14 → 21), and every one of the seven is named by §15 as actuator or
   process-lifecycle surface. Three predicted operations dissolved and one
   whole scenario family - the three proxy faults - dissolved entirely.
4. **The frozen exact-50 baseline encodes the pre-`85d5096a` partition
   observation**, so a correct run legitimately differs from it in one view, in
   a shape measured across four runs. `fault_matrix` diffs **5/6 against the
   frozen baseline and 5/6 is the pass mark**, the same way `management_matrix`
   diffs 6/8. The delta is stated exactly below.
5. §9.1 fixes what an actuator must record, and **nine of the ten fault actions
   record none of it**; the tenth records it only when it succeeds. Both are
   pre-existing, neither is this slice's, and the seam is what would make them
   fixable - so the map says what the seam must return for that to stay true.

## Where the stage begins and ends

`_write_measured_lifecycle` in `gates/real.py` groups the first three lifecycle
steps by segment category and every later step by exact segment name:

```python
for step in lifecycle[3:]:
    groups[step] = [row for row in segments if row.get("name") == step]
```

`fault_matrix` is therefore exactly one setup-timeline span, opened in
`write_full_flow_artifacts` at `docker_runtime.py:7780`:

```python
with _timeline_span(setup_timeline, "fault_matrix", "fault_matrix", {"node_count": ...}):
    fault = _local_full_flow_run_fault_failover_sequence(...)
```

It begins when `management_matrix` closes and ends when `recovery` opens.
`recovery` is a *separate* span of its own - two lines that re-read
`_management_cluster_health` and staple it onto `fault["summary"]` - so the
stage boundary is clean on both sides and `recovery` is not this slice's.

Measured, `source_segments` is `["fault_matrix"]` in every run:

| Run | `fault_matrix` | `management_matrix` | Whole flow | Share |
| --- | --- | --- | --- | --- |
| frozen exact-50 baseline run-1 | 259.7s | 479.2s | 875.6s | 29.7% |
| frozen exact-50 baseline run-2 | 240.6s | 506.1s | 819.2s | 29.4% |
| exact-30, HEAD, `gate-20260808T083851Z-c2e29055` | 230.8s | 382.6s | 661.7s | 34.9% |
| exact-50, HEAD, `gate-20260808T112054Z-1d83f988` | 248.1s | 509.4s | 809.3s | 30.7% |
| exact-50, HEAD, `gate-20260808T120727Z-f5043cee` | 260.2s | 494.8s | 824.4s | 31.6% |
| exact-200, HEAD, `gate-20260808T092308Z-eee88ccb` | 215.0s | 1011.8s | 1416.9s | 15.2% |

### It does not emit different segments at different scales, and its shape is scale-flat too

`_configure_process_cluster` dispatches on `len(nodes) > 30` and its two
branches emit different segment sets; that is what forced Slice 2 to cover both
branches and cost it a hermetic test per branch. Grepping the whole region
(`docker_runtime.py:8540-9358`) for `len(nodes) >`, `scale >`, `node_count >`
and `> 30` returns nothing, and the timeline shows one span with one source
segment at 30, 50 and 200 nodes.

Slice 3 found that `management_matrix` had no branch either but *did* vary
through data, because the rolling restart's batch shape follows the density
plan. This stage does not even do that. Measured:

| Scale | Fault scenarios | Command rows | Workload windows | Sentinel canaries | Span |
| --- | --- | --- | --- | --- | --- |
| exact-30 | 9 | 12 | 15 | 15 | 230.8s |
| exact-50 | 9 | 12 | 15 | 25 | 248.1s |
| exact-200 | 9 | 12 | 15 | 100 | 215.0s |

The only number that follows scale is the Sentinel canary count, which is the
shard count and belongs to `SentinelLane`, not to this stage. Everything the
stage itself produces is a fixed 9 / 12 / 15, and its duration is dominated by
one cluster-node-timeout-driven failover (~47s RTO in every run at every
scale) plus nine bounded probes.

**Consequence for the acceptance bar.** Nothing is lost to a branch, and the
fixed shape is a strong check in its own right: any candidate that produces
other than 9 scenarios, 12 command rows and 15 windows at any scale has changed
the stage, and the views below all fail on it. What *is* lost is the cheap
smoke, for a reason peculiar to this stage - stated under "Acceptance".

## Where the code lives today

Eleven functions, 799 contiguous lines, `docker_runtime.py:8540-9358`:

| Region | Location | Lines | `run_docker` |
| --- | --- | --- | --- |
| the kill, the Sentinel/observer fault window, restart and restore, the failover observation artifact | `_run_scalable_primary_kill_failover` (8540-8811) | 272 | 1 (+1 via `_wait_container_pid_gone`) |
| stage entry, target selection, the five workload windows, the nine-scenario table, the summary | `_local_full_flow_run_fault_failover_sequence` (8814-9015) | 202 | 0 |
| per-scenario frame: event pair, command row, metric, workload window | `_local_full_flow_execute_fault_probe` (9018-9105) | 88 | 0 |
| the partition-scenario observation contract | `_local_full_flow_validate_fault_probe_observation` (9108-9150) | 43 | 0 |
| `replica_stop` | `_local_full_flow_process_pause_probe` (9153-9165) | 13 | 2 |
| `node_host_stop` | `_local_full_flow_nodehost_pause_probe` (9168-9178) | 11 | 2 |
| `az_stop` | `_local_full_flow_az_pause_probe` (9181-9194) | 14 | 2 |
| `network_delay`, `network_loss`, `network_flap` | `_local_full_flow_proxy_fault_probe` (9197-9222) | 26 | **0** |
| `network_partition`, `minority_majority`, `split_brain_detection` | `_local_full_flow_network_disconnect_probe` (9225-9334) | 110 | 3 |
| info truncation, the partition's recovery wait | `_bounded_cluster_info_excerpt`, `_local_full_flow_wait_clean_cluster_snapshot` (9337-9358) | 20 | 0 |

Nine direct `run_docker` calls, in five functions. Unlike `cluster_form` this
is not one algorithm; unlike `management_matrix` the Docker is not concentrated
in two places but spread across five - which is why it looked like the last
large concentration and why it is worth doing as one slice rather than five.

**There is no second entry point.** This is the one place where this stage is
easier than Slice 3's. `write_management_matrix_artifacts` drives the
management operation core through a standalone capability; there is no
`write_fault_matrix_artifacts`. `FAULT_MATRIX_SCENARIO` appears in
`execute_scenario`'s `docker_process` allow-list (line 601) and nowhere else -
no `_fault_matrix_profile` exists beside `_management_matrix_profile` and
`_full_flow_profile` - so the scenario id is admitted and then nothing writes
it. `gates/adapters.py:_run_fault_matrix` is a projection that records a step
result and runs no Docker. So "the old path proven removed" is a single-frame
claim here.

**But there is a second Docker actuator, and it is not in this module.**
`fault/sandbox.py` (490 lines) imports `run_docker` from `docker_runtime` and
implements fault apply/clear - process kill, container stop, restart, pid-file
removal, PING probe - reached from `cli.py fault apply` / `fault clear` and
from `compat/phase_aliases.py`. §15 names *actuator 实现* as the one thing an
adapter replaces, so after this slice there would be a `NodeBackend` actuator
and a second Docker actuator in `fault/`. That is real and it is named under
"Report, do not fix" rather than folded in: nothing in this stage calls it, no
run in the acceptance bar exercises it, and rewriting a CLI-facing module under
cover of a stage refactor is exactly the broadening the working rules forbid.

## The backend operations this stage needs beyond the fourteen

`NodeBackend` has fourteen methods: nine from Slice 1, `client_host` and
`run_cluster_admin` from Slice 2, `stop_node`, `start_node` and
`resource_sampler` from Slice 3. Derived by enumerating every `run_docker`,
`docker exec` and `run_node_*` call in the stage's line ranges, then checked
against §15 and - because this stage holds the actuator - against §9.1.

§15:

> 运行时适配器只负责替换: inventory 和 endpoint 发现; 进程启动、停止和恢复;
> **actuator 实现**; 本地资源采样器部署; 日志与证据上传。
> 保持不变: RESP 命令; `CLUSTER MYSLOTS` 契约; 三层验证逻辑; Sentinel 和
> Load Lane; 检查任务 `OK/FAIL/ERROR` 语义 …

§9.1:

> actuator 是故障动作的权威记录者，必须记录: target; action; action start;
> signal/request sent; action completed; result。
> 计划内 kill 是实验事件，不是 `FAIL`。actuator 无法实际执行故障动作属于工具
> 错误，返回 `ERROR`。

The complete Docker surface of the stage:

| Site | What it does | §15 verdict |
| --- | --- | --- |
| `_run_scalable_primary_kill_failover` | `docker exec … sh -c "kill -KILL <pid>"`, then `_wait_container_pid_gone` (`docker exec` reading `/proc/<pid>/stat`) | actuator → backend |
| `_local_full_flow_process_pause_probe` | `docker exec … sh -c "kill -STOP <pid>"` / `kill -CONT <pid>` | actuator + 进程停止/恢复 → backend |
| `_local_full_flow_nodehost_pause_probe` | `docker pause <c>` / `docker unpause <c>` | actuator → backend |
| `_local_full_flow_az_pause_probe` | the same over a list of containers | actuator → backend, same operation |
| `_local_full_flow_network_disconnect_probe` | `docker network disconnect`, `docker inspect -f …Networks`, `docker network connect --ip <ip>` | actuator → backend |
| `_local_full_flow_proxy_fault_probe` | none - an in-process host TCP proxy | **dissolves** |
| `run_node_cluster_cli` ×2 (workload SET/GET in the windows) | `docker exec … valkey-cli -c` | already `run_cluster_admin` |
| `_node_command`'s `docker exec` fallback | shared by six stages, out of scope | CLAUDE.md holds it open |

So the stage grows the seam by **seven operations**, all seven inside §15's
`actuator 实现` and `进程启动、停止和恢复`:

1. **`kill_node(node) -> list[dict]`** - terminate the owned process without
   warning and do not return until it is gone.
2. **`pause_node(node) -> list[dict]`** and
3. **`resume_node(node) -> list[dict]`** - suspend and resume one owned process
   in place, leaving it in the cluster's node table.
4. **`pause_nodehost(nodehost) -> list[dict]`** and
5. **`resume_nodehost(nodehost) -> list[dict]`** - suspend and resume a whole
   host and everything it runs.
6. **`isolate_nodehost(nodehost) -> list[dict]`** and
7. **`rejoin_nodehost(nodehost) -> list[dict]`** - remove a host from the run's
   own network and put it back where it was, confirming each took effect.

Each returns command records in `stop_node`'s shape - `command_kind`, `argv`,
`started_at_unix_ms`, `ended_at_unix_ms`, `status`, `stdout_tail`,
`stderr_tail`, `returncode` - so the lifecycle keeps owning the evidence.
That return type is not decoration; see "The evidence asymmetry" below.

### Why `kill_node` is not `stop_node` with a flag

`stop_node` sends `SHUTDOWN NOSAVE`, then `kill -TERM`, then waits. A kill
sends `kill -KILL` and waits. They share only the wait, which is internal to
the backend. Folding them would make the flag gate a Valkey command - the
graceful path asks the server to leave; the fault path must not warn it at all,
because §9.1's planned kill *is* the experiment. A flag that decides whether a
Valkey command is sent is not a parameter, it is two operations.

### Why the pause pairs do not fuse into a scope

A context manager would be neater and cannot express what the code does.
`_local_full_flow_az_pause_probe` pauses N hosts in order, observes once, then
unpauses in **reverse** order inside `finally`; and every probe must resume even
when the observation raises. This is Slice 3's stop/start argument again, with
stronger evidence: the resume is not merely non-adjacent, it is a different
arity and a different order from the pause.

### Why `pause_node` and `pause_nodehost` are not one operation

Different targets, and §15 names them under different headings: suspending one
process is 进程停止和恢复, suspending a host is actuator. Under
`native_multi_ecs` they are a signal to a process and a stop of a task - they
share nothing but a verb. Collapsing them would be an abstraction added for
symmetry, which is what the map's rule exists to prevent.

### Four predicted operations dissolved, which is the map's rule working

Mapping predicted eleven. Reading closed four, exactly as `peer_address` closed
in Slice 2 and three more closed in Slice 3:

- **A proxy fault actuator.** `network_delay`, `network_loss` and
  `network_flap` looked like the clearest actuator surface in the stage. They
  are not actuators at all: `SandboxNetworkProxy` is a pure-Python TCP proxy
  that runs **in this process on the host**, and `_local_full_flow_proxy_fault_probe`
  stands it in front of one node's client port, connects its own client through
  it, and measures what that client sees. It never touches the cluster and
  never runs a Docker command - `run_docker` count 0. What it needs from a
  backend is the endpoint to put the proxy in front of, which is
  `client_host(node)`, added in Slice 2. Three of the nine scenarios need
  nothing new.
- **A disconnect verification.** `run_docker(["inspect", "-f",
  "{{json .NetworkSettings.Networks}}", container])` asks "did the actuator
  actually act". §9.1 makes that the actuator's own business - an actuator that
  cannot act is a tool error - so it belongs *inside* `isolate_nodehost`, the
  same way confirming a process is gone is inside `stop_node`. Not a method.
- **The rejoin address.** `docker network connect --ip <nodehost_container_ip>`
  restores the address the node announces. `nodehost_container_ip` is written
  from `NodehostAddress.address` at `_process_runtime_state`, i.e. it is
  already backend-supplied inventory through the Slice 1 seam - the identical
  finding to Slice 2's `peer_address` and Slice 3's `MIGRATE` peer. A backend
  restores what it disconnected; the lifecycle passes no address.
- **The network name.** `_local_full_flow_run_fault_failover_sequence` takes
  `network_name` from `state["runtime"]["network_name"]` and threads it into the
  disconnect probe. Which network a nodehost is attached to is settled by
  `create_network`, a Slice 1 method. `isolate_nodehost(nodehost)` takes no
  network, and the `network_name` parameter leaves the stage's signature.

Two more things dissolve that were never predicted as operations but do have to
be named, because they are the "old path proven removed" test:

- **`_wait_container_pid_gone` stops being a lifecycle function.** Census by
  AST over the whole module: three call sites, two inside
  `DockerNodeBackend.stop_node` and one in `_run_scalable_primary_kill_failover`.
  Once `kill_node` owns the third, every caller is a backend method and the
  lifecycle no longer names a `/proc` reader. Same for `_safe_process_pid`: four
  call sites, two in the kill, one in `stop_node`, one inside
  `_wait_container_pid_gone`.
- **`_advertised_endpoint_resolver`** is built purely from `node["host"]` and
  `node["nodehost_container_ip"]`, both inventory since Slices 1 and 2. It needs
  nothing - the third time this exact finding has recurred.

So the seam grows by seven, not eleven. Enumerating what the regions call
rather than designing ahead of use removed a third of the predicted surface
again, and removed the family that looked most obviously like the answer.

### The evidence asymmetry the seam must not break

`management_matrix` writes **one command row per Docker command** - 212 rows at
exact-50, all produced by `stop_node`/`start_node` and recorded by the
lifecycle. `fault_matrix` does not. It writes **one row per scenario**:
`_local_full_flow_execute_fault_probe` appends a single `owned_fault_probe` row
whose `argv` is `details["actions"]`, a list of rendered command strings.
Measured, exact-50, both baselines and both HEAD runs, 12 rows in every one:

```
   9  owned_fault_probe          1  actuator_kill_primary
   1  owned_valkey_process_start 1  cluster_replicate_restored_primary
```

Once the seven operations return command records, the obvious thing is to
append them - which would turn 12 rows into ~30 and fail the diff for a reason
that has nothing to do with the refactor. **The lifecycle keeps rendering one
`owned_fault_probe` row per scenario and folds the backend's records into
`details["actions"]`, so `fault_command_log` stays 12 rows and `actions`
renders byte-identical for `DockerNodeBackend`.** That is a bar item, and the
`fault_sequence` and `fault_command_log` views are what prove it.

One ordering invariant goes with it. Today `actions` is written *before* either
call runs, so both the STOP and the CONT string are present even if the
observation raises. If `actions` is assembled from records instead, the failure
path would carry one entry rather than two. It does not matter today -
`_local_full_flow_execute_fault_probe` uses `details.get("actions", [scenario_id])`
and `details` is `{}` on the error path - but it is the kind of quiet change
that survives a green diff, so it is named here.

## What stays in the lifecycle

Everything else, and §15 names most of it explicitly.

- **The whole failover observation.** `ActuatorRecorder`, `SentinelLane`,
  `AffectedShardObserver`, `FullClusterValidator`, `redundancy_recovery`. §9.2's
  500ms affected-shard control plane, §9.3's two-round convergence rule, §9.4's
  split of failover success from redundancy recovery, §7.6's 100ms fault probe.
  §15 lists Sentinel and the three-layer verification as unchanged across
  backends. A backend kills a process; it does not observe a failover.
- **Every RESP command.** `CLUSTER INFO`, `CLUSTER MYID`, `CLUSTER REPLICATE`,
  `PING`, `ROLE`, and the partition's `_node_host_command` reads. §15: *RESP
  命令 … 保持不变*, and *不得把 Docker 特有命令带入验证层*.
- **`partition_read` and its fail-closed rule.** `85d5096a` made "unreachable
  from this side" the observation and required a recorded reason. That is
  verification logic and §12.1 semantics; it stays exactly where it is, and the
  seam must not give it a new road to an answer - see "must not entrench".
- **Target selection.** Which primary to kill, which replica to freeze, which
  nodehost and which AZ to stop, which node survives outside them. Reads
  `nodehost_container_name` and `az_id` as *where a node runs*, which is
  inventory, not a call.
- **The scenario table, the workload windows, the per-scenario frame, the
  observation contract in `_local_full_flow_validate_fault_probe_observation`,
  and the summary.** §15 puts *日志与证据上传* on the adapter; producing the
  evidence is not uploading it.
- **Verdicts.** §15 and §16 items 13-14 fix `OK/FAIL/ERROR` and
  `PASS/FAIL/ERROR`; a backend may not introduce or reinterpret one.

## Blast radius

**Tests.** 32 references to the stage's symbols across nine files - a quarter of
Slice 3's 66, because this stage is one algorithm per scenario rather than
eleven operation rows over a shared frame:

| File | Refs | What they pin |
| --- | --- | --- |
| `tests/integration/test_docker_runtime_contract.py` | 17 | `_node_host_command` (5), `_wait_container_pid_gone` (4), `_local_full_flow_wait_clean_cluster_snapshot` (3), `_local_full_flow_network_disconnect_probe` (2), `_local_full_flow_validate_fault_probe_observation` (2), `_run_scalable_primary_kill_failover` (1) |
| `tests/fault/test_network_proxy.py` | 6 | `SandboxNetworkProxy` and `ProxyRule` - untouched, since the proxy family dissolves |
| `tests/unit/test_scalable_observability.py` | 4 | `_run_scalable_primary_kill_failover`, `ActuatorRecorder` |
| `tests/real_valkey/test_exact_gate.py` | 4 | the partition probe, the observation contract, the recovery wait, `_node_host_command` |
| `tests/unit/test_full_flow_complete_matrix.py`, `tests/integration/test_full_flow_fault_command_diagnostics.py`, `tests/failover/test_full_flow_unprobed_fault_rejection.py`, `tests/failover/test_full_flow_fault_workload_measurement.py` | 1 each | `_local_full_flow_execute_fault_probe`'s frame: the scenario set, the command row, the rejection of an unprobed scenario, the workload measurement |
| `tests/failover/test_partition_group_semantics_gap.py` | 1 | `SandboxNetworkProxy` |

The four `_wait_container_pid_gone` references become tests of a backend
internal rather than a lifecycle helper, which is where the equivalent
`test_management_stop_uses_shell_builtin_for_term_fallback` already went in
Slice 3. Nothing here asserts the exact Docker argv of a *fault* action, so
unlike Slice 3 there is no argv test to move - which is itself worth saying:
the seven argvs this slice moves are pinned only by the real diff, so the
targeted hermetic tests must pin them.

**Which shared helpers are actually this stage's.** Counted by call site over
the module's AST:

| Helper | Call sites | Whose |
| --- | --- | --- |
| `_wait_container_pid_gone` | 3 | 2 in `DockerNodeBackend.stop_node`, **1 here** - the last lifecycle caller |
| `_safe_process_pid` | 4 | 2 here, 1 in `stop_node`, 1 inside `_wait_container_pid_gone` |
| `_local_full_flow_wait_clean_cluster_snapshot` | 1 | **this stage only** |
| `_bounded_cluster_info_excerpt` | 2 | **this stage only** |
| `_node_host_command` | 3 | 1 here, 2 inside `_node_response` |
| `_advertised_endpoint_resolver` | 2 | 1 here, 1 in `management_matrix` |
| `_management_matrix_start_process` | 3 | **1 here**, 2 in `management_matrix` - already on the seam since Slice 3 |
| `run_node_cluster_cli` | 6 | 2 here, 2 in `baseline_workload`, 2 in other capabilities |
| `_management_matrix_first_live_node` | 5 | 2 here, 2 in `baseline_workload`, 1 in `management_matrix` |
| `_management_wait_clean_cluster` | 8 | 3 here, 5 elsewhere |
| `_management_cluster_health` / `_management_live_topology` / `_management_topology_snapshot` | 11 / 11 / 11 | 1 / 1 / 2 here; the rest are `management_matrix`'s |
| `_node_command` | 39 | 4 here |

**Part of this stage is already on the seam.** Slice 3 threaded `backend`
through `_local_full_flow_run_fault_failover_sequence` and
`_run_scalable_primary_kill_failover` so the fault lane's recovery restart
could use `start_node` - and found that omission the hard way, at 566.77s of a
real exact-30 run, after all 91 catalog tests passed with the bug present. So
the `backend` parameter already reaches both of this stage's entry points and
one of its Docker sites; the other eight sites are in five leaf functions that
take no `backend` today. Threading it into those five is the same class of
change that produced Slice 3's latent bug, and the same check applies: after
threading, walk every free name in every touched function rather than trusting
the test suite.

The observation helpers - `_management_cluster_health`,
`_management_wait_clean_cluster`, `_management_topology_snapshot`,
`_management_live_topology` - are **not** this stage's, are pure RESP, and are
not touched.

## Should `baseline_workload` ride along?

**Yes.** Not because it is small, but because leaving it out makes this slice's
own claim untrue.

`_local_full_flow_run_baseline_workload` is 29 lines with two
`run_node_cluster_cli` calls. `_local_full_flow_run_fault_failover_sequence`
has the other two in its workload windows. `run_node_cluster_cli` is
`docker exec … valkey-cli -c`, which is exactly `run_cluster_admin`, added in
Slice 2 and used by four management call sites since Slice 3. If only the fault
lane converts, `run_node_cluster_cli` survives in the lifecycle for two calls in
the stage immediately before it, and "no Docker name survives in the stage's
regions" becomes a claim about where a line sits rather than about the
lifecycle.

Converted together, **no full-flow lifecycle stage names `run_node_cluster_cli`
any more.** The function does not reach zero references - two calls remain in
`_write_workload_workload_benchmark_artifacts` and `write_telemetry_artifacts`,
which belong to other capabilities and to other slices - so the claim is scoped
to the lifecycle, not to the module, and the map says so rather than letting a
later reader find the two survivors.

Cost: one `backend` parameter on a function that has none, one line at the call
site, and `baseline_workload`'s own view in the diff (`workload_windows`
scoped to `-baseline-`, one window at every scale). It rides along.

## The diff views this stage owns, and the calibration

Six views, all built and calibrated against
`artifacts/baselines/exact-50-6b6f57fd/run-1` versus `run-2` **and** against the
two HEAD exact-50 runs while writing this map. **All six report identical
within each pair.** They go into `STAGE_VIEWS` in
`scripts/diff_stage_artifacts.py` as the `fault_matrix` entry.

| View | Source | Normalisation beyond the shared scrub |
| --- | --- | --- |
| `lifecycle_timeline:fault_matrix` | `lifecycle_timeline.json` | none |
| `fault_sequence` | `fault_sequence.json` | measured-ms placeholder; node ids and nodehost addresses named; command ids resolved to kinds; pid-in-argv named; `CLUSTER INFO` text reduced; proxy listen port named; transport-failure reasons named |
| `fault_command_log` | `fault_command_log.jsonl` | the above, plus `stdout_tail` replaced **only** on the two row kinds whose stdout is a re-serialisation of evidence compared elsewhere |
| `failover_observation:verdicts` | `scalable_primary_failover_observation.json` | reduced to the §9.1/§9.2/§9.3/§9.4 verdicts and structural scalars |
| `topology_snapshots:fault` | `full_flow_topology_snapshots.jsonl`, rows whose `operation_id` contains `-fault-` | as `fault_sequence` |
| `workload_windows:fault` | `workload_windows.json`, `-fault-` windows, reduced to `operation_id`/`window_name`/`status`/`coverage_id`/`workload_mode` | see below |

Six things had to be named or reduced rather than dropped, and each is a
measurement made against the four runs, not a guess:

**A pid appears inside a string, not as a field.** `details["actions"]` carries
`"docker exec <c> kill -STOP 15899"`. Slice 1's `scrub` replaces `pid` as a
*key*; here it is embedded in a rendered command, so it survives and the two
baseline runs differ (15899 against 17208). The rule is `kill -<SIG> <n>` →
`kill -<SIG> <PID>`, replacing rather than dropping, so the signal itself stays
compared - and it must, because "there is no `kill` binary in the image, only
the shell builtin" is an environment fact the Docker backend has to keep. Seed
7 below proves this view catches `-KILL` becoming `-TERM`.

**Three `CLUSTER INFO` texts are live server state.** `observed_cluster_info`,
`majority_cluster_info` and `isolated_cluster_info` carry
`cluster_stats_messages_ping_sent` and every other counter, and the two frozen
baseline runs differ in all three. Worse, the *key set* differs too:
`cluster_stats_messages_update_received` and `..._fail_received` appear only
when such a message was seen, so even reducing to sorted field names does not
calibrate - measured, that reduction still reported 14 diff lines between the
baselines. What the field actually carries is two things: that a real
`CLUSTER INFO` was observed at all (the validator requires `"cluster_state:" in
…`), and what `cluster_state` said. So each is reduced to
`{"observed": bool, "cluster_state": str|null}` - the same choice Slice 3 made
for `scalable_stability_observation.json`, drawn once by what the field is.
The reduction must also record `truncated`, because `_bounded_cluster_info_excerpt`
bounds these at 1000 characters and `observed_cluster_info` keeps the **tail**:
measured lengths run 794-999 across 30, 50 and 200 nodes, so the bound is close
and a future truncation would otherwise silently drop `cluster_state`.

**The proxy's listen port is ephemeral.** `proxy_snapshot.listen_port` is
whatever the OS handed the sandbox proxy - 49612 against 51183 between the two
baselines. Named `<PORT>`, not dropped. `target_port` is the node's planned
client port and stays compared.

**A transport-failure reason is not one string.** `isolated_unreachable_reason`
and the isolated-side `client_observations[].error` record why the isolated node
could not be read, and the flavour depends on a race between a socket timeout
and an EOF. Measured across six runs: at 30 and 50 nodes `network_partition`
records `timeout('timed out')` while `minority_majority` and
`split_brain_detection` record `DockerRuntimeError("unknown RESP prefix b''")`;
at 200 nodes `network_partition` records the RESP-prefix flavour instead. Two
runs agreeing would have hidden that, which is precisely CLAUDE.md's warning.
The boundary is drawn by what the field is - evidence that the node could not
be reached, and the validator requires only that it is non-empty - so a
non-empty reason becomes `<UNREACHABLE>` and an empty one stays `""`. Appearance
and disappearance still show; which flavour of transport failure does not. The
actual texts are reported beside the diff.

**`stdout_tail` is a re-serialisation, on exactly two row kinds.** Slice 3 kept
`stdout_tail` compared in `management_command_log`, and that is how the
`CLUSTER REPLICATE` fallback anomaly was found - so blanket-dropping it here
would throw away the one field that has already caught a real regression. It
does not need blanket-dropping. In this log, `owned_fault_probe`'s `stdout_tail`
is `json.dumps(details)[-2000:]` - the same `details` dict that `fault_sequence`
compares **in full** - and `actuator_kill_primary`'s is `json.dumps(actuator_record)`,
whose contents `failover_observation:verdicts` compares. Both are truncated to
the last 2000 characters, so the truncation window itself moves when the
content grows: measured, the baseline's partition row begins mid-line at
`"\ncluster_voting_nodes_pfail:0…"`. So `stdout_tail` is replaced with
`<OBSERVATION_JSON>` **only on those two kinds**, and compared literally on
every other row - which at exact-50 means the `cluster_replicate_restored_primary`
row's `"OK"` and the `owned_valkey_process_start` row's `""` are still compared,
the two rows where Slice 3's lesson actually applies.

**Two artifacts are reduced to verdicts.** `scalable_primary_failover_observation.json`
carries 453 Sentinel samples at 100ms, 95 affected-shard rounds, 102 connection
events and a whole `FullClusterValidator` result - all live measurement.
Reduced to §9.1's actuator fields (`target`, `action`, `result`, and which of
the three stamps are present), §9.2's `interval_ms`, §9.3's
`candidate_rounds_required` / `converged_relationship` / `round_interval_ms`,
§9.4's `redundancy_recovery` and `failover_success`, the Sentinel prepare and
restore verdicts, and the recovery validation's scalars. `workload_windows.json`
is reduced to per-window verdicts for the reason Slice 3 gave. Both are
identical between the frozen runs and both still fail if a verdict flips, a
window disappears, or a §9 parameter changes - seeds 9, 10 and 11 below.

**What is reported, not diffed.** The RTO and promotion latency
(`rto_ms`, `promotion_latency_ms`, `cluster_recovery_latency_ms`,
`read/write_unavailability_ms`), the Sentinel sample and round counts, and the
isolated-side reason texts. Measured across the runs above, RTO sits at
45.5-49.0s at every scale, sample counts at 253-468 - a real recovery
measurement that no normalisation can equate, and a number a candidate must not
be allowed to change unseen. `STAGE_REPORTED` carries them, as
`runtime_all_node_light_probe` and the workload counters already do.

### Calibration plan

```bash
./scripts/diff_stage_artifacts.py --stage fault_matrix \
    artifacts/baselines/exact-50-6b6f57fd/run-1/001-real.local.full-flow/runtime \
    artifacts/baselines/exact-50-6b6f57fd/run-2/001-real.local.full-flow/runtime
```

must report **6/6 identical**, plus the reported numbers. Already measured
while writing this map: 6/6 between the two baselines, and 6/6 between the two
HEAD exact-50 runs, under the normalisation above. `runtime_start`'s seven
views, `cluster_form`'s five and `management_matrix`'s eight are re-run on the
candidate to prove the earlier slices are not regressed.

### Calibration alone is not enough: the seeded regressions

Slice 3 shipped a normalisation that calibrated perfectly and collapsed every
command reference to one token. So the views must be shown to bite. Fifteen
plausible regressions were seeded into a copy of baseline run-1 and each was
required to be caught by the view that owns it. **All fifteen were caught, none
was missed, and no seed was caught only by a view that does not own it:**

| Seeded regression | Reported by |
| --- | --- |
| 1. actuator `result` is not `OK` (it could not act) | `failover_observation:verdicts` |
| 2. actuator drops §9.1's `signal_or_request_sent` stamp | `failover_observation:verdicts` |
| 3. a partition records `disconnect_verified: false` | `fault_sequence` |
| 4. the isolated-side observation silently emptied | `fault_sequence` |
| 5. `az_stop` pauses one container instead of two | `fault_sequence` |
| 6. a fault scenario stops recording its command row | `fault_sequence`, `fault_command_log` |
| 7. the kill becomes `kill -TERM` | `fault_command_log` |
| 8. `redundancy_recovery.replicas_connected` false | `failover_observation:verdicts` |
| 9. a fault workload window disappears | `workload_windows:fault` |
| 10. §9.3's `candidate_rounds_required` weakened 2 → 1 | `failover_observation:verdicts` |
| 11. §7.6's Sentinel probe interval loosened 100 → 500ms | `failover_observation:verdicts` |
| 12. the `fault_after` topology snapshot is lost | `topology_snapshots:fault` |
| 13. `network_loss` reports client success where it must fail | `fault_sequence` |
| 14. the stage's own status flips to FAIL | `fault_sequence` |
| 15. a probe's command row is marked FAIL | `fault_command_log` |

Seeds 10 and 11 matter most: they are the two §9 parameters that a reduced view
would be most tempted to drop, and they are the reason the reduction keeps
`interval_ms`, `round_interval_ms` and `candidate_rounds_required` rather than
only the statuses.

## The expected delta against the frozen baseline: 5/6 is the pass mark

The frozen exact-50 baseline is at 6b6f57fd, which is **before `85d5096a`**.
At that commit the partition probe read the isolated node through
`_node_command`, whose `docker exec` fallback reaches straight through the
partition, so the isolated side answered `cluster_state:ok`. On HEAD it does
not, and being unreachable is the observation.

Measured, all four combinations (baseline run-1 and run-2 against HEAD run-1
and run-2), the delta is identical every time and is confined to `fault_sequence`.
Per partition scenario - `network_partition`, `minority_majority`,
`split_brain_detection`, three of the nine - and nowhere else:

| Field | frozen baseline | HEAD |
| --- | --- | --- |
| `isolated_reachable_from_this_side` | **absent** | `false` |
| `isolated_unreachable_reason` | **absent** | `<UNREACHABLE>` |
| `isolated_cluster_info` | a real `CLUSTER INFO` | `""` |
| `isolated_cluster_state_ok` | `true` / `false` / `false` | `false` in all three |
| `client_observations[isolated].success` | `true` | `false` |
| `client_observations[isolated].response` | `"PONG"` | `""` |
| `client_observations[isolated].error` | `""` | `<UNREACHABLE>` |

Nothing else moves: the majority side, the recovery observation,
`disconnect_verified`, `recovery_verified`, every action string, all six other
scenarios, and the other five views are identical. **Check that shape, not
equality: any other kind of difference, or a different set of fields, is a real
finding.** This is an intentional behaviour fix on its own evidence and its own
commit, exactly like `ded96fac`'s +14 `cluster_migrate_keys` rows, which is why
the baseline stays frozen anyway.

So `fault_matrix` is **5/6 identical plus one view showing exactly the delta
above**, and that is the pass mark for this slice.

## exact-200: not a diff item, and why

CLAUDE.md's bar requires exact-200 for `runtime_start`, `cluster_form` and
`stabilize`. `fault_matrix` is not on that list and cannot be added
retroactively, for the reason Slice 3 gave for `management_matrix`: **no
exact-200 run at 6b6f57fd reaches the fault lane.** The frozen exact-200
baseline's `BASELINE.md` records both runs stopping downstream of `stabilize`,
so neither wrote `fault_sequence.json`, `fault_command_log.jsonl` or
`scalable_primary_failover_observation.json`. exact-50 is the only baseline
that carries them.

There are passing exact-200 runs on HEAD - `gate-20260808T092308Z-eee88ccb`,
`fault_matrix` PASS 215.0s, 9 scenarios, 12 command rows, 15 windows, RTO
47215ms - but they are on HEAD, not on the frozen commit, and diffing against
them is the per-slice drift the frozen-baseline rule exists to prevent.

So the bar is: **run one real exact-200 and report its stage numbers; do not
diff them.** The stage's fixed shape makes that unusually informative: 9 / 12 /
15 must hold at 200 nodes as it does at 30 and 50, the Sentinel canary count
must be 100, and the RTO must land in the 45-49s band every run so far has
produced. A regression that shows up only at 200 nodes would move one of those.

## Acceptance for this slice

1. `./gate suite repository.all` at 91/91.
2. Targeted hermetic tests driving the stage with a recording backend while
   `run_docker` raises: one for the kill through `kill_node` including the
   actuator record and the `-KILL` argv (the argv no existing test pins); one
   for `az_stop`'s N-pause / reverse-N-resume through
   `pause_nodehost`/`resume_nodehost`, including resume-on-exception; one for
   the partition through `isolate_nodehost`/`rejoin_nodehost` asserting that
   `partition_read` still does **not** fall back to `docker exec`; and one for
   `baseline_workload` plus the fault workload windows through
   `run_cluster_admin`. The proxy scenarios need no new test - they touch no
   backend - but one test must assert that, so the dissolution is pinned rather
   than assumed.
3. **exact-30 stands in for the six-node smoke**, as it did for Slice 3, but
   for a different and sharper reason - see below. The bar is: exact-30 passes,
   one `fault_matrix` span with `source_segments == ["fault_matrix"]`, 9
   scenarios, 12 command rows, 15 windows, zero residue. It is a behaviour
   smoke and not a diff; exact-30 has no frozen baseline and must not acquire
   one.
4. Real exact-50 against `artifacts/baselines/exact-50-6b6f57fd`, **5 of 6
   views identical against run-1 and against run-2, with `fault_sequence`
   showing exactly the delta shape above and nothing else**, plus the reported
   RTO, sample counts and reason texts.
5. `runtime_start`, `cluster_form` and `management_matrix` not regressed: 7 of
   7, 5 of 5, and 6 of 8 with `management_matrix`'s own known +14
   `cluster_migrate_keys` delta unchanged.
6. Real exact-200, stage numbers reported and not diffed, per the section above.
7. The old path proven removed: no `run_docker`, no `docker exec` string, no
   `docker pause`/`network disconnect` argument construction and no
   `nodehost_container_name`-as-a-container-argument survives in any of the
   eleven functions, checked by walking the module's AST rather than grepping
   the file - the check Slice 3 used. `_wait_container_pid_gone` and
   `_safe_process_pid` must have no remaining lifecycle caller. No fallback, no
   duplicate implementation.
8. `details["actions"]` renders byte-identical for `DockerNodeBackend`, and
   `fault_command_log` is still 12 rows at every scale.
9. Add the `fault_matrix` entry to `STAGE_VIEWS` (and its reported rows to
   `STAGE_REPORTED`) in `scripts/diff_stage_artifacts.py`, calibrate it run-1
   against run-2 at 6 of 6, and re-run the fifteen seeded regressions before
   using it on a candidate.

Then stop and report. The baselines stay frozen at 6b6f57fd; do not
re-baseline.

### What stands in for the six-node smoke, and the measured reason

CLAUDE.md records that "both the gate and the product refuse fewer than 30
nodes for this lifecycle". Checked rather than assumed, and it is half right.

The **gate** does refuse: `real.local.full-flow` declares
`"nodes": {"type": "integer", "minimum": 30, "maximum": 200}` in
`catalog.json`, so six cannot be requested through `./gate test`.

The **product does not**. `PROFILES["small-real"]` is six nodes,
`_full_flow_profile("local_full_flow", "local_full_flow", 6)` returns it rather
than `None`, `execute_scenario` admits `docker_process` + `small-real`, and
`write_full_flow_artifacts`'s only scale guard is
`len(nodes) != profile.requested_nodes`, which six satisfies. There is no
node-count guard anywhere in `_local_full_flow_run_management_sequence` or
`_local_full_flow_run_fault_failover_sequence`. So the six-node call is legal
and would reach this stage.

It would then fail, and this stage is where it fails. Measured by running the
density planner on the shipped configs:

```
templates/configs/single_mac_6node.yaml   6 nodes -> 2 nodehosts, both az-local
templates/configs/scale_30.yaml          30 nodes -> 4 nodehosts, az-a and az-b
```

`single_mac_6node.yaml` declares `virtual_az_mode: single` and `azs: [az-local]`,
so every node's `az_id` is `az-local`. The stage's target selection
(`docker_runtime.py:8957-8961`) then does:

```python
az_nodehosts = sorted({... for node in nodes if str(node.get("az_id")) == target_az})
survivor = next(node for node in nodes if str(node.get("nodehost_container_name")) not in set(az_nodehosts))
```

With one AZ, `az_nodehosts` is every nodehost and no node is outside it, so
`survivor` raises `StopIteration` - **`az_stop` structurally requires a node
outside the target AZ, and the shipped six-node config has no second AZ.** It
raises after `primary_failover` has already run and before any of the nine
scenarios, so a six-node run would produce a partial stage and no
`fault_sequence.json`.

Two consequences. First, exact-30 is the smallest real run that exercises this
stage, and the bar uses it. Second, this is a finding in its own right and it is
**reported, not fixed**: it is not a refactor's business to invent a two-AZ
six-node config, and the raw `StopIteration` - not a `DockerRuntimeError` -
would surface as an unattributed failure rather than a stated one. Named here
so the bar's shape is a decision rather than an omission.

## Dead code in the stage's region

One function, `_partition_fault_matrix_process_nodehosts` (39 lines,
`docker_runtime.py:1444`), has exactly one occurrence in the whole repository -
its own definition - and no test reference. It is a nodehost placement planner
for the `fault_matrix` scenario, splitting nodes into a minority and two
majority groups.

It is **not** a second implementation of what this slice extracts, the way
Slice 3's `_management_log_docker_command` and `_management_make_primary_safe`
were, and it does not sit in the stage's contiguous region - it lives with the
placement planners at line 1444. So removing it is not required by bar item 7.
It should still go with this slice, because it names this stage, nothing else
will ever claim it, and a dead partition planner beside a live partition probe
invites a later reader to call it.

A repo-wide scan for zero-reference top-level functions in `docker_runtime.py`
found thirteen, 176 lines in total. The other twelve belong to `cluster_form`,
telemetry and `management_matrix` and are not this slice's; they are listed
here only so the next slice does not have to re-derive them:
`_is_failover_latency_exact_200_runtime_exception`, `_wait_process_integrated`,
`_meet_new_node`, `_wait_cluster_known_at_least`, `_wait_host_probe_ready`,
`_ensure_replica_of`, `_wait_replica_of`, `_telemetry_cluster_nodes_metric_rows`,
`_local_full_flow_load_jsonl`, `_management_matrix_skipped`,
`_management_diff_from_health`, `_add_slots`.

## Known items the slice must not entrench

All of these are recorded in CLAUDE.md and none is this slice's to fix. What
matters here is that the seam does not make any of them harder to fix later.

- **`_node_response`'s `docker exec` fallback for transport failures.** §16.2
  forbids it and CLAUDE.md holds it open. The seam must not build a second road
  to it: `partition_read` deliberately uses `_node_host_command`, which has no
  fallback, and that stays. The seven new operations are actuator calls, not
  Valkey reads, so none of them can reach it. The one thing the slice must not
  do is let a backend method fall back to a Valkey read to decide whether its
  action worked - `isolate_nodehost` confirms with `docker inspect`, which is a
  runtime question, not a protocol one.
- **Whole-fleet cadence, and the rolling restart's whole-fleet `CLUSTER NODES`.**
  This stage is a heavy fleet consumer today - three `_management_wait_clean_cluster(nodes)`
  calls at 1 Hz, one `_local_full_flow_wait_clean_cluster_snapshot(nodes)`, two
  whole-fleet topology snapshots, one `_management_live_topology(nodes)`, one
  `_management_cluster_health(nodes)` and three `FullClusterValidator` runs. All
  of it is pre-existing and none of it is this slice's. **The seven new
  operations are all per-node or per-nodehost and add no fleet-wide read**, and
  the slice adds no new caller of `_management_wait_clean_cluster`. The
  `fault_command_log` and `failover_observation:verdicts` views would show it if
  it did.
- **The `MISSING` semantics paired with the FAIL-to-ERROR verdict mapping.**
  The seam does not touch `_management_live_topology`, which stays in the
  lifecycle unchanged. `kill_node` and the six pause/isolate operations **raise**
  on failure and the lifecycle's existing error path handles them; none of them
  reports a backend failure as a node observation, so no new road to `MISSING`
  is built. This matters more here than it did in Slice 3, because §9.1 is
  explicit that an actuator which cannot act is `ERROR` and not `FAIL`, and the
  next item is exactly that gap.
- **`_execute_runtime`'s exception handler reads unbound names** and **whether
  the pre-drain reshard stranded keys** - neither is reachable from this stage.

## Report, do not fix

Seven things this map surfaced and deliberately leaves alone.

- **Nine of the ten fault actions record no actuator evidence at all.** §9.1
  requires target, action, action start, signal/request sent, action completed
  and result for a fault action. `ActuatorRecorder` is constructed in exactly
  one place - `_run_scalable_primary_kill_failover` - and the nine
  `owned_fault_probe` scenarios record only a free-text `actions` list and one
  command row. This is a contract gap, and CLAUDE.md's working rules say to
  report before a semantic change to a validation contract, so it is not folded
  in. **The seam is what would make it fixable:** the seven operations return
  command records with start and end stamps and a result, which is precisely an
  `ActuatorRecorder`'s raw material, so a later change wraps each scenario's
  backend call rather than reaching for Docker again.
- **When the actuator cannot act, nothing at all is recorded.**
  `ActuatorRecorder.complete()` raises `CollectionError` when `result != "OK"`,
  and it is called *before* `command_log.append(...)` at
  `docker_runtime.py:8632`. So the one row that carries the actuator record is
  written only on success, and §9.1's `result` - the field that exists to
  describe the failure - is never persisted on the path where it matters. The
  row's `"status"` is a literal `"PASS"` for the same reason. Worse for the
  verdict: the raised `CollectionError` propagates out of
  `write_full_flow_artifacts` and the gate reports the run FAIL, where §9.1 and
  §12.1 both say a tool error is `ERROR`. That is the same FAIL-vs-ERROR
  correction CLAUDE.md already holds open for `MISSING`, at a second site, and
  it belongs with it: pairing an observation fix with its verdict mapping is
  what makes the correction whole.
- **`fault/sandbox.py` is a second Docker actuator**, 490 lines, importing
  `run_docker` from this module, reached from `cli.py fault apply` /
  `fault clear` and from `compat/`. §15 makes the actuator the one thing an
  adapter replaces, so after this slice there are two. Nothing in this stage
  calls it and nothing in the acceptance bar exercises it. Named here so it is
  a known limitation of "the old path proven removed" rather than a discovery
  later.
- **`_local_full_flow_proxy_fault_probe` hardcodes `target_host="127.0.0.1"`.**
  This is the last of the five loopback defaults Slice 2 found and left to the
  stages that own them; Slice 3 did not remove it because it is not
  `management_matrix`'s. It is a literal, not a `node.get("host", …)` default
  arm, and `client_host(node)` has existed since Slice 2. It is one call site in
  this stage's own region and it is inventory, not a new operation, so it is
  small enough to fold into this slice and it should be - but it changes a
  value the `fault_sequence` view compares (`target_port` stays, the host is not
  recorded), so it is named here rather than made silently. The four remaining
  `node.get("host", "127.0.0.1")` arms are in `_management_cluster_nodes_contains`,
  `_management_wait_node_role`, `_management_reshard_node_owns_slot` and
  `_management_reshard_primary_owned_slots` - all `management_matrix`'s, all
  reading a real value now, and not this slice's.
- **`survivor` selection raises `StopIteration`, not `DockerRuntimeError`.**
  Two selections in this stage (`survivor` at 8961 for the AZ probe, and the
  disconnect probe's `target`/`survivor` at 9228-9229) use bare `next()` over a
  generator with no default. When the topology cannot satisfy them - the
  single-AZ six-node case above is one - the failure surfaces as an
  unattributed `StopIteration` rather than a stated reason. Its own change, on
  its own evidence.
- **`observability/load.py` builds its own `docker exec` wrapper**, unchanged
  since Slice 3 recorded it. This stage declines the Load Lane entirely
  (`load_not_applicable`, on the measured ground that memtier stops issuing
  operations for good once an endpoint disappears), so it does not even supply
  the container the way `management_matrix` does. Not this slice's.
- **`_local_full_flow_wait_clean_cluster_snapshot` and
  `_management_wait_clean_cluster` are two different clean-cluster waits**, used
  by different scenarios in the same stage: the three pause probes use the
  latter at 1 Hz over every node, the partition probe uses the former, which is
  one `_wait_process_snapshot_clean`. Both are pure RESP and neither is backend
  surface, so the seam does not touch them - but that one stage waits for the
  same condition two ways is worth someone's measurement, and it is not this
  slice's.
