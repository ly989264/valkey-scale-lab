# M4-4/M4-5: what a 1280-node cluster costs, and the staged plan that replaced paid runs

Written 2026-08-18 at `bc55f56f`. This is the handoff for the session that
implements the four approved items in §6 and then takes the one paid run in §7.

**Read §1 first.** It is the reason this document exists: five real 1280-node
runs were spent finding one defect each, the fleet was suspended by the cloud
provider for cost, and everything since has been measured on local Docker at zero
fleet cost. §5 is what that bought.

## §1 The cost lesson, stated first because it governs everything else

Five paid 1280-node attempts, each ~8-20 minutes on 32 hosts plus the idle time
around them. Each found exactly one defect and was relaunched. Four of the five
were diagnosing things measurable for free, and the fifth was blocked by the same
defect *shape* as the first.

**The rule this leaves:** on a paid fleet, state the expected number of runs
before the first one, and when a run fails, audit the *class* of defect for other
instances rather than relaunching. The same shape (a single un-retried RESP
command in a 1024-way fan-out) turned up at **four** sites; one careful read of
the formation path would have found them together.

The fleet does not need to idle. The golden image makes a rebuild a Console
action, so it should exist only for the runs themselves.

## §2 What M4-4 set out to do, and what actually happened

Scope was `cluster-link-sendbuf-limit`, to make a 1280-node run fit the twelve
8 GB GCE hosts. That succeeded as an item and failed as a strategy:

- `39d44012` set the directive to 32 KiB and **proved it a no-op at exact-200**
  (two real runs; the whole delta was one added line in all 200 node configs;
  `generated_valkey_configs_manifest` does **not** move, correcting the handover).
- The value's floor is **one whole gossip message**, not a memory budget.
  `freeClusterLinkOnBufferLimitReached` frees the link when the send queue
  exceeds the limit, and a PING is `2256 + 104*max(3, N/10)` bytes - so
  `m4_first_1280_run_map.md` §7.1's recommended 8 KiB is *half a message* at
  1280 and would free every link ten times a second.
- At 1280 on twelve hosts, **both** failure modes appeared at once: the bus
  thrashed (33,000 link frees over four sampled nodes per host) *and* memory still
  exhausted. So no value of that knob fits that fleet, and §7.3's provisioning
  table is the answer.

## §3 The fleet moved, and that answered the provisioning question

GCE quota refusals killed the 52-host plan; the operator provisioned Huawei
Cloud. Read `huawei-fleet-image-baseline` in session memory for the image and the
fleet layout. The result that matters:

**A 1280-node cluster forms and is healthy on 32 x (8 vCPU / 16 GB).**
`cluster_state: ok`, 1280/1280 known, 256 primaries, 1024 replicas, gossip
converged in ~56 s. Against GCE's 12 x (2 vCPU / 8 GB):

| per host | GCE, 107 nodes | Huawei, 40 nodes |
|---|---|---|
| bus sockets | 223,622 | **102,528** (predicted 102,320) |
| kernel TCP memory | 2.1-3.1 GB | **0-1 MB** |
| valkey RSS | 1,701-2,652 MB | **642 MB** |
| MemAvailable | collapsed to 271 MB | **14,353 MB** |
| OOM kills | 13, then 8 hosts wedged | **0** |

The GCE wall was never the product. It was 107 nodes on 2 vCPU.

## §4 Four defects of one shape, and the two reporting defects that hid them

All found by running, each costing a run until the audit in §5.2 found the rest
statically.

1. `_bounded_parallel` caught `concurrent.futures.TimeoutError` around
   `future.result()`. On Python 3.11+ that **is** the builtin `TimeoutError`,
   which **is** `socket.timeout`, so a worker's RESP read timeout was reported as
   the pool's budget - a run died at 448 s claiming a 10,225.7 s budget was
   exceeded while 1023 of 1024 workers had finished in 98 s. **Invisible on the
   workstation**, which is Python 3.9 where the classes differ; mutation-checked
   on the controller.
2. `replicate_command`'s `_process_node_is_replica_of` pre-check: an unguarded
   5 s `RespConnection` in front of a command that retries for 120 s.
3. `_meet_node_pair`: one `CLUSTER MEET` of 1024, no retry.
4. `_wait_process_replica_of`: the same unguarded probe one pipeline stage later,
   fanned over all 1024 replicas polling once a second - the higher-count
   instance of (2).

Plus `_management_matrix_wait_replica_sync_ready`, which had `CLUSTER MYID`
outside its retry loop *and* an `except` omitting `OSError` (which `TimeoutError`
subclasses), so error *replies* were retried and transport failures were not.

And the reporting defects: `lifecycle.py`'s failure handler let a failing
`reclaim_run` **replace** the exception that caused it (map §5.2), costing two of
the five runs their diagnosis; and the convergence bound was a fixed 240 s whose
own comment said it "will need re-measuring before 500 nodes".

