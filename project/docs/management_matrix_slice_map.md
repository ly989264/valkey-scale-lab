# Slice 3 map: `management_matrix`

Written before moving any code, for the reason Slices 1 and 2 worked: the seam
is argued from the timeline, the artifacts and a real calibration run first, so
a design surprise surfaces while it is still cheap.
`docs/runtime_start_slice_map.md` carries the accepted `NodeBackend` seam;
`docs/cluster_form_slice_map.md` carries the two operations it grew and the rule
that produced them.

Slice 1's surprise was that seven operations had to become nine methods, because
fusing a pair would erase a timeline segment. Slice 2's was that the stage had
two branches with different segment sets, and that §15 already fixed most of the
answer. This slice has four of its own, all recorded below:

1. The stage is **one timeline span at every scale**, so the segment-branch
   problem that complicated Slice 2's bar does not exist here — but the acceptance
   bar loses its cheapest instrument in exchange, because a six-node smoke cannot
   reach the stage at all.
2. The stage's Docker surface is **196 lines of ~3,400** (277 counting the
   planning around them), and it is exactly the two things §15 names: process
   stop/start, and local sampler deployment. Everything else that looked like a
   candidate dissolved on reading.
3. **Six functions totalling 167 lines in the stage's region are dead**, and two
   of them are older duplicates of the code this slice is about. They would
   survive the slice as a second implementation of the seam unless the slice
   removes them.
4. The stage's artifacts break the diff tool's shared normalisation in a way no
   earlier stage did: `wall_ms` and `*_at_ms` are not in `IGNORED`, node ids
   appear as **dict keys** and not only as values, and the workload counters are
   genuinely non-deterministic. All four were measured against the frozen
   baseline while writing this map, and the calibration below is the result.

## Where the stage begins and ends

`_write_measured_lifecycle` in `gates/real.py` groups the first three lifecycle
steps by segment category and every later step by exact segment name:

```python
for step in lifecycle[3:]:
    groups[step] = [row for row in segments if row.get("name") == step]
```

`management_matrix` is therefore exactly one setup-timeline span, opened in
`write_full_flow_artifacts`:

```python
with _timeline_span(setup_timeline, "management_matrix", "management_matrix", ...):
    management = _local_full_flow_run_management_sequence(...)
```

It begins when `baseline_workload` closes and ends when `fault_matrix` opens.
`local_full_flow_v1.json` states the same order as a dependency chain
(`stabilize → baseline_workload → management_matrix → fault_matrix`).

Measured, `source_segments` is `["management_matrix"]` in every run, and the
stage is the largest single step in the flow:

| Run | `management_matrix` | Whole flow | Share |
| --- | --- | --- | --- |
| frozen exact-50 baseline run-1 | 479.2s | 875.6s | 55% |
| frozen exact-50 baseline run-2 | 506.1s | 819.2s | 62% |
| exact-30, HEAD, `gate-20260808T001341Z-f02ab933` | 398.6s | 684.3s | 58% |
| exact-200, HEAD, `gate-20260808T021925Z-0078a747` | 992.2s | 1387.0s | 72% |

### It does not emit different segments at different scales

`_configure_process_cluster` dispatches on `len(nodes) > 30` and the two branches
emit different segment sets; that is what forced Slice 2 to cover both branches.
This stage has no such dispatch. Grepping the whole region for `len(nodes) >`,
`node_count >` and `> 30` returns nothing, and the timeline shows one span with
one source segment at 30, 50 and 200 nodes.

What *does* vary with scale is the rolling restart's batch shape, and it varies
through data rather than through a branch. `_management_matrix_rolling_restart_batches`
fills a batch with entries of one role whose shards and nodehosts are all
distinct, capped at `ROLLING_RESTART_MAX_PARALLELISM = 8`:

| Scale | Batches per operation | Max concurrent | Observed batch sizes | Restart rows |
| --- | --- | --- | --- | --- |
| exact-30 | 8 | 4 | 3, 4 | 60 |
| exact-50 | 14 | 4 | 1, 4 | 100 |
| exact-200 | 26 | 8 | 4, 8 | 400 |

The cap is a constant; what actually limits the batch at 30 and 50 is the
**nodehost count**, because a batch may not restart two nodes on one nodehost.
So the batch shape is a function of the density plan the backend's placement
produced, not of a scale branch in this stage.

**Consequence for the acceptance bar.** Only one thing is lost relative to
Slice 2, and it is not the branch problem: it is that the smallest run which
exercises the stage at all is exact-30, so the cheap six-node smoke that closed
both earlier slices' behaviour question is unavailable. `real.local.full-flow`
declares `"nodes": {"type": "integer", "minimum": 30, "maximum": 200}` in
`catalog.json`, so the gate will not accept six; CLAUDE.md records that the
product refuses this lifecycle below 30 as well. What stands in for the smoke is
stated under "Acceptance" below.

## Where the code lives today

