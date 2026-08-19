# M4 Stage 3: the one paid 1280-node run, and what is declared before it

Written 2026-08-19 at the head of the M4-5 commit series. This is the
**preparation** for `m4_gossip_cost_and_stage_plan.md` §7's stage 3. Nothing here
has been executed and no fleet exists: the 32-host Huawei fleet was suspended by
the cloud provider for cost, and every measurement below was taken on the
workstation for free.

Read `m4_gossip_cost_and_stage_plan.md` §1 first. This document exists because of
it: five paid 1280-node runs each found one defect and were relaunched, and the
rule that leaves is to **state the expected number of runs before the first one**
and to audit a defect's *class* rather than relaunching.

**The expected number of runs is one.** Not one attempt that may be repeated -
one run, instrumented from the first second, which either passes or yields a
complete diagnosis. If it fails, the next action is an audit on the workstation,
not a second run.

## §1 Item 4's declaration: the RTO band changes, and every prior number is uncomparable

`scale_1280_native_ecs_optin.yaml` sets `cluster_node_timeout_ms: 60000`. PFAIL
detection, and therefore failover RTO, scales with that value. **Every fault-lane
number this repository has ever recorded was taken at 30000.**

| | `cluster_node_timeout_ms` | measured RTO |
|---|---|---|
| every exact-50 run to date | 30000 | **45-50 s** |
| every exact-200 run to date | 30000 | **47.6-53.8 s** |
| Stage 2 exact-50, Docker, `bc55f56f` | **60000** | **95,230 ms** |
| **Stage 3, 1280 nodes** | **60000** | **no prior; ~95 s is the only anchor** |

So: **do not compare a Stage 3 RTO against 45-54 s, and do not treat a value near
95 s as a regression.** A number in the old band would itself be the surprise.

**The margin that has to hold, and it is the reason this is declared rather than
noted.** The Sentinel canary recovery deadline is a hardcoded **180.0 s**
(`docker_runtime.py:9308` and `:9313`). Stage 2 measured both sides of it: at
120000 the fault lane **FAILS** - 1696 canary rounds with zero reads on the
killed shard, because RTO lands near 190 s - and at 60000 it **PASSES** at
95.2 s. That leaves **84.8 s of headroom at exact-50**, and the headroom is what
Stage 3 spends:

- **Detection scales with the timeout and is flat in node count** - measured
  across 74 retained runs at 44.07 / 44.16 / 43.02 s median for 30 / 50 / 200
  nodes. So the detection term at 1280 should still be ~90 s at 60000.
- **The control-plane term grows with node count** - 2.53 / 3.80 / 8.05 s at
  30 / 50 / 200, and 8.0-19.0 s across the frozen exact-200 baselines. It has no
  measurement at 1280 and it is the term that could consume the margin.

**Record `pfail_to_promotion_ms` and `failure_to_client_recovered_ms` separately,
and rank on the split rather than on the aggregate.** The 2026-08-13 failover
work exists because one aggregate RTO per run cannot separate cluster sizes: the
aggregate moves ~6 % between exact-50 and exact-200 while the control-plane term
moves up to 7.6x.

**If the fault lane fails at 1280, check the deadline before the cluster.** An
RTO above 180 s is the deadline being reached, not necessarily a sick cluster,
and raising it is a fault-lane contract change - the operator's call, not a
config edit.

## §2 What is compiled, not guessed

Everything in this section was compiled at this HEAD against a synthetic
32-host manifest, on the workstation, at zero cost. The manifest is synthetic
only in its addresses; `host_inventory.py` reads the same field set either way.

### §2.1 The fleet shape, and one result worth the provisioning decision

At 32 hosts (16 nodehosts per AZ, 40 logical nodes each) the plan compiles with
**zero validation errors**:

| quantity | value |
|---|---|
| nodes | 1280 |
| nodehosts = hosts | **32**, one nodehost per host, which a native run requires |
| logical nodes per nodehost | **40**, exactly, no tail |
| per-AZ nodes | **640 / 640** |
| shards sharing a nodehost | **0 of 256** |
| shard AZ split | **3 / 2** for all 256 |
| rolling-restart batches per operation | **160**, max concurrent **8** |
| primaries per nodehost | **8**, on every one of the 32 |