## §5 What was measured for free, and it is the substance of this handoff

### §5.1 The gossip cost curve has a knee, and it is not where a fixed timeout assumes

Local Docker, same code, cluster-bus **bytes/s sent per node**:

| N | msgs/s in+out | bytes/s sent | bytes/msg | mem_cluster_links |
|---|---|---|---|---|
| 50 | 4.17 | 5,920 | 2,844 | 102,912 |
| 100 | 5.30 | 8,567 | 3,262 | 212,256 |
| **200** | **24.6-27.6** | **30,915** | 4,102 | 426,656 |

Nearly flat to 100, then **3.6x**. A node need only ping peers it has not heard
from within `node_timeout/2`; below ~150 peers the random cron ping keeps
everyone fresh, above it the forced rule binds and the rate goes as N.

**The message-size model is confirmed to 1-2% at all three scales**:
`2256 + 104*max(3, N/10)` + ~33 bytes of extensions (2,844 measured against
2,809 predicted; 3,262 against 3,329; 4,102 against 4,369). At N=1280 that is
**15,601 bytes**. Note this corrects an earlier claim that packets are floored at
`sizeof(clusterMsg)` = 4,352 - that floor is on the *allocation*; `totlen` is
trimmed.

### §5.2 The timeout lever is 2.1x, not the 4x both analysts predicted

Two N=200 runs differing only in `cluster_node_timeout_ms`: 30,915 against
14,767 bytes/s per node. Decomposing them: **30% of gossip is
timeout-independent random pinging, 70% is the forced rule.** The forced share
grows with N, so the same change is worth ~3.4x at N=1280.

Extrapolated to N=1280, per vCPU on a 40-node/8-vCPU host: **30 s -> 5.5 MB/s,
60 s -> 2.9, 120 s -> 1.6**, against roughly 1-2 MB/s per dedicated core in the
only published 2000-node cluster.

### §5.3 60 s is the measured ceiling, and 120 s breaks the fault lane

Two real Docker exact-50 runs:

- **120000 FAILS** - Sentinel canaries never recovered the killed shard, 1696
  rounds with zero reads on the affected slot. PFAIL detection scales with the
  node timeout and the canary recovery deadline is a **hardcoded 180 s**
  (`docker_runtime.py:9281`), so an RTO near 190 s blows it.
- **60000 PASSES** - PASS 1097.80 s, fault lane 9/9 `REAL_PASS`,
  `cluster_recovery_latency_ms` **95,230 ms** against ~47,000 at 30000.

So 60000 is the largest value that leaves the deadline untouched, and going
further is a fault-lane contract change rather than a config edit.

### §5.4 The context that resolves "how did the official test pass"

The Valkey 1-billion-RPS benchmark was a real single mesh of **2,000 nodes** -
larger than 1280, on this engine. It is not that they avoided gossip storms; they
paid for them: **one node per r7g.2xlarge with six dedicated cores**,
`io-threads 6`, ~16,000 vCPU for 2,000 nodes. This lab runs 40 nodes per 8 vCPU
host with `io-threads 1`. AWS ElastiCache caps a Valkey cluster at **500 nodes**;
managed Redis offerings avoid the data-plane mesh entirely.

**So 1280 nodes in one mesh is reasonable as a cluster size and this fleet is
~5x over the per-core gossip budget at 30 s, about 1.5-3x at 60 s.**

## §6 The four approved items, not yet implemented

Approved by the operator 2026-08-18 after an adversarial review with a second
model. **All four are local; none needs a host.**

1. **Restore `cluster-link-sendbuf-limit` at 1 MB.** `ac90e32a` removed it
   entirely, justified by steady-state N<=200 Docker data - but the M4-4 abort
   measured **31.5 MB/node of link memory during 1280 formation with the 32 KiB
   cap fighting it**, so that justification was exactly the small-N extrapolation
   this document warns about. The cap's defect was its *value*, not its
   existence. A hard host-level bound is not achievable (the cap is **per link**;
   at ~2,558 links/node even 1 MB is a 2.6 GB/node ceiling), so its real job is
   stopping a **single stuck link** running away. 1 MB is ~80x the measured
   average occupancy of 12.6 KB, so it never bites a healthy link, and it is
   Redis's own documented recommended minimum. **This amends `ac90e32a` and
   touches a previously operator-approved decision; say so in the commit.**
2. **Add one shared `is_transient_transport_error(exc)`** - timeout,
   `ConnectionRefused`, `EOFError`, truncated RESP - used **only** by retry and
   redundancy layers. `is_collection_failure` and §12.2's FAIL-before-ERROR
   precedence stay **byte-untouched** for final verdicts.