| Region | Location | Lines |
| --- | --- | --- |
| stage entry, per-operation loop, evidence bookkeeping, bounded-stability lane | `_local_full_flow_run_management_sequence` | 205 |
| workload windows around each operation, the `event` window that overlaps it | `_management_matrix_run_operation_with_workload` | 124 |
| operation dispatch, before/after health and topology, the result row | `_management_matrix_execute_operation` | 162 |
| rolling restart: plan, batches, handoff, restart, restore, gates, rows | `_management_matrix_execute_process_rolling_restart` + 8 helpers | 610 |
| remove-and-restore (`add_replica`, three `remove_*` rows) | `_management_matrix_remove_and_restore_row`, `_management_forget_until_absent`, `_management_matrix_rejoin_as_replica` | 111 |
| reshard and rebalance | `_management_reshard_*`, 11 functions | 293 |
| health, topology and role observation shared with later stages | `_management_cluster_health`, `_management_live_topology`, `_management_wait_clean_cluster`, `_management_wait_node_role`, `_management_topology_snapshot` | 182 |
| evidence recording | `_management_log_node_command`, `_management_matrix_log_docker_exec`, `_management_matrix_log_health_probe_summary`, `_management_matrix_merge_parallel_command_rows` | 134 |
| **owned process stop and start** | `_management_matrix_stop_process`, `_management_matrix_start_process`, `_wait_container_pid_gone` | **104** |
| **local resource sampler deployment** | `NodehostResourceAgent`, `_resource_runners_for_nodes`, `_watch_expected_gone_active` | **173** |
| observation-lane wiring for bounded stability | `_advertised_endpoint_resolver`, `_load_lane_seed` | 39 |
| artifact writers | `_write_management_matrix_cluster_plan`, `_write_management_matrix_run_state`, `_management_matrix_rolling_plan`, coverage ledger | 175 |
| a second, separate driver of the same operations | `write_management_matrix_artifacts` | 256 |

Unlike `runtime_start`, the stage is not pre-factored into helpers that map onto
backend operations. Unlike `cluster_form`, it is not one algorithm either: it is
eleven operation rows over a shared verification frame, and the Docker in it is
concentrated in two places rather than spread through it.

**There is a second entry point.** `write_management_matrix_artifacts` runs the
same `MANAGEMENT_MATRIX_EXECUTION_ROWS` through the same
`_management_matrix_run_operation_with_workload` for the standalone
`management_matrix/management_matrix` capability, without the bounded-stability
lane and with its own artifact set. It has no registered real gate test —
`catalog.json` carries only `product.artifacts.management_matrix`, a fixture
test — and no baseline covers its artifacts. It is reachable through
`execute_scenario` and the legacy aliases in `compat/`. Because it shares the operation
core, the seam reaches it whether or not the slice intends that, and "the old
path proven removed" is not met if the standalone driver keeps a Docker path of
its own.

## The backend operations this stage needs beyond the eleven

`NodeBackend` has eleven methods today: nine from Slice 1, plus `client_host`
and `run_cluster_admin` from Slice 2. Derived by enumerating what the regions
above actually reach — every `run_docker`, `docker exec` and `run_node_*` call
in the stage's line ranges — and then checked against §15:

> 运行时适配器只负责替换: inventory 和 endpoint 发现; 进程启动、停止和恢复;
> actuator 实现; 本地资源采样器部署; 日志与证据上传。
> 保持不变: RESP 命令; `CLUSTER MYSLOTS` 契约; 三层验证逻辑; Sentinel 和
> Load Lane; 检查任务 `OK/FAIL/ERROR` 语义 …

The complete Docker surface of the stage is:

| Site | What it does | §15 verdict |
| --- | --- | --- |
| `_management_matrix_stop_process` | `docker exec … valkey-cli -p P SHUTDOWN NOSAVE`, then `docker exec … sh -c "kill -TERM <pid>"` | 进程停止 → backend |
| `_wait_container_pid_gone` | `docker exec … sh -c` reading `/proc/<pid>/stat` | 进程停止 → backend |
| `_management_matrix_start_process` | `docker exec … rm -f <data_dir>/nodes.conf`, `docker exec … valkey-server <config>`, `docker exec … cat <pid_file>` | 进程启动和恢复 → backend |
| `NodehostResourceAgent.start/stop/mark` | `docker cp` the package and a spec, `docker exec` to launch, stop and collect a long-lived sampler | 本地资源采样器部署 → backend |
| `run_node_cluster_cli` ×4 | `docker exec … valkey-cli -c` for the workload SET/GET and the reshard key seed/read/write checks | already `run_cluster_admin` |
| `_management_log_docker_command` | `run_docker` evidence wrapper | **dead, zero callers** |
| `_node_response`'s fallback | `docker exec valkey-cli` on any exception | shared by six stages, out of scope |

So the stage grows the seam by **three operations**, all three named verbatim in
§15's list of what an adapter replaces:

1. **`stop_node(node, *, command_kind) -> list[dict]`** — stop the owned Valkey
   process on `node` and do not return until it is gone. The backend owns the
   mechanism (SHUTDOWN, the signal fallback, the liveness check) and returns the
   command rows it produced; the lifecycle owns when to stop and what the stop
   means. `/proc` is the reason this cannot stay in the lifecycle: there is none
   on Darwin, and there is none on an ECS control plane either.