**That last row is a finding, and it is free.** `m4_first_1280_run_map.md` §3
reports that at twelve hosts az-a's 128 primaries land on **2 of its 6
nodehosts, 64 each, with four holding none**, forcing 194 batches and giving the
fault lane's sorted-first target 25 % of all primaries. That reproduces exactly
at this HEAD - `nodehost_density.py` is byte-unchanged since `bb92abc2` - and
§3's general rule is confirmed by sweeping fleet sizes through the run path:

| hosts | nodehosts/AZ | gcd(3, nodehosts/AZ) | az-a primaries per nodehost | batches |
|---|---|---|---|---|
| 8 | 4 | 1 | 32, 32, 32, 32 | 161 |
| **12** | **6** | **3** | **64, 64, 0, 0, 0, 0** | **194** |
| 16 | 8 | 1 | 16 x 8 | 160 |
| 20 | 10 | 1 | 13 x 10 | 160 |
| **24** | **12** | **3** | **32, 32, 32, 32, 0, 0, ...** | **161** |
| 26 | 13 | 1 | 10 x 13 | 160 |
| **32** | **16** | **1** | **8 x 16** | **160** |

The defect fires **iff the AZ's nodehost count is divisible by 3**, exactly as
§3 derived. So **moving to 32 hosts removes it as a side effect**: the fault
lane's blast radius falls from 25 % of all primaries to **3.1 %**, and the
rolling restart loses 34 batches. If the fleet is rebuilt at any other size,
**24 hosts is the trap** - it looks like a clean doubling and it clusters.

### §2.2 The planner and the run path disagree about placement at r>=2, and the run path is the one that governs

Reported rather than fixed, and it is why the table above says "through the run
path". The same twelve-host configuration gives:

- **run path** (`_node_specs` -> `_process_nodehosts` -> `build_nodehost_density_plan`):
  az-a primaries **64, 64, 0, 0, 0, 0**.
- **planner** (`build_cluster_plan`): az-a primaries **22, 21, 21, 21, 21, 22**.

One `_assign_within_az`, two orderings into it: the planner interleaves each
primary with its replicas while the runtime blocks every primary first, so the
positional assignment succeeds for one and falls through to the grouped walk for
the other. This is `multi_replica_mr2_slice_map.md` §8 item 6 - the known
planner/runtime ordering divergence, unobservable at one replica - surfacing in
nodehost assignment rather than in port numbers.

Its consequence: **`cluster_plan.json`'s embedded density plan and
`nodehost_density_plan.json` disagree about where the primaries are, in the same
run, at r>=2.** `nodehost_density_plan.json` is written by the run path and is
the one that describes what actually happened. Anyone reading placement out of
`cluster_plan.json` at r>=2 is reading the wrong artifact.

Not this document's to close, and **not to be fixed before Stage 3**: making the
two agree moves `cluster_plan.json` at one replica, which is every frozen
baseline.

### §2.3 What the configuration in the repository is, and is not, ready for

`templates/configs/scale_1280_native_ecs_optin.yaml` is tuned for **twelve
`c4a-standard-2` GCE hosts** (`nodehosts_per_az: 6`,
`max_logical_nodes_per_nodehost: 107`, `host_inventory_path` naming `gce-m3b`).
That fleet is the one whose 1280-node attempts failed, and neither it nor the
Huawei fleet is up.

A 32-host run therefore needs, and **none of these exists**:

1. A fleet manifest at `artifacts/host-fleets/<fleet-id>/inventory.json`.
   `scripts/make_fleet_manifest.py` writes one; reuse the previous fleet's
   `host_id` values so `state_before_cluster` stays comparable, since the diff
   tool compares `host_id` literally and rewrites every address.
2. A configuration with `nodehosts_per_az: 16`,
   `max_logical_nodes_per_nodehost: 40` and that manifest's path. It **must keep
   `profile_name: scale_1280_native_ecs_optin`** - `is_exact_1280_native_ecs_profile`
   keys on that exact string plus eleven other clauses, and a copy with an edited
   name is refused, which is the point of a named exception.
3. Host preparation applied **and re-verified after every boot**. See §4.

`real.ecs.full-flow-1280` is registered and declares `nodes` minimum and maximum
both 1280, with `--operator-opt-in` and `--cost-acknowledged` in its argv. It is
deliberately not in `real.ecs.full-suite`.

## §3 What has never been observed at this size