3. **`TopologyObserver`: substitution, not quorum.** Replace a transiently-failed
   observer with another node **from the same AZ/placement** and re-read;
   `excluded_observer_logical_ids` already half-provides the machinery. Fail only
   when an entire AZ yields no readable observer.
4. **Declare the RTO band change before the 1280 attempt.** Every prior band
   (45-54 s) becomes uncomparable at 60 s; measured ~95 s at exact-50.

### §6.1 Why §12.1 is NOT being changed, and the argument that settled it

The open question was whether a transport timeout should stop being a *semantic*
cluster failure. It should not, but the first reason given for that was wrong and
the correction matters:

- **Wrong**: "the retry layer can key on the row, which already records a
  transport failure." It does not. `_failed_row` labels via
  `is_collection_failure`, and `is_collection_failure(TimeoutError())` is
  **False** - `TimeoutError().errno` is `None`, so it is not in
  `_LOCAL_RESOURCE_ERRNOS`. A timed-out node's row says `failure_kind:
  "semantic"`. **Verified in source.**
- **Also wrong**: tolerating a minority of failed observers. `choose_topology_
  observers` spreads across `az_id` and `placement_id`, so under an AZ partition
  the lost observer is *correlated with the event the redundancy exists to
  catch* - quorum would turn "cannot see AZ-b" into "AZ-b concurs". The current
  all-or-nothing behaviour fails **closed**; quorum fails **open**. Hence item 3
  is substitution.
- **The synthesis that survived**: deciding *which* failures to retry **is**
  classification. The choice is one named predicate or N ad-hoc ones, and this
  codebase already ran the ad-hoc experiment - the narrow
  `except (DockerRuntimeError, TypeError, ValueError)` was a local, slightly
  wrong transient-detector that shipped. Item 2 adds the one predicate on the
  *retry-eligibility* axis and leaves the *verdict* axis alone.

## §7 The stage plan, and where it stands

| stage | what | fleet cost | state |
|---|---|---|---|
| 0 | batch every code change | zero | §6 items outstanding |
| 1 | measure the gossip law on local Docker | zero | **done** (§5.1, §5.2) |
| 2 | prove the config changes at exact-50 on Docker | zero | **done** (§5.3) |
| 3 | **one** paid 1280 run, everything batched | ~1 h of fleet | not started |
| 4 | acceptance pair + baseline-freeze decision | paid | not started |

Stage 3's rule: full instrumentation from the first second, and it either passes
or yields a complete diagnosis. **No "fix one thing and relaunch."**

## §8 Open, and none of it this document's to close

- **Mutations are covered by nothing.** A timed-out `FAILOVER`/`SETSLOT`/`MIGRATE`
  is an *unknown* outcome, not a failed one - the server does not know the client
  left. No classification fixes it and blind retry corrupts state; only
  verify-then-retry per command kind works, and at ~21,900 management rows the
  family will eventually fire. `_retry_read` is deliberately named for reads.
- **Budgets that do not scale with N.** A fixed 5 s on `CLUSTER SHARDS` is a
  different quantile at 1280 than at 50, because the reply is O(N). A budget of
  the form `base + k*N` moves the quantile without masking a sick node.
- **`nodes.conf` fsync storms, unverified.** `clusterSaveConfig` writes the whole
  node table (~200 KB at 1280) and **fsyncs**, driven by
  `clusterDoBeforeSleep(CLUSTER_TODO_SAVE_CONFIG)` from dozens of topology-change
  sites, with 40 nodes sharing one disk and `/tmp` deliberately off tmpfs
  (`ecs_host_prepare.sh` §7, for measurement quality, reversible with
  `--keep-tmpfs`). Free to test: `LATENCY HISTORY cluster-config-fsync` with
  `latency-monitor-threshold` set.
- **`cluster-message-gossip-perc`** reduces per-node work rather than tolerating
  it, but it is `HIDDEN_CONFIG`, absent from upstream docs, and the 10% default
  is what the failure-detection quorum maths is calibrated on. PFAIL nodes are
  gossiped every packet regardless of it. Not to be touched without its own
  evidence, and if ever, at exact-200 where baselines exist.
- Carried from before: `run` not classifying a transport failure; a native run's
  command audit recording no ssh; the aborted controller's ssh masters; the
  resource-to-timeline monotonic correlation; the absent fault-path ownership
  check.

## §9 Two instrument defects, recorded so they are not repeated

- **`used_cpu_user`/`used_cpu_sys` per node is contaminated** by client work and
  by which stage a run is in - it moved *down* from N=50 to N=100. Every number
  in §5.1 rests on the cluster-bus byte counters instead, which are
  stage-independent.
- **A test that reads a function's source text can pass on its own comment.** The
  first version of the `OSError` regression test searched
  `inspect.getsource(...)` for `"OSError"` and passed with the except narrowed,
  because the explanatory comment above it says "OSError". It asserts the parsed
  AST handler now. The mutation check is what caught it - run it, always.
