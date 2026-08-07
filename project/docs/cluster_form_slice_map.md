# Slice 2 map: `cluster_form`

Written before moving any code, for the reason Slice 1 worked: the seam is
argued from the timeline and artifact evidence first, so a design surprise
surfaces while it is still cheap. `docs/runtime_start_slice_map.md` carries the
accepted `NodeBackend` seam this slice extends.

Slice 1's surprise was that seven backend operations had to become nine methods,
because fusing a pair would have erased a timeline segment. This slice has two
surprises of its own, both recorded below: the stage has **two implementations
with different segment sets**, and the design document already fixes most of the
answer to "what does the backend own here".

## Where the stage begins and ends

`_write_measured_lifecycle` in `gates/real.py` defines `cluster_form` as every
setup timeline span whose `category` is `cluster_formation`. `runtime_start`
ends at `state_write_before_cluster`; `cluster_form` begins at
`primary_cluster_create`.

The stage does not emit the same segments at every scale. `_configure_process_cluster`
dispatches on `len(nodes) > 30`, and the two branches are different code:

| Segment | ≤30 nodes | >30 nodes |
| --- | --- | --- |
| `primary_cluster_create` | yes | yes |
| `cluster_slots_assign` | yes | no |
| `replica_meet` | yes | yes, unless the preseed strategy folds it into `replica_replicate` |
| `replica_replicate` | yes | yes |
| `cluster_convergence_wait` | **no** | yes |
| `cluster_final_snapshot` | **no** | yes |
| `cluster_final_full_snapshot` | yes | yes |

`REQUIRED_SETUP_SEGMENTS` demands `cluster_convergence_wait` and
`cluster_final_snapshot`, which only the >30 branch produces, and does not list
`cluster_slots_assign`, which only the ≤30 branch produces.

**Consequence for the acceptance bar.** The six-node smoke runs the ≤30 branch;
exact-50 and exact-200 run the >30 branch. For `runtime_start` the smoke and the
scale runs exercised one code path and the smoke could stand as segment-order
evidence. Here it cannot: the smoke proves the small branch and nothing about
the branch the diff actually compares. Both branches need covering, and the bar
below says how.

Measured on the frozen exact-50 baseline (`lifecycle_timeline.json`,
`cluster_form`, 122621.8 ms, PASS) — the stage is 122.6s of an ~866s run, of
which `primary_cluster_create` is 84.8s.

## Where the code lives today

| Region | Location |
| --- | --- |
| branch on scale, small-cluster formation | `_configure_process_cluster` |
| large-cluster formation, convergence wait, final snapshots | `_configure_large_process_cluster` |
| primary create + replica attach, strategy dispatch | `_create_large_cluster` |
| the four primary-create strategies | `_create_primary_cluster_valkey_cli`, `_create_primary_cluster_manual_tree_meet_parallel_slots`, `_create_primary_cluster_tree_meet_addslotsrange`, `_create_primary_cluster_preseed_epoch_tree_meet` |
| `valkey-cli --cluster create` itself | `_create_primary_cluster` |
| replica attach | `_configure_large_cluster_replicas_with_diagnostics`, `_configure_replicas_local_meet_replicate_pipeline`, `_replicate_process_nodes_parallel` |
| membership fanout | `_tree_fanout_meet_nodes`, `_tree_fanout_levels`, `_meet_node_pair` |
| slot and epoch commands | `_add_slots_node`, `_add_slots_range_node`, `_set_config_epoch_node` |
| peer addressing | `_cluster_meet_address`, `_cluster_meet_port`, `_cluster_create_address` |

The lifecycle calls the stage from `_create_process_scenario` as a single line
(`_configure_process_cluster(nodes, timings=..., setup_timeline=...)`), so the
stage boundary in the lifecycle is already clean. Unlike `runtime_start`, this
stage is *not* pre-factored into helpers that map onto backend operations; it is
one algorithm with a small amount of Docker inside it.

## The backend operations this stage needs beyond the nine

Derived by enumerating what the regions above actually reach, then checked
against §15 of `docs/scalable_cluster_observability_design.md`, which already
fixes the boundary:

> 运行时适配器只负责替换: inventory 和 endpoint 发现; 进程启动、停止和恢复;
> actuator 实现; 本地资源采样器部署; 日志与证据上传。
> 保持不变: RESP 命令; `CLUSTER MYSLOTS` 契约; 三层验证逻辑; ...
> 不得把 Docker 特有命令带入验证层。

So the MEET fanout, the slot ranges, the replica attach, the convergence waits
and the snapshots are **not** backend surface. They are RESP against endpoints,
and they stay in the lifecycle. Only two things in this stage are
backend-specific:

1. **`client_host(node) -> str`** — where this process connects to speak RESP to
   a node. Under Docker that is loopback, because `start_nodehost` publishes
   every hosted port as `127.0.0.1:port:port`; under `native_multi_ecs` it is
   the node's own address. §15 names endpoint discovery as the adapter's job.
2. **`run_cluster_admin(node, argv, *, timeout, operation_id, record_node)`** — run a `valkey-cli`
   that must sit *inside* the cluster network, for commands the lifecycle
   cannot issue from outside it. Two callers, both real: `valkey-cli --cluster
   create` in the default strategy (`_create_primary_cluster`), and the
   M2-only cluster-aware `SET`/`GET` data-path probe, which follows a `MOVED`
   to an unroutable address.

Neither is a barrier the timeline measures, so unlike Slice 1's pair case
neither splits: the segments around them are opened by the lifecycle, and the
same method called twice from two different segments erases nothing.

### The third operation dissolved, and a worse gap took its place

Mapping predicted a third, `peer_address(node)` — what *other* nodes are told,
which under Docker is the nodehost's address on its own network and is not the
same value as the client host. Reading the code closed that: the peer address is
**already** backend-supplied through the Slice 1 seam. It arrives as
`NodehostAddress.address` when a nodehost starts, and the lifecycle records it
on every node the nodehost holds as `nodehost_container_ip`, which
`_cluster_meet_address` then reads. Adding a method would have been a second way
to fetch a value the backend already provides. It is inventory, not a call.

That is the map's own rule working — enumerate what the regions actually call
rather than design ahead of use — so the seam is two operations, not three.

The client host turned out to be the real defect, and a larger one than
"endpoint resolution is inlined". `host` was written **only into the state
artifact**, hardcoded as `"127.0.0.1"` at two places, and never onto the live
node dicts at all. Every reader in the run therefore took the default arm of
`node.get("host", "127.0.0.1")`. A second backend would not have failed; it
would have silently talked to loopback. The fix is what §15 asks for: the
backend fills in the inventory once, at the point the node becomes reachable,
and the readers stop defaulting. `_process_runtime_state` now writes the
backend's value through instead of a constant.

The defaults are removed at the four sites this stage owns. Five remain, in
`management_matrix`, `fault_matrix` and `recovery`; they now read a real value
because the key exists, and removing the dead default arm belongs to those
stages' slices, not to a refactor of this one.

## What stays in the lifecycle

The RESP transport (`_host_command`, `_encode_resp`, `_read_resp`), the fanout
tree, the slot ranges, every `_wait_process_*` predicate, the snapshot summaries
and the timing/timeline recording. §15 lists all of these as unchanged across
backends, and §17 explicitly allows the RESP client's internal class structure
to be an implementation choice but not a contract change.

## Blast radius

- **35 tests** reference the stage's symbols: 28 in
  `tests/integration/test_docker_runtime_contract.py`, 5 in
  `tests/integration/test_rolling_restart_scaling.py`, 1 in
  `tests/real_valkey/test_exact_gate.py`, 1 in
  `tests/stability/test_stability_health_criteria_gap.py`. Many of these
  monkeypatch `_node_command` or a `_create_primary_cluster_*` strategy.
- **`_node_command` is shared, and mostly not this stage's.** The module has 57
  occurrences; only **8** are inside cluster-form-owned functions. The rest
  belong to `stabilize`, `management_matrix`, `fault_matrix` and `recovery`, and
  to the `_wait_process_*` helpers those stages share with this one. Converting
  all of them is a later slice's work, not this one's. This slice changes how a
  node's *endpoint* is resolved, not how RESP is spoken.
- Docker names reachable from the stage today: `_create_primary_cluster`
  (`docker exec … valkey-cli --cluster create`), `run_node_cluster_cli` (the M2
  data-path probe), and `run_node_cli` reached as a fallback inside
  `_node_response`. The first two become operation 3. The third is discussed
  under "report, do not fix" below.

## Calibrating the diff

Run before trusting any candidate, as in Slice 1: diff the two frozen baseline
runs against each other and require every view identical. These five views were
built and calibrated against `artifacts/baselines/exact-50-6b6f57fd/run-1`
versus `run-2` while writing this map, and all five now report identical. Three
things had to be named rather than dropped, and one row had to be excluded:

| View | Source | Normalisation |
| --- | --- | --- |
| `lifecycle_timeline:cluster_form` | `lifecycle_timeline.json` | none beyond the shared scrub |
| `runtime_timing_breakdown:stage_rows` | `primary_cluster_create`, `replica_meet`, `replica_replicate`, `runtime_representative_probe`, `runtime_final_full_probe`, `runtime_diagnostic_full_probe` | cluster node ids renamed; `replica_diagnostics` sorted; `slowest_replicas` reduced |
| `runtime_timing_breakdown:summary` | the artifact's `summary` block | none beyond the shared scrub |
| `cluster_snapshots` | `cluster_snapshots_local_full_flow.json` | `samples` sorted by `logical_id` |
| `state:operations` | `state.json` `runtime.operations` | `samples` sorted by `logical_id` |