Stated so that a Stage 3 report says which of these it answered:

- the fault lane's **9 / 12 / 15** at 1280 nodes and five-member shards;
- **RTO at r=4 and this density together** (§1);
- **formation dwell** at 1280 - the 240 s no-progress window and the 1800 s
  ceiling are `observability/cluster.py:57,61`, and dwell is the term that grows
  with node count *and* density;
- the rolling-restart health-gate escalation, rate-limited at `f26769b3` and
  never observed firing since, at a size where one `CLUSTER NODES` reply is
  ~161 KB;
- **~21,900 management rows** and **194 or 160 batches** depending on §2.1;
- canary count **256**.

`cleanup_actions` = **60 rows in four kinds** is *not* on this list: three
separate cleanups measured it exactly as declared at twelve hosts. At 32 it is
`5 x nodehosts` = **160 rows**, native having no network row.

### §3.1 One vocabulary delta to declare before the next diffed run

`TopologyObserver.run` now returns **`observer_substitutions`** (always present;
an empty list is the ordinary case) and each view carries
**`planned_logical_id`**. Those land verbatim wherever a topology validation is
embedded - the myslots report, the scalable validation and stability documents,
the primary-failover observation's recovery validation and affected-shard
convergence, and both M2 capture documents.

Checked, so the declaration is bounded rather than a warning: **no schema
constrains any of them and no diff view compares `observers`**, so no frozen
baseline moves. `diff_artifact_vocabulary.py` will surface the new paths, which
is why they are declared here in advance rather than explained afterwards.

One landmine for whoever extends this: the `management_stability` diff view
compares `full_validation_keys: sorted(keys)`, so a new **top-level** key on a
validation result flips that view red. `observer_substitutions` is inside the
`TopologyObserver` return - a sibling at the top level would not be safe.

## §4 The pre-run checklist

Order matters; each line is a thing that has failed before.

1. **`tcp_mem` is applied and re-read off every host.** The GCE fleet boots from
   **instance metadata**, which rewrites `/etc/sysctl.d/90-valkey-scale-lab.conf`
   nine seconds after every boot and carries no `tcp_mem`, so the committed
   `ecs_host_prepare.sh` is *not* what a running host has. A 1280-node attempt's
   failure mode is a reboot, and a reboot is what removes the tuning. Read the
   value back from each host; do not assume the script ran.
2. **`native_bringup_smoke.py` against the fleet id**, and it must answer clean
   on every host before anything else.
3. **`native_cleanup_proof.py release|abort --fleet-id <id> --nodes-per-host 40`**.
   Memo §4's sequencing: prove reclaim *at this density* before a two-hour run
   can strand 1280 processes. The `--nodes-per-host` flag exists; the default is
   2 and using it would prove nothing about M4's density.
4. **Run from the in-VPC controller, never a workstation.** Transport is 5.1 ms
   median in-VPC against 110-116 ms from a laptop, which across an exact-200's
   3037 rows is 15.5 s against ~5.6 minutes.
5. **`scripts/ecs_gate.py` raises `RLIMIT_NOFILE` toward 65536** and prints what
   it got. Check the printed value; `runtime_fd_limit` needs ~10,500 at twelve
   hosts and should be re-read from the preflight at 32.
6. **`setsid nohup ... < /dev/null &`**. A run started without it dies with its
   ssh session, mid-flight. And watch for `valkey_scale_lab.cli gate execute`,
   not `ecs_gate.py` - the wrapper `execv`s, so a watcher grepping its own name
   reports "finished" immediately.

## §5 Instrumentation, running from the first second

The §1 rule is that this run either passes or yields a complete diagnosis, and
three of the five paid runs could not because the measurement was not running.
**Nothing in a run's own evidence records process RSS or kernel socket memory**,
which is why the whole of `m4_first_1280_run_map.md` §5 had to be taken from
outside the product. Start these *before* the gate, not after a failure:

- **`scripts/mesh_cost_sampler.sh`** - per-host valkey RSS and
  `/proc/net/sockstat`. This is the instrument that told GCE's wall from the
  product.
- **`scripts/cluster_link_sendbuf_sampler.sh`** - it exists for the one window
  no artifact covers, **cluster formation**. Note that
  `total_cluster_links_buffer_limit_exceeded` is a `CLUSTER INFO` field and is
  already in `fault_sequence.json`, `fault_command_log.jsonl` and
  `fault_results.json`, so the run's own evidence covers the fault window; the
  sampler is for before it.