2. **`start_node(node, *, fresh_cluster_identity: bool) -> int`** — start the
   owned process, discarding its cluster identity first when asked, and report
   the pid it is now running under.
3. **`resource_sampler(nodehost_handle, *, sampler_id, processes, expected_gone)
   -> ResourceSamplerRunner`** — deploy and collect the long-lived local sampler
   that §11.1 requires (host metrics every 5s, process metrics every 60s, no
   `docker exec` per sample). `_resource_runners_for_nodes` keeps the planning —
   grouping nodes by nodehost, building `ProcessSpec`s, deciding there is nothing
   to sample when identity is incomplete — and calls the backend once per
   nodehost.

### Why 1 and 2 do not fuse into `restart_node`

Slice 1's rule for splitting was a timeline barrier. There is no timeline
segment inside this span to appeal to, so the evidence is different and stronger:
the two calls are **not adjacent at two of the three call sites**.
`_management_matrix_restart_process_target` does call them back to back, but
`_management_matrix_remove_and_restore_row` stops the target, runs
`CLUSTER FORGET` against every survivor until the node is absent and the cluster
is clean again — a wait bounded at 120s — and only then starts it. A fused
`restart_node` could not express that, and the `remove_*` rows are four of the
eleven operations. `_run_scalable_primary_kill_failover` in the fault lane calls
`_management_matrix_start_process` with no matching stop at all.

### Why `fresh_cluster_identity` is a flag and not a fourth operation

The `rm -f nodes.conf` is only correct while the process is stopped, and only
the backend knows where that file physically is. Making it a separate call would
put an ordering invariant the backend must enforce into the lifecycle's hands.
As a flag it still produces its own `owned_valkey_process_remove_nodes_conf`
command row, so the evidence the diff compares is unchanged either way — which
is why this is a judgement rather than a measurement, and the command-log view
below is what confirms it.

### Three predicted operations dissolved, which is the map's rule working

Mapping predicted three more. Reading closed all three, exactly as
`peer_address` closed in Slice 2:

- **A cluster-network client.** The workload's `cluster_command`, the reshard
  key seed, and the two reshard verification reads all go through
  `run_node_cluster_cli`, which is `docker exec … valkey-cli -c`: a client that
  follows a `MOVED` to an unroutable address. That is precisely
  `run_cluster_admin`, added in Slice 2 for the same reason at two other call
  sites. Four call sites move onto an existing method; no method is added.
- **A peer address for `MIGRATE`.** `_management_reshard_move_slots` passes
  `target["container_ip"]` as the address the source node uses to reach the
  target. `container_ip` is written from `NodehostAddress.address` at
  `_process_runtime_state`, i.e. it is already backend-supplied inventory
  through the Slice 1 seam — the identical finding to Slice 2's `peer_address`.
- **A load-lane execution site.** `_load_lane_seed` returns
  `nodes[0]["container_name"]` plus loopback and the seed's port. For a process
  node `container_name` *is* the nodehost container name (both are written from
  `nodehost["container_name"]`), so this too is inventory the backend already
  supplies. `MemtierLoadLane` builds its own `docker exec` wrapper inside
  `observability/load.py`; that is a real §15 problem, and it is not this
  stage's — see "Report, do not fix".

`_advertised_endpoint_resolver` is the same story once more: it is built purely
from `node["host"]` and `node["nodehost_container_ip"]`, both already inventory
since Slices 1 and 2. It needs nothing.

So the seam grows by three, not six. Enumerating what the regions call rather
than designing ahead of use removed half the predicted surface again.

## What stays in the lifecycle

Everything else, and §15 names most of it explicitly.

- **Every RESP command and the whole verification frame.** `CLUSTER FAILOVER`,
  `CLUSTER FAILOVER TAKEOVER`, `CLUSTER FORGET`, `CLUSTER SETSLOT`, `MIGRATE`,
  `CLUSTER MEET`, `CLUSTER REPLICATE`, `CLUSTER MYID`, `INFO replication`,
  `ROLE`. §15: *RESP 命令 … 三层验证逻辑 … 保持不变*, and *不得把 Docker 特有
  命令带入验证层*.
- **The three-layer observation.** `_management_cluster_health` and
  `_management_live_topology` are `LightClusterProbe` over `CLUSTER MYSLOTS` +
  `CLUSTER INFO` + `ROLE` — layer 1, §4. `_management_removed_absent` reads
  `CLUSTER SHARDS` from three fixed observers — layer 2, §6.1. The bounded
  stability window is `StabilityWindow` over the light probe, `SentinelLane` and
  `MemtierLoadLane` — §7, §8, §10. §17 allows the RESP client's internals to be
  an implementation choice; it does not allow a new collection layer.
- **The rolling restart plan and batching.** Live-role ordering, shard and
  nodehost disjointness, the batch cap. It reads `nodehost_container_name` as
  *which host a node runs on*, which is inventory, not a call.
- **The safety algorithm.** Sync-then-failover before restarting a primary,
  failover back to restore placement, and the placement signature that judges it.