**Cluster node ids vary per run and are renamed, not dropped.** Valkey generates
a 40-hex id at node start. The `master_id` in every `replica_diagnostics` row
differs between the two baseline runs. Dropping the field would hide a replica
attached to the wrong primary and would hide the field's absence, so each id is
replaced with `<node:{logical_id}>`, resolved through `cluster_myslots_report.json`,
and an unresolvable id becomes `<node:UNKNOWN>` so that it shows. Under this
rename every replica in both runs points at its own shard's primary — which is
the evidence, and it survives.

**Snapshot sample order is completion order.** `_process_node_snapshots_parallel`
collects through `as_completed`, so the two baseline runs list the same two
representatives in opposite orders. Sorting by `logical_id` drops the race and
keeps every sample.

**`slowest_replicas` is a ranking by a duration that is already ignored.** Its
membership is pure timing noise — the two baseline runs name different replicas.
It is reduced to its row count plus the distinct non-identity content of its
rows, so "five rows, all PASS, all `replicaof_confirmed`" is still checked while
which five were slowest is not. The full per-replica evidence is unaffected:
`replica_diagnostics` lists every replica and is compared in full.

**`runtime_all_node_light_probe` is excluded, and that is a real gap.** It is a
retry counter for cluster convergence, and the two frozen baseline runs
genuinely differ: run-1 needed 30 attempts and recorded `status=FAIL` with a
`cluster_state: fail, 15729/16384 slots` snapshot before converging; run-2
converged on the first attempt with `status=PASS`. No normalisation can make
those equal without hiding a regression, so the row is not diffed. Its `count`
and `status` will be **reported alongside the diff as measured numbers** for
both baseline runs and the candidate, so a candidate that made convergence
dramatically worse is still visible — just not as a diff result.
`runtime_representative_probe` is kept: its `count` is 4 in both runs, so it is
deterministic.

## exact-200: the bar is stage-scoped, on measurement

CLAUDE.md left this open: either `cluster_form`'s exact-200 bar is judged
stage-scoped the way Slice 1's was, or the downstream failures are fixed first.
**Agreed at review: stage-scoped.** Unlike Slice 1 this is not an argument from
absence — the stage's own exact-200 evidence is complete and passing on HEAD.

From `artifacts/gate-runs/gate-20260807T125644Z-2f53bae9`, the exact-200 run of
the Slice 1 commit (FAIL, 392.1s, at rolling restart):

| Stage evidence at 200 nodes | Result |
| --- | --- |
| `primary_cluster_create` | PASS, 51.69s |
| `replica_meet` | PASS, 2.52s |
| `replica_replicate` | PASS, 8.76s |
| `runtime_representative_probe` / `all_node_light_probe` / `final_full_probe` | PASS |
| `cluster_snapshots` `after_cluster_create` | 200 known nodes, state `ok`, 16384/16384 slots, 100 primaries, 100 replicas |
| `cluster_snapshots` `final` | identical |
| `runtime_timing_breakdown` status | PASS |
| `cluster_myslots_report` | PASS, 200 of 200 nodes observed |

So every artifact this slice's diff compares exists, is complete and is passing
at 200 nodes. The bar can be met by diffing them, which is a stronger claim than
Slice 1 could make.

One view is short at this scale. `lifecycle_timeline.json` is written by the
gate after the whole flow, so a run that fails at rolling restart never produces
it, and `lifecycle_timeline:cluster_form` is unavailable on both sides of the
exact-200 diff. The tool reports that as `UNAVAILABLE in both runs` rather than
as a match or a difference, so exact-200 is **four comparable views, one
unavailable**, while exact-50 is five. The unavailable view carries the stage's
start and end times, which the four remaining views already cover through the
timing breakdown, so nothing is lost beyond the stage's placement in the run.

The three recorded exact-200 failures are all strictly downstream:

- rolling restart, `live role changed … actual=MISSING` — `management_matrix`,
  four stages after this one.
- `Errno 49 Can't assign requested address` — a host port exhaustion during a
  later lane, not cluster formation.
- `CLUSTER SHARDS contains unhealthy nodes` — raised by
  `normalize_cluster_shards` in `observability/cluster.py`, reached through
  `FullClusterValidator`, which this setup path runs in the `cluster_myslots`
  span *after* `stabilize`. `cluster_form` reaches that function only under the
  non-default `preseed_epoch_tree_meet_pipeline_replicas` strategy, and there it
  is swallowed into a retry rather than raised.