- **`MemAvailable` per host.** On the failed GCE attempt it fell 3569 MB -> 271 MB
  in one 45 s interval, which no per-node metric showed.

## §6 If it fails

- **Kill and reclaim in one move.** Killing the controller does not stop the
  fleet - the cluster bus is peer-to-peer, so 1280 unmanaged nodes carry on, and
  the heaviest link-freeing on the M4-4 abort was sampled *after* the controller
  was dead. That abort cost a host. The correct sequence is kill, then
  immediately `cli gate cleanup --state <run>/state.json`, not kill and observe.
- **Then stop.** Audit the defect's class on the workstation. Do not relaunch.
- Expect the reporting defects `m4_first_1280_run_map.md` §5.2 records to still
  be present: a Gate-plan refusal dies with `AdapterOwnershipError` and writes no
  verdict, and a failing teardown's exception can replace the failure that caused
  it. Both are reported and neither is fixed, so **read the run's own log, not
  only the Gate's error**.
- **Destroy the fleet immediately afterwards**, pass or fail. The golden image
  makes a rebuild a Console action, so the fleet should exist only for the run.

## §7 The un-retried-command audit, reported and not fixed

The defect class that cost five paid runs - **a single un-retried RESP command
inside a ~1024-way fan-out** - was audited across the *formation* path, which is
where all four known instances were found. **The management and fault matrices
had never had the same audit**, and at 1280 nodes they are where a two-hour run
spends most of its time. That audit was done for this handoff, statically, at
zero cost, with a second model.

**None of it is fixed here.** Each is a behaviour change on `run_exact_gate`'s
path and needs its own evidence; §6's four items are what this commit series
carries. This section exists so Stage 3 is planned knowing the exposure, and so
the next item has a ledger rather than a starting point.

Two structural facts govern all of it, both verified in source:

- **S1: every fault-scenario exception is run-fatal.**
  `_local_full_flow_execute_fault_probe` catches, writes its FAIL row, and then
  re-raises. There is no per-scenario tolerance.
- **S2: a transient timeout is classified `semantic`.** That is §12.1 working as
  designed and item 2 deliberately does not change it - but it means that at a
  gap-checking site a transient is indistinguishable from a confirmed cluster
  failure, and takes the fatal branch.

Ranked by exposure. Counts are estimates from the call graph at N=1280 unless
marked verified; read them as *relative* exposure, because the ~1/1000 transient
rate they lean on was measured during 1280-node **formation** under a gossip
storm and the management-time rate is unknown and demonstrably lower - real
exact-200 runs pass with every one of these live.

| # | site | kind | why it fires |
|---|---|---|---|
| **F1** | `_management_require_live_topology` | read | one-shot whole-fleet round, **any single gap raises**. ~43 whole-fleet rounds per run plus a batch-scoped variant over ~160-194 batches x 2 operations. Largest surface, and one function covers it. |
| **F2** | `_management_log_node_command` | **mutation** | the chokepoint: `except Exception` -> FAIL row -> **raise**, with no reply/transport distinction. ~10,900 un-retried mutations per run (SETSLOT, FAILOVER, MIGRATE, MEET, REPLICATE). Blind retry is wrong here; every family already has a verify step next door. This is `m4_gossip_cost_and_stage_plan.md` §8's open mutation item, now with counts. |
| **F3** | `_management_log_forget_removed_node` | mutation | **cheapest win.** A timeout's `repr` fails the `"unknown node"` test, so it becomes FAIL and **raises out of the 120s convergence loop that exists to re-issue exactly this command**. The error-*reply* case is already tolerated and the absence verify already exists. ~5,100 commands per run. |