- **All evidence construction.** The command log, the topology snapshots, the
  workload windows, the restart rows, the result rows, the `MISSING` encoding.
  §15 puts *日志与证据上传* on the adapter; producing the evidence is not
  uploading it, and the diff views below are what would notice the difference.
- **Verdicts.** §15 and §16 items 13–14 fix `OK/FAIL/ERROR` and `PASS/FAIL/ERROR`;
  a backend may not introduce or reinterpret one.

## Blast radius

**Tests.** 66 references to the stage's symbols across six files:

| File | Lines referencing | What they pin |
| --- | --- | --- |
| `tests/integration/test_rolling_restart_scaling.py` | 29, over 11 tests | batching, live-role planning, handoff/restore, sync gate, probe scope and counts, placement signature |
| `tests/integration/test_docker_runtime_contract.py` | 22 | `_wait_container_pid_gone`, `_management_matrix_log_docker_exec`, `_management_matrix_stop_process`, `_management_wait_clean_cluster`, `_management_forget_until_absent`, `_management_log_forget_removed_node`, `_write_management_matrix_cluster_plan` |
| `tests/stability/test_full_flow_bounded_stability.py` | 4 | the stability lane and the operation row set |
| `tests/stability/test_full_flow_management_workload_overlap.py` | 4 | the `event` window overlaps the operation |
| `tests/unit/test_full_flow_complete_matrix.py` | 4 | operation → scenario mapping |
| `tests/stability/test_full_flow_management_workload_impact_status.py` | 3 | workload errors mark the row |

One test asserts the exact Docker argv the seam moves:
`test_management_stop_uses_shell_builtin_for_term_fallback` requires
`["exec", "nodehost-a", "valkey-cli", "-p", "7000", "SHUTDOWN", "NOSAVE"]` then
`["exec", "nodehost-a", "sh", "-c", "kill -TERM 101"]`. It exists because the
image ships no `kill` binary, only the shell builtin — an environment fact the
`DockerNodeBackend` implementation must keep, so this test moves to the backend
rather than being deleted. `_wait_container_pid_gone`'s three references and
`_management_matrix_log_docker_exec`'s one move with it.

**Which shared helpers are actually this stage's.** Counted by call site:

| Helper | Call sites | Whose |
| --- | --- | --- |
| `_load_lane_seed` | 1 | **this stage only** |
| `_resource_runners_for_nodes` | 2, one of them behind the parked M2 env gate | **this stage's, in practice** |
| `_management_matrix_log_docker_exec` | 4 | **this stage only** |
| `_management_matrix_stop_process` | 2 | **this stage only** |
| `_management_matrix_start_process` | 3 | 2 here, 1 in `_run_scalable_primary_kill_failover` (fault) |
| `_wait_container_pid_gone` | 3 | 2 here, 1 in the fault lane |
| `_advertised_endpoint_resolver` | 2 | 1 here, 1 in the fault lane |
| `_management_matrix_first_live_node` | 5 | 1 here, 2 in `baseline_workload`, 2 in the fault lane |
| `_management_cluster_health` | 10 | 6 here, 1 in `recovery`, 1 in the fault lane, 2 in reshard |
| `_management_wait_clean_cluster` | 9 | 4 here, 1 in `stabilize`, 4 in the fault lane |
| `_management_topology_snapshot` | 10 | 6 here, 4 in the fault lane |
| `_representative_nodes` | 11 | 2 here; the rest belong to `cluster_form` and `stabilize` |
| `_process_node_snapshots_parallel` | 7 | 2 here; 5 in `cluster_form`/`stabilize` |
| `run_node_cluster_cli` | 10 | 4 here, 2 in `cluster_form`/M2, 2 in `baseline_workload`, 2 in the fault lane |

The three operations this slice adds sit under helpers the stage owns outright
or nearly so: `stop_node` and the sampler are this stage's alone; `start_node`
and `_wait_container_pid_gone` are shared with exactly one fault-lane call site,
which converts with them because there is one implementation and no fallback.
The observation helpers — `_management_cluster_health`,
`_management_wait_clean_cluster`, `_management_topology_snapshot`,
`_representative_nodes` — are **not** this stage's, are pure RESP, and are not
touched.

**Command-log rows.** At exact-50 the stage writes 1,592 command rows, of which
**212 are `docker` rows** and 1,380 are RESP:

```
   950  cluster_setslot_node            104  owned_valkey_process_start
   196  cluster_forget_removed_node     100  owned_valkey_process_restart_stop_shutdown_nosave
    50  cluster_failover_before_primary_restart    4  owned_valkey_process_stop_shutdown_nosave
    50  cluster_failover_restore_primary_placement 4  owned_valkey_process_remove_nodes_conf
```

Every one of the 212 comes from `stop_node`/`start_node`, and every one is
compared by the command-log view below. **The backend must return its command
rows rather than swallow them**, which is why `stop_node` and `start_node` are
specified as returning rows and why `_management_matrix_restart_process_target`
already collects them into a local list before merging (it runs under
`_bounded_parallel`, so the backend calls must also be safe to run concurrently
across nodes).

## The diff views this stage owns, and the calibration