None of the three can fail this stage's diff, because the run that produced them
wrote every stage-owned artifact first. That is the difference from Slice 1,
where exact-200 was accepted on "the stage passed" alone.

## Acceptance for this slice

1. `./gate suite repository.all` at 91/91.
2. Targeted hermetic tests driving `cluster_form` with a recording backend while
   `run_docker` raises — covering **both** branches, ≤30 and >30, since they are
   different code with different segment sets, and asserting each branch's own
   segment set rather than a shared one. Agreed at review: the branch gap is
   closed hermetically, not by adding a second real smoke.
3. A real six-node smoke (`templates/configs/single_mac_6node.yaml`), which
   proves the ≤30 branch: segments in order, zero residue. The artifact's own
   status cannot pass at six nodes at any commit; see below.
4. Real exact-50 against `artifacts/baselines/exact-50-6b6f57fd`, all five views
   identical, with the two excluded `runtime_all_node_light_probe` numbers
   reported.
5. Real exact-200, the same five views against
   `artifacts/gate-runs/gate-20260807T125644Z-2f53bae9`, judged stage-scoped per
   the section above. The full flow is still expected to fail at rolling restart.
6. The old path proven removed: no Docker name survives in the stage's regions,
   no fallback, no duplicate implementation.
7. Add the `cluster_form` entry to `STAGE_VIEWS` in
   `scripts/diff_stage_artifacts.py`, and calibrate it (baseline run-1 versus
   run-2, five of five identical) before using it on a candidate.

Then stop and report. The baseline stays frozen at 6b6f57fd; do not re-baseline.

## The ≤30 branch: a flaky replica attach, and an unsatisfiable contract

Four six-node runs, two per commit:

| Commit | Run | Result |
| --- | --- | --- |
| this slice | 1 | FAIL, `shard-0000-replica-00 did not become replica of 3c7ab66a…` |
| this slice | 2 | **PASS**, cluster formed, all five segments in order |
| frozen baseline 6b6f57fd | 1 | FAIL, `shard-0002-replica-00 did not become replica of 66c94d38…` |
| frozen baseline 6b6f57fd | 2 | FAIL, `shard-0000-replica-00 did not become replica of f01e9ce9…` |

So the failure is **flaky and pre-existing**, not a regression: the baseline
failed both attempts, this slice failed one and passed one, and the only
six-node run that has ever completed is on this slice's code. It is in
`_wait_process_replica_of` inside `replica_replicate`, which requires all three
of `role == replica`, `replication_state == connected` and
`myslots.slot_owner_id == master_id`. Which of the three loses the race was not
run down: that is a fix on its own evidence, not a refactor slice's to make.
Every run cleaned up with zero residue.

The passing run confirms the map's branch prediction exactly. Its
`cluster_formation` segments are

    primary_cluster_create  cluster_slots_assign  replica_meet
    replica_replicate       cluster_final_full_snapshot

which is the ≤30 set this map predicted and the hermetic test asserts, and its
cluster reached 6 known nodes, state `ok`, 16384 slots, 3 primaries and 3
replicas across five snapshots.

It also shows the branch contract is unsatisfiable, at both commits. The setup
timeline artifact is `status: FAIL` on the passing run, for exactly two reasons:

    missing required setup timeline segment: cluster_convergence_wait
    missing required setup timeline segment: cluster_final_snapshot

`REQUIRED_SETUP_SEGMENTS` demands both, and only the >30 branch emits them. The
baseline's timeline is `FAIL` for the same two segments. A six-node run can
therefore form a correct cluster and still never produce a passing setup
timeline — which is why bar item 3 was written as "segments in order" and is met
in that sense, while the artifact's own status cannot be.

Three pre-existing things this slice will surface and must not quietly change:

- **`_node_response` falls back to `docker exec valkey-cli` on any exception**,
  including a RESP error reply, because `_read_resp` raises `DockerRuntimeError`
  for a `-ERR` and the fallback catches `Exception`. §16.2 requires that Valkey
  protocol checks not use `docker exec`. This is a shared helper on six stages'
  paths, not this stage's, and removing it is its own change on its own evidence.
- **The M2 data-path probe uses `docker exec valkey-cli -c`** for the same
  reason it must: following a `MOVED` needs a client inside the cluster network.
  Operation 3 gives it a home, but whether a redirect-following probe counts as
  a §16.2 "protocol check" is a contract question, and M2 is parked.
- **`_configure_process_cluster`'s `>30` branch is scale-dispatched, not
  configured**, so the two branches can drift and only one is diffed. Naming it
  here so it is a known limitation of the bar, not a discovery later.