**Re-verifying F2 or F3 means reading to the end of the function, not to the row write.** Both raise *after* `command_log.append(entry)`, so each one looks tolerant - catch, record, return - right up to the last two lines. Checking this the quick way produces the confident wrong answer that the loop absorbs a transient; it does not.
| **F4** | `_management_cluster_nodes_contains` | read | **verified: a bare `RespConnection` with no `try` at any level.** A `socket.timeout` escapes as a raw `OSError`. `_retry_read` is the exact fix. |
| **F5** | `_management_cluster_health` as a raising gate | read | one transient FAIL row makes `cluster_state` "unknown" (it requires *all* nodes to answer) -> raise. The quieter variant writes a **false FAIL** for an operation that succeeded. The tolerant shape already exists next door in `_management_wait_clean_cluster`. |
| **F6** | `FullClusterValidator` one-shots in the fault lane | read | worst instance is the primary-kill **down-window** validation, which runs while the primary is dead and the fleet is gossiping the failure - the moment a 5s read is most likely to be slow - and `validate_light` raises on one FAIL row while `run()` retries only `ConvergenceFailure`. Part of this fix belongs in `observability/cluster.py`. |
| **F7** | reshard drain `GETKEYSINSLOT` | read | unguarded inside the batch loop; dies **mid-slot-move**, with the slot left `IMPORTING`/`MIGRATING`. |
| **F8** | `_host_command_binary` MYSLOTS | read | no guard; raises a raw `socket.timeout`, not even a `DockerRuntimeError`. |
| ~~**F9**~~ | ~~seven unconverted `CLUSTER MYID` siblings~~ | read | **DONE.** All seven wrapped in `_retry_read`, with an AST guard asserting the set of functions still holding an un-retried `CLUSTER MYID` is exactly `{"_cluster_node_ids_by_shard"}`, and a second test asserting that function has no management or fault caller. See §7.1. |
| **F10** | fault-probe survivor reads | read | `CLUSTER INFO` at t=30 while a replica, nodehost or AZ is paused, plus the majority-side read and a single-attempt recovery PING. All run-fatal via S1. The *isolated*-side reads are correct by design and excluded - see `85d5096a`. |
| **F11** | reshard seed/verify client commands, and one workload error flipping a non-event window | low | arguably availability-measurement-by-design. Operator call, not a defect. |

**Suggested order for the rest**: F1 (one function, largest surface), F3
(cheapest, and the loop that should have absorbed it already exists), then F2's
per-family verify-then-retry as **its own item with its own evidence** - it is
the open mutation question and blind retry there corrupts state.

### §7.1 F9 is done, and what it did and did not settle

All seven `CLUSTER MYID` reads now go through `_retry_read`. Each was a read
whose answer addresses every mutation that follows - the reshard's source and
target ids, the `removed_id` every `CLUSTER FORGET` in a 120s convergence loop
names, the `master_id` a rejoining node replicates from, and the `promoted_id`
read on a just-promoted node while the fleet is still gossiping the role change.
So a transient did not cost a command; it ended the operation before any of it
ran.

**What is guarded rather than merely fixed**: an AST walk asserts the set of
functions still holding an un-retried `CLUSTER MYID` is exactly
`{"_cluster_node_ids_by_shard"}`, so an eighth fails by name wherever it is
written. That exemption is a statement about which lane the read is on, not
about it being safe - it is a genuine un-retried read inside a fan-out over
every primary, 256 of them at 1280 nodes - and a second test asserts none of its
callers is a management or fault function, so the exemption stops holding the
moment one appears. Converting it would change a path every frozen baseline was
taken on, which is why it is on the formation ledger instead.

**Not settled by it**: `_retry_read` still catches a broad `except Exception`,
so it retries error replies as well as transport failures, contradicting
`is_transient_transport_error`'s own doctrine. Narrowing it needs the
`subprocess.TimeoutExpired` decision and changes every existing caller, so it is
its own change. Harmless at these seven - `CLUSTER MYID` does not produce an
error reply this product can generate.

**F1 has a prerequisite that is easy to miss.** Retrying only the *gapped* nodes
needs the row to say whether its failure was transport, and it does not:
`_failed_row` records `failure_kind` from `is_collection_failure`, which answers
`"semantic"` for a timeout. Recording `is_transient_transport_error(exc)`
alongside it - a second field, not a changed one - is what makes F1 fixable
without re-opening §12.1.

**Re-verified as already tolerant**, so the coverage is auditable rather than a
sample: `_management_topology_snapshot`, `_management_wait_clean_cluster`,
`_management_wait_node_role`, the rolling-restart health gate,
`_management_matrix_wait_replica_sync_ready` (fixed at `5082e4e8`),
`_management_matrix_first_live_node`, the Sentinel lane, `AffectedShardObserver`
rounds, and the partition isolated-side reads.