Eight views, all built and calibrated against
`artifacts/baselines/exact-50-6b6f57fd/run-1` versus `run-2` while writing this
map. **All eight report identical** under the normalisation below. They go into
`STAGE_VIEWS` in `scripts/diff_stage_artifacts.py` as the `management_matrix`
entry, and the calibration is re-run before any candidate is judged.

| View | Source | Normalisation beyond the shared scrub |
| --- | --- | --- |
| `lifecycle_timeline:management_matrix` | `lifecycle_timeline.json` | none |
| `rolling_restart_plan` | `rolling_restart_plan.json` | measured-ms placeholder; `probed_node_ids` sorted; node ids named |
| `rolling_restart_results` | `rolling_restart_results.jsonl` | the above, plus pid and replication-offset placeholders |
| `management_sequence` | `management_sequence.json` | the above, plus node ids named **in dict keys**, plus `workload_impact` counters reduced |
| `management_command_log` | `management_command_log.jsonl` | the above, plus nodehost addresses named |
| `topology_snapshots:management` | `full_flow_topology_snapshots.jsonl`, rows whose `operation_id` names a management operation | the above |
| `workload_windows:management` | `workload_windows.json`, management-scoped windows, reduced to `operation_id`/`window_name`/`status`/`coverage_id`/`workload_mode` | see below |
| `stability_observation:verdicts` | `scalable_stability_observation.json`, reduced to statuses and the light-validation scalars | see below |

Five things had to be named or reduced rather than dropped, and each is a
measurement, not a guess:

**`wall_ms` and `*_at_ms` are not in the tool's shared `IGNORED`.** The regex
covers `.*_seconds`, `duration_ms`, `.*_monotonic_ms`, `created_at_unix_ms`,
`monotonic` and `wall_time`. Counted over the frozen exact-50 baseline's five
management artifacts, this stage carries 479 `wall_ms`, 400 `*_wall_ms`, 150
`wait_ms`, 200 `restart_*_at_ms`, 200 `health_gate_*_at_ms` and 3,206
`started/ended_at_unix_ms`, none of which match. Widening the shared regex
to `.*_ms` is wrong: the tool's own comment records that `cluster_node_timeout_ms`
and its siblings are configuration and must stay compared. The rule is therefore
stage-local — replace the **value** of any `_ms` key with `<MEASURED_MS>` except
a small configured allowlist (`sample_interval_ms`, `timeout_ms`) — and it
replaces rather than drops so that a field's disappearance still shows, the same
choice Slice 1 made for `pid`.

**Node ids appear as dict keys, not only as values.** `slot_counts` in
`management_sequence.json` is keyed by the 40-hex node id, and
`rename_node_ids` only rewrites strings in values. Without renaming keys the
view differs on 25 lines of pure identity noise; with it, the per-primary slot
counts stay fully compared. This is the first stage to need it.

**Three per-node measurements are named, not dropped.**
`process_pid_before`/`process_pid_after` become `<PID>` for the reason Slice 1
gave — whether a restart changed the pid is the evidence, which pid it is is
not. `primary_repl_offset`/`replica_repl_offset` become `<OFFSET>`: they are
byte offsets that differ by tens of bytes between runs, while the evidence —
`master_link_status: up`, `master_sync_in_progress: 0`, `status: PASS` — is
compared in full. `probed_node_ids` arrives in `as_completed` order and is
sorted, the same fix Slice 2 applied to snapshot samples.

**The workload counters are genuinely non-deterministic, and are reported.**
`workload_impact.sample_count` is how many SET/GETs fitted in the window while
the operation ran, and it moves by up to 50% between the two baseline runs
(`add_replica` 164 against 244; `remove_replica` 147 against 237).
`workload_impact.error_count` moves too, and on one row it moves a lot:
`remove_primary_drained_or_safe_replaced` recorded **17 errors in run-1 and 6 in
run-2**. Both are real availability measurements of a deliberate primary
handoff, and no normalisation can equate 17 with 6 without also hiding a
regression. So both counters are replaced with a placeholder in the view, while
`errors_observed_during_operation` — which is `true` in both runs for the same
three operations and `false` for the other eight — stays compared, and the two
numbers are **reported alongside the diff for both baselines and the candidate**,
exactly as `runtime_all_node_light_probe` is for `cluster_form`.

**Two artifacts are reduced to verdicts, because their content is live server
state.** `workload_windows.json` carries `achieved_qps`, `throughput_ratio` and
a latency histogram per window; `scalable_stability_observation.json` carries
`cluster_stats_messages_ping_sent` and every other `CLUSTER INFO` counter for 50
nodes, plus replication offsets — 40,168 diff lines between two runs of the same
code. Diffing either in full would report a difference on every run. Reduced to
the verdicts and the structural scalars, both are identical between the frozen
runs and both still fail if a window's status flips, a window disappears, or the
stability lane's health criteria change. `workload_windows.json` and
`full_flow_topology_snapshots.jsonl` are shared with `baseline_workload` and
`fault_matrix`, so both views are scoped to rows whose `operation_id` names a
management operation — 66 of 82 windows and 44 of 46 snapshot rows at exact-50.

**Calibration plan.** Before the candidate is diffed:

```bash
./scripts/diff_stage_artifacts.py --stage management_matrix \
    artifacts/baselines/exact-50-6b6f57fd/run-1/001-real.local.full-flow/runtime \
    artifacts/baselines/exact-50-6b6f57fd/run-2/001-real.local.full-flow/runtime
```

must report **8/8 comparable views identical**, plus the reported counters. A
normalisation loose enough to hide the two baselines' differences would hide a
regression with them; a view that cannot be made to report identical between the
two baselines is not added, it is reported. `runtime_start`'s seven views and
`cluster_form`'s five are re-run on the candidate too, to prove the earlier
slices are not regressed.

## exact-200: not a diff item, and why

CLAUDE.md's bar requires exact-200 for `runtime_start`, `cluster_form` and
`stabilize`. `management_matrix` is not on that list, and it cannot be added
retroactively: **no exact-200 run at 6b6f57fd reaches the management lane.** The
frozen exact-200 baseline's own `BASELINE.md` records both runs stopping
downstream of `stabilize` — run-1 at `[Errno 49] Can't assign requested
address`, run-2 at a `/proc/<pid>/stat` probe failure — and the two discarded
attempts stopping even earlier. Neither wrote `rolling_restart_plan.json`,
`rolling_restart_results.jsonl`, `management_sequence.json` or
`management_command_log.jsonl`. exact-50 is the only baseline that carries them.

There is a passing exact-200 run — `gate-20260808T021925Z-0078a747`, PASS
1520.6s, `management_matrix` PASS 992.2s, 26 batches, 400 restart rows — but it
is on HEAD, not on the frozen commit. Diffing a candidate against it would be
precisely the per-slice drift the frozen-baseline rule exists to prevent, and
which the exact-200 baseline was captured to close.

So the bar is: **run one real exact-200 and report its stage numbers; do not
diff them.** What that buys is the thing exact-50 cannot show — the stage at the
scale where its two known problems were first measured — as measured numbers
next to the HEAD reference: stage status and duration, batch and restart-row
counts, `health_probe_summary`'s representative/full/retry counts, and the
per-operation workload counters. A regression that shows up only at 200 nodes
would be visible in those numbers even though it is not a diff result.

## Acceptance for this slice

1. `./gate suite repository.all` at 91/91.
2. Targeted hermetic tests driving the stage with a recording backend while
   `run_docker` raises: one for the rolling restart's stop/start pair through
   `stop_node`/`start_node`, one for the remove-and-restore path where the two
   are separated by the forget convergence (the case a fused `restart_node`
   could not express), and one for the bounded-stability lane's sampler
   deployment through `resource_sampler`.
3. **exact-30 stands in for the six-node smoke.** A six-node run cannot reach
   the stage — the gate's `nodes` parameter declares `minimum: 30`, and the
   product refuses the lifecycle below 30 as well.
   exact-30 is the smallest real run that exercises the stage and it passes on
   HEAD today (`gate-20260808T001341Z-f02ab933`, PASS 728.3s, twelve of twelve
   steps, `management_matrix` PASS 398.6s, 8 batches, 60 restart rows, zero
   residue). The bar is: exact-30 passes, one `management_matrix` span with
   `source_segments == ["management_matrix"]`, 60 restart rows, zero residue.
   It is a behaviour smoke and not a diff — exact-30 has no frozen baseline and
   must not acquire one, since a third baseline captured now would be at HEAD.
4. Real exact-50 against `artifacts/baselines/exact-50-6b6f57fd`, **8 of 8 views
   identical** against run-1 and against run-2, with the excluded workload
   counters reported for both baselines and the candidate.
5. `runtime_start` and `cluster_form` not regressed: 7 of 7 and 5 of 5 at
   exact-50.
6. Real exact-200, stage numbers reported and not diffed, per the section above.
7. The old path proven removed: no `run_docker`, no `docker exec` string and no
   `nodehost_container_name`-as-a-container-argument survives in the stage's
   regions; no fallback; no duplicate implementation. **This explicitly includes
   the six dead functions and the standalone driver** — see below.
8. Add the `management_matrix` entry to `STAGE_VIEWS` (and its reported rows to
   `STAGE_REPORTED`) in `scripts/diff_stage_artifacts.py`, and calibrate it
   run-1 against run-2, 8 of 8 identical, before using it on a candidate.

Then stop and report. The baselines stay frozen at 6b6f57fd; do not re-baseline.

## Dead code the slice must remove, because it is the old path

Six functions in the stage's region have exactly one occurrence in the whole
repository — their own definition — and no test reference:

| Function | Lines | Why it matters |
| --- | --- | --- |
| `_management_log_docker_command` | 37 | **a `run_docker` evidence wrapper**; leaving it after the seam lands leaves a second way to run a Docker command from the stage |
| `_management_make_primary_safe` | 39 | **an older duplicate of `_management_matrix_make_primary_restart_safe`**, using `TAKEOVER` instead of the sync-then-`FAILOVER` path |
| `_management_parse_cluster_nodes_text` | 31 | a `CLUSTER NODES` text parser, superseded by `_management_live_topology`'s bitmap path |
| `_run_management_ops` | 50 | a stub operation list from before the real matrix existed |
| `_management_matrix_strict_operation_row` | 10 | |
| `_management_matrix_strict_workload_window` | 10 | |

Removing them is not scope creep; items 1 and 2 are literally a second
implementation of what this slice extracts, and bar item 7 cannot be met while
they exist. The other four go with them because they are in the same region and
leaving dead parsers behind invites a later reader to call one.

## Two known items the slice must not entrench

Both are recorded in CLAUDE.md and neither is this slice's to fix. What matters
here is that the seam does not make either harder to fix later.

- **`actual=MISSING`.** `_management_live_topology` drops any node whose light
  probe is not OK, and the strict rolling-restart role check reports that
  absence as `live role changed … actual=MISSING` — a collector failure reported
  as a Valkey semantic failure, held for a change that also moves the verdict
  from FAIL to ERROR. The seam does not touch it: `_management_live_topology`
  stays in the lifecycle unchanged (it is layer-1 RESP, §4), and the role check
  stays beside it. The one thing the slice must not do is let `stop_node` or
  `start_node` report a backend failure as a node observation — they raise, and
  the lifecycle's existing error path handles them, so no new road to `MISSING`
  is built.
- **Whole-fleet cadence.** `_management_wait_clean_cluster` still probes every
  node at 1 Hz and `FullClusterValidator` at 0.5 Hz, against §4.4's one
  whole-fleet light round per 60s and §6.1's 3–5 observers. See
  `docs/observability_connection_scale.md`. The three new operations are all
  **per-node** and add no fleet-wide read, and the slice adds no new caller of
  `_management_wait_clean_cluster` or `_management_cluster_health`. The
  `management_command_log` and `rolling_restart_plan` views would show it if it
  did: the plan's `health_probe_summary` records
  `representative_probe_count`, `full_probe_count` and `node_command_count` per
  gate, and those numbers are diffed.

## Report, do not fix

Six things this map surfaced and deliberately leaves alone:

- **`SHUTDOWN NOSAVE` is a Valkey command sent through `docker exec`**, which
  §16.2 forbids. Moving it behind `stop_node` makes it the adapter's business
  rather than the verification layer's, which is the letter of §15, but a Docker
  backend that keeps sending it that way still runs a Valkey command through
  `docker exec`. Whether "stop the process" counts as a protocol check is a
  contract question, and this slice changes where the call lives, not what it is.
- **`_management_reshard_move_slots` derives a peer port by testing the runtime
  type:** `str(target["client_port"]) if target.get("runtime_type") == "docker_process" or target.get("nodehost_container_name") else "6379"`.
  That is the same shape as the hardcoded `"127.0.0.1"` Slice 2 found — a peer
  endpoint computed from backend knowledge at the call site instead of read from
  inventory — and `_cluster_meet_port` already computes exactly this value. It
  is one call site in this stage's own region and it is inventory, not a new
  operation. It is small enough to fold into this slice and it should be, but it
  is a behaviour-visible change to a `MIGRATE` argv that the command-log view
  compares, so it is named here rather than made silently.
- **The rolling restart health gate reads `CLUSTER NODES` from every node on
  every non-clean attempt.** `_management_matrix_wait_rolling_restart_health`
  falls back to `_process_node_snapshots_parallel(nodes)` inside its retry loop
  whenever the representative probe is not clean, and each snapshot is
  `CLUSTER INFO` + `CLUSTER NODES`. §16 item 1 asks that the normal path not
  periodically run whole-fleet `CLUSTER NODES`, and item 3 forbids O(N²) normal
  collection. This is a third, distinct instance of the cadence problem — it is
  about `CLUSTER NODES`, not about light-probe frequency — and it wants its own
  measurement. Not this slice's.
- **`observability/load.py` builds its own `docker exec` wrapper.**
  `MemtierLoadLane.command()` and its preflight construct `["docker", "exec", …]`
  directly. §15 keeps the Load Lane unchanged across backends and §8.1 fixes its
  tool and parameters, but *where the tool runs* is adapter surface, and today
  the observation layer decides it. This stage supplies the container through
  `_load_lane_seed` and nothing more; rewriting `load.py` would be a change to a
  shared observation lane under cover of a stage refactor.
- **`_node_response` still falls back to `docker exec valkey-cli` on any
  exception**, unchanged since Slice 2 recorded it. Six stages share it.
- **The standalone `management_matrix` capability has no real gate test and no
  baseline.** `write_management_matrix_artifacts` drives the same operation core
  through a different frame; the seam reaches it because the core is shared, but
  nothing in the acceptance bar exercises it end to end. Named here so it is a
  known limitation of the bar rather than a discovery later.

## Slice 3 is measured

| Bar item | Result |
| --- | --- |
| `./gate suite repository.all` | 91/91 |
| Targeted hermetic tests | four, each driving the stage with a recording backend while `run_docker` raises |
| exact-30 in place of the six-node smoke | **PASS 686.97s**, twelve of twelve steps, one `management_matrix` span, 60 restart rows, zero residue |
| Real exact-50 against the frozen baseline | two consecutive runs, **PASS 906.01s** and **PASS 842.99s**; run 2 **eight of eight** views identical against both baselines, run 1 seven of eight - see below |
| `runtime_start` and `cluster_form` not regressed | 7 of 7 and 5 of 5, on both runs, against both baselines |
| exact-200, reported not diffed | **PASS 1568.38s**, twelve of twelve steps, 200 of 200 nodes |
| Old path removed | no `run_docker`, `docker exec` or `run_node_cluster_cli` name survives in any of the stage's functions, checked by walking the module's AST rather than grepping the file; 215 lines of dead path deleted |
| Residue | zero after every run, `cleanup_report` PASS |

### The seam is invisible in the evidence, which is the point

The 212 `docker` rows at exact-50 are now produced by the backend and recorded
by the lifecycle, and `management_command_log` diffs clean, so the split did not
cost a row. At 200 nodes the structural evidence is equal to the reference run
in every number the stage owns:

| exact-200 | reference `gate-20260808T021925Z-0078a747` | this slice |
| --- | --- | --- |
| `management_matrix` | PASS 992.2s | PASS 1011.8s |
| restart batches, max concurrent | 26 and 26, 8 | 26 and 26, 8 |
| restart rows, all health gates PASS | 400, yes | 400, yes |
| probe counts: representative / full / retry / node commands | 474 / 200 / 0 / 1348 | 474 / 200 / 0 / 1348 |
| command rows, of which `docker` | 5978, 812 | 5978, 812 |
| `docker` row kinds | the same four | the same four |
| stability lane, cleanup | PASS, PASS | PASS, PASS |

### The one difference, and what it measured

exact-50 run 1 differed from both baselines in exactly one field of one row out
of 1,592: a `cluster_replicate_restored_node` whose `stdout_tail` read
`ERR To set a master the node must be empty and without assigned slots.` where
the baselines read `OK`. The row's `status` was `PASS`.

It is not a regression, and the run's own evidence says so rather than an
argument: the after-topology records `shard-0000-replica-00` as `role: replica`,
`link_state: connected`, following its own shard's primary, in a cluster with
`cluster_state: ok`, 25 primaries, 25 replicas and 16384 slots - and
`management_sequence`, which carries that verdict and both topology snapshots,
is identical to both baselines. So the RESP `CLUSTER REPLICATE` succeeded.

What produced the row is `_node_response`'s `docker exec` fallback, which Slice
2 recorded from a reading of the code and left alone. This is its first
measurement, and it is worse than the reading suggested: the fallback catches
any exception from the RESP path and **re-executes the command**. `CLUSTER
REPLICATE` is not idempotent, so the second attempt found the node already
replicating and returned an error, and because `docker exec` exited 0 the
lifecycle recorded a failed Valkey command as a passing row. A collector retry
became a false report about the cluster - the same shape §16 item 12 forbids.

It did not recur in run 2, at exact-30, or in either exact-200 run, and the
fallback and the connection pooling under it are both untouched by this slice.
It stays reported: the helper is on six stages' paths and CLAUDE.md holds it
open deliberately. Nothing here normalises it away, because a rule that hid a
command's stdout would hide this class of regression too.

### The reported counters

Diffing them is impossible by design; here they are for all four runs, as
`samples/errors` per operation:

| Run | `rolling_restart_replica_first` | `rolling_restart_primary_safe` | `remove_primary_drained_or_safe_replaced` |
| --- | --- | --- | --- |
| baseline run-1 | 757/1 | 1001/1 | 217/**17** |
| baseline run-2 | 751/1 | 1040/1 | 208/**6** |
| candidate run 1 | 699/1 | 973/1 | 246/**40** |
| candidate run 2 | 685/2 | 1001/1 | 203/**9** |

Candidate run 2 sits inside the baseline spread throughout. Candidate run 1's
40 errors on the primary-handoff row is **above** it - 16% of its samples
against the baselines' 8% and 3%. That operation is a deliberate primary
handoff where client errors are expected, its verdict
(`errors_observed_during_operation: true`) and its topology diff clean, and it
is the same run that hit the fallback above and took 906s against run 2's 843s,
so host load is the plausible common cause. That is a hypothesis, not a
conclusion, and it is recorded here rather than resolved because a number this
noisy is exactly what the reported-not-diffed rule exists for.

### A pre-existing latent bug found while checking the threading

The `backend` name is threaded through a long call chain, and one intermediate
function was missed: `_run_scalable_primary_kill_failover`, the fault lane's
recovery, which restarts the killed primary through this stage's `start_node`.
All 91 catalog tests and the four new hermetic tests passed with the bug
present; the exact-30 run found it at 566.77s. Checking the whole module for
the same class of error afterwards - every free name in every top-level
function - turned up one more, and it is not this slice's: `_execute_runtime`'s
exception handler reads `nodehosts` and `snapshots`, neither of which is bound
in that scope, so the failure path raises `NameError` and falls through to the
bare cleanup branch. It is present at the pre-refactor commit too. Reported, not
fixed: it belongs to `runtime_start`'s error path.
