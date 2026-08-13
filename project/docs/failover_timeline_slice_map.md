# Failover timeline slice map

Scope: make failover/RTO measurement trustworthy and comparable across
200/500/1000/2000 before M4. Not a roadmap item. No new observability
framework - the existing timeline machinery was used where it was already
correct, and only the concrete evidence gap M4 needs was closed.

Read §1 before anything else: the observation points a reader expects to find
are defined in a module that never runs on a real full-flow run, and that fact
shaped every decision here.

## 1. The two failover systems, and the real path uses the other one

`observer/failover_timeline.py` defines `REQUIRED_TIMESTAMPS` -
`target_process_gone_at_ms`, `first_pfail_seen_at_ms`, `first_fail_seen_at_ms`,
`first_promotion_seen_at_ms`, `first_slots_covered_at_ms`,
`first_cluster_ok_at_ms`, `first_client_success_at_ms`,
`clean_snapshot_passed_at_ms` - and `derive_rto_metrics` over them. It is driven
by `scripts/m2_performance_capture.py` and
`scripts/fault_failover_timeline_gate.py`.

**None of it runs on a real full-flow run.** `analysis/summary.py` imports three
constants from it (`FULL_FLOW_FAULT_TYPES`, `FULL_FLOW_SCALE_RUNGS`,
`FULL_FLOW_TIMELINE_METRICS`) and derives no timestamp. Measured against a real
run's `analysis_summary.json`: `kill_to_pfail_ms`, `pfail_to_cluster_ok_ms`,
`first_pfail` and `target_process_gone` are all **absent**.

The real path is `_run_scalable_primary_kill_failover` in `docker_runtime.py`,
which takes a `NodeBackend` and is therefore **identical on `docker_process` and
`native_multi_ecs`**. It instruments three things:

1. `ActuatorRecorder` - `action_start` / `signal_or_request_sent` /
   `action_completed`, each wall and monotonic.
2. `AffectedShardObserver` - 500ms `ROLE` + `CLUSTER INFO` against **only the
   surviving nodes of the affected shard** (one replica at 1 replica/shard).
3. `SentinelLane.fault_probe` - nominally 100ms `GET` of an affected and a
   control canary through `ClusterRouter`.

## 2. What a run emitted, and the two duplicate pairs

`fault_sequence.json`'s `failover_details` carried four numbers, which are two
pairs of duplicates:

```
promotion_latency_ms        = 47654.75  ┐ the same expression:
cluster_recovery_latency_ms = 47654.75  ┘ rounds[-1].monotonic - fault_monotonic
read_unavailability_ms      = 47093.83  ┐ the same sentinel rto_ms; the canary
write_unavailability_ms     = 47093.83  ┘ only issues GET
```

- `promotion_latency_ms` was **not promotion**. It is the last observer round,
  which is the round the §9.3 two-round convergence rule completed. Measured
  across **74 retained runs** it overstates the first observed promotion by
  **0.501-0.519s, median 0.508s, and never by zero** - one observer round.
- It was byte-identical to `cluster_recovery_latency_ms`, so one of the two
  names was definitionally wrong.
- `write_unavailability_ms` was a read number under a write name.

## 3. The evidence was retained; nothing derived it

`scalable_primary_failover_observation.json` retains every observer round with
its full `CLUSTER INFO` - including `cluster_nodes_pfail`, `cluster_nodes_fail`,
`cluster_slots_ok`, `cluster_current_epoch` and the election's
`auth-req_sent`/`auth-ack_received` counters - and every sentinel sample. So the
stage timeline was reconstructible after the fact and simply never was.

Reconstructed over 74 retained runs (9 exact-30, 56 exact-50, 9 exact-200,
including two runs copied into a baseline):

| N | RTO median | process_gone→PFAIL median | **PFAIL→promotion median** | client probe interval |
|---|---|---|---|---|
| 30 | 46.45s | 44.07s | **2.53s** | 106.9ms |
| 50 | 47.69s | 44.16s | **3.80s** | 106.7ms |
| 200 | 49.75s | 43.02s | **8.05s** | **194.1ms** |

**This is why an aggregate RTO cannot be an M4 metric.** The detection term is
flat across a 6.7x change in cluster size while the control-plane term grows
~3.2x, and detection jitter alone (30.4-46.0s) is larger than the entire
control-plane term. `process_gone→PFAIL` is bounded above by ~46s ≈ 1.5 ×
`cluster-node-timeout` (30000ms, applied via `cluster_timeout.py:121`), which is
consistent with Valkey's ping scheduling; that mechanism is *consistent with* the
data rather than proven from Valkey source.

## 4. What the vantage point cannot measure, declared rather than omitted

- **`first_fail` is circular.** `cluster_nodes_fail` is read from the surviving
  replica, and that replica sets it as it promotes itself. Measured: FAIL and
  promotion land in the **same 500ms round in 72 of 74 runs**, and in the other
  two they are exactly one round apart. So this is a proxy for promotion, not an
  observation of FAIL consensus. Finer cadence would not fix it; only a
  primary-side vantage point would, and §7.6/§9.2 do not give this lane one.
- **`first_cluster_ok` never transitions.** `cluster_state` was observed `ok` on
  the survivor for the whole outage in every retained run, because the shard's
  slots stay covered by a node that is pfail but not yet fail.
- **`clean_snapshot` is not the failover tail.** `recovery_validation` runs after
  the killed node is restarted and re-attached.

Both unmeasurable points are now recorded in the artifact with their reason, so a
later reader cannot derive them from a neighbouring field that happens to move.

## 5. The scale-dependent probe bias was a conformance defect, not a design gap

§7.6 requires the fault probe's cost to be "固定开销约为 20 个 `GET/s`，与集群节点
数无关". §14 budgets it `O(1)`. §16 item 8 asks it to reach a 100ms period.

`ClusterRouter.get` built its candidate list as the cached route plus **every
primary**. During an outage the cached route is dead and every live seed answers
MOVED naming that same dead endpoint, so one lookup cost one connect and one GET
per primary. Measured against a fake transport, steady state, per lookup:

| primaries | connects | commands | after promotion |
|---|---|---|---|
| 15 | 15 | 14 | 2 / 2 |
| 100 | 100 | 99 | 2 / 2 |
| 1000 | 1000 | 999 | 2 / 2 |

On real runs that is a 194.0ms round while the outage is open at exact-200
against 106.5ms at exact-50, both falling back to ~103ms once recovered - the
degradation appears only while the outage is open, and grows with primary count. At exact-2000 it would be ~1000
connects and ~999 GETs **per 100ms round**, which makes the probe a load
generator against the failover it is measuring and reproduces the connection
churn `eac9b545` fixed elsewhere.

So this was the code violating three design statements, not the design needing a
change. Two bounds restore it: an endpoint that already failed in a lookup is not
dialled again, and at most `MAX_SEEDS_PER_LOOKUP` (3) distinct seeds are
consulted from a rotating offset. Re-measured: **2 connects and 3 commands per
lookup at every size**, and the promoted owner is still found on the round it
becomes routable, which is the property that keeps the RTO honest.

Rotation means the router eventually holds a persistent connection to each
primary. §14 explicitly sanctions that (`memtier 和 Sentinel 的持久连接数量仍为
O(N)`), and it is strictly better than HEAD, which dialled every primary on
*every* round.

### 5.1 The cadence loss is environment-dependent, and this map first got it wrong

The 194ms measurement is Docker on a laptop. **On the real fleet the pre-fix
probe was already at its period**: derived from the frozen native baselines' own
retained samples, median interval **100.06-100.07ms at exact-50 and at
exact-200**, p90 100.07-100.11ms. The walk's ~199 operations at 100 primaries are
sub-millisecond in-VPC, so they still fit inside a 100ms budget; on the Mac each
operation costs about 1ms and they do not.

So "exact-200 is where it shows" is true of Docker-on-laptop and **false of the
fleet**, and this map said otherwise before the measurement was taken. What
survives is the cost model in the table above, which is a property of the code
rather than of the environment: at 1000 primaries the same walk is ~1999
operations per lookup, roughly ten times the exact-200 work, and that does not
fit a 100ms budget on any network. The fix is **not yet binding at exact-200
in-VPC and becomes binding inside M4's range**, which is the honest claim.

### 5.2 On the fleet the cost lands in the tail, and that is what the fix removes

The median was never the fleet's problem; the **tail** was, and the exact-200
candidate settles it. Probe round intervals, real fleet, 200 nodes:

| | median | p90 | p99 | max | rounds > 125ms |
|---|---|---|---|---|---|
| baseline run-1 | 100.06 | 100.07 | **1098.33** | **1099.51** | **11** |
| baseline run-2 | 100.07 | 100.07 | **1096.47** | **1106.89** | **9** |
| **candidate** | 100.10 | 100.14 | **100.18** | **100.21** | **0** |

Nine to eleven rounds per pre-fix run took about **1.1 seconds**, which is the
`SentinelLane` connect timeout of 1.0s: the walk dialled the dead node once per
seed, roughly a hundred times per lookup, so a dial that hung rather than being
refused was near-certain to be hit somewhere in the walk. The bound dials it
once, and the tail disappears entirely.

**This is the measurement that matters for M4.** A stall inside the recovery
window delays *observed* recovery by up to 1.1s, which is exactly the
quantisation error on the user-visible RTO. It is now bounded at 100.21ms. So the
fix pays for itself on the real fleet at exact-200 after all - through the tail,
not through the median, which is not what §5.1 predicted before it was measured.

Both numbers are now reported by `round_cadence`, so a future run cannot lose
this silently.

## 5a. The headline M4 result, from evidence M3 already had

Derived retroactively from the frozen native baselines - no re-run needed,
because the raw rounds were always retained:

| runs | RTO | detection | **PFAIL→promotion** |
|---|---|---|---|
| native exact-50 ×2 | 48.73s / 47.90s | 42.52s / 45.53s | **6.50s / 2.50s** |
| native exact-200 ×2 | 51.77s / 51.06s | 44.03s / 32.02s | **8.00s / 19.03s** |

**Aggregate RTO differs by about 6% between exact-50 and exact-200 while the
control-plane term differs by up to 7.6x.** That is the whole argument for the
metric: the number M3 reported cannot rank 500/1000/2000, and the number it was
hiding can. Note also that exact-200's control-plane spread (8.0-19.0s) is far
wider than exact-50's (2.5-6.5s), so M4 rungs need more than one run each before
any two are compared.

## 6. Decisions taken, and what decided them

- **The 500ms affected-shard period is unchanged.** §9.2 mandates it and §16
  acceptance item 9 pins it, so changing it is a design amendment rather than a
  session's call. The cost is that `pfail_to_promotion_ms` is known to ±1000ms
  (both endpoints sampled at 500ms). Against a metric that is 2.5-8.0s and grows
  with scale, that is tolerable; it is recorded as `precision_ms` beside every
  interval rather than left implicit. Raising it would need operator approval and
  a design amendment, and is the one change that would sharpen this metric most.
- **No write-recovery probe.** §7.3 states `正式窗口内 Sentinel 不再写入或更新
  canary` and forbids a per-round write protocol, so a write probe is forbidden
  in the formal window, not merely unnecessary. `write_unavailability_ms` is
  therefore `MISSING` with a reason, using the `missing_fields` shape the sibling
  handoff path at `docker_runtime.py:11385` already uses.
- **No second vantage point.** Out of scope as set; the consequence is that
  `first_fail` is dropped as unmeasurable rather than fixed, and said so.

## 7. Metric definitions

All derived from rounds already recorded; nothing new is collected.

| metric | definition | expectation at M4 |
|---|---|---|
| `process_gone_to_pfail_ms` | actuator `action_completed` → first round with `cluster_nodes_pfail > 0` | detection policy; expect flat in N |
| `pfail_to_promotion_ms` | first pfail → first round with `role == primary` | **the control-plane scaling metric** |
| `promotion_to_slots_covered_ms` | promotion → `cluster_slots_ok == 16384` | ≈0 by construction; invariant check |
| `client_unavailable_to_recovered_ms` | first failing canary sample → first of the stable streak | genuine user-visible outage |
| `failure_to_client_recovered_ms` | kill → first of the stable streak | **identical to the legacy `rto_ms`** |

The last one was verified equal to the legacy `rto_ms` in **74 of 74** retained
runs, so M3's frozen results stay comparable with M4's.

Four latency classes are kept apart: Valkey control-plane
(`pfail_to_promotion_ms`), topology propagation (**not measured** - needs a
second vantage point), client recovery (the two client metrics), and observer
sampling delay (`precision_ms` on every interval, plus the probe's measured
`round_cadence`).

## 8. Where each value lives, and why

The derived detail - per-point offsets, sampling bounds, stated absences - lives
in `scalable_primary_failover_observation.json` under `failover_timeline`. Only
the scalars go into `failover_details`, which `fault_sequence.json` carries and
which the stage diff compares field by field; the timeline's per-run round counts
would otherwise have made a diffed stage view non-deterministic. `failover_details`
carries `failover_timeline_ref` to point at the detail.

§11.4 forbids a collected field without an automatic analysis consumer, so the
three new scalars are consumed by `full_flow_result.json`'s `lifecycle_durations`.

`round_cadence` is excluded from the `failover_observation:verdicts` diff view and
added to the `failover_recovery` reported line, which is the boundary `rto_ms`
already sits on: it is what the probe achieved, not what the stage owes.

## 9. Declared deltas

Declared before the runs, not after.

- `fault_matrix` against the frozen exact-50 baseline moves **5/6 → 4/6**, with
  exactly one new differing view: `failover_observation:verdicts`, whose whole
  difference is the `keys` list gaining `failover_timeline`.
- `fault_sequence` already differed (the inherited `85d5096a` partition delta), so
  the count is unchanged, but its delta grows by `write_unavailability_ms`
  `<MEASURED_MS>` → `"MISSING"`, three new `<MEASURED_MS>` keys,
  `failover_timeline_ref` and `missing_fields`.
- `runtime_start`, `cluster_form`, `management_matrix` and `cleanup` must not move
  at all: `ClusterRouter` is constructed only inside `fault_probe`, which has
  exactly one caller.

A third differing view, or movement in any other stage, is a finding.

## 10. Proof

### 10.1 Hermetic

`repository.all` **92/92** on the Mac and **91/92** on the controller, the one
being `product.integration.docker_runtime_contract` against the absent Docker
daemon, which is the recorded and correct state there. pytest tree **815 → 823**;
the eight new checks joined `tests/unit/test_scalable_observability.py`, which the
catalog already registers, so **catalog stays 99 and the M1 plan 91** and no
contract count moved.

### 10.2 Real Docker exact-50, two consecutive at the final code state

**PASS 868.82s** (`gate-20260813T090246Z-4bb41647`) and **PASS 944.98s**
(`gate-20260813T091715Z-e6224598`). Both: `run_verdict` PASS with **12/12 checks
OK** and `tool_errors` empty, no `admission` check (a passing run passes no extra
check, as `940efa13` intended), cleanup PASS with 21 rows, `resources_remaining`
empty and no `cleanup_errors`, fault lane **9 scenarios / 12 command rows / 15
windows** with nine `REAL_PASS`, the string `ERROR` in no artifact, and zero
Docker residue.

Against the frozen baseline both score **`runtime_start` 7/7, `cluster_form` 5/5,
`management_matrix` 6/8, `fault_matrix` 4/6, `cleanup` 2/2** - the declared shape
exactly, with `failover_observation:verdicts`'s whole difference being the `keys`
list gaining `failover_timeline`. **Against each other they are 7/7, 5/5, 8/8,
6/6, 2/2** - identical in every view, including both views that differ from the
baseline.

The end-to-end number did not move: run A's RTO is **47090.555ms against the
baseline's 47093.83ms**, 3ms apart. The stage terms differ between the two runs
the way detection jitter predicts - detect 45.77s / 41.21s, control plane 1.52s /
4.04s - which is the dispersion §3 measured, not an effect of the change.

### 10.3 Real native exact-50 on the eight-host GCE fleet

**PASS 839.72s** (`gate-20260813T090314Z-98272223`). Calibration of the two
frozen native baselines against each other is **6/6**; the candidate scores
**4/6**, both differing views being the declared ones. `fault_sequence` differs
here where it was identical in calibration, because the native baseline carries
no inherited partition delta - so on this backend both differing views are this
change's, and both are declared.

Behaviour did not move, checked against the baselines' own retained rounds:
control plane **4.00s** against their **6.50s** and **2.50s**, and the lower RTO
(44.76s against 48.73s and 47.90s) is fully accounted for by detection at
**41.04s** against their 42.52s and 45.53s.

`write_unavailability_ms` is `MISSING` carrying the §7.3 reason;
`promotion_latency_ms` **45062.826** and `cluster_recovery_latency_ms`
**45563.401** are no longer the same number, separated by one observer round.
Probe cadence median **100.095ms**, p90 100.151ms, **0 overruns**.

### 10.4 Two defects this work's own runs found in this work's own code

Neither was visible to reading or to the hermetic tests; both were caught by
replaying real evidence and reading the reported line.

- **`_failover_point` compared an unrounded offset against an already-rounded
  threshold**, so `promotion_to_slots_covered_ms` skipped the very round that set
  its threshold and reported **511ms** where promotion and full slot coverage
  land in the same round. Now exactly **0.000 in all 74 retained runs**, which is
  the invariant §7 says it should be.
- **`overrun_round_count` fired on 438 of 438 intervals.** A healthy probe sleeps
  off its period and inherits scheduling jitter, measured 100.1-114.9ms against a
  100ms period, so a bare `> period` test counts every round and signals nothing.
  It now uses a tolerance sized on that measurement, giving 0 on healthy runs
  while the 194ms case it exists to catch sits 94% over.

### 10.5 Real native exact-200 on the eight-host GCE fleet

**PASS 1510.33s** (`gate-20260813T092430Z-83460d7d`), against the frozen native
exact-200 baselines' 1462.73s and 1454.44s. Calibration **6/6**, candidate
**4/6** with the two declared views. `run_verdict` PASS **12/12 OK**,
`tool_errors` empty; cleanup PASS with 40 rows, `resources_remaining` empty, no
errors; fault lane **9 / 12 / 15**; **200 of 200** node journals; the string
`ERROR` in **no** artifact; and **0 `valkey-server` and 0 `vslab` firewall rules
on all eight hosts**, asked over ssh from outside the product.

Behaviour did not move: RTO **52.17s** against the baselines' 51.77s and 51.06s,
control plane **9.01s** against their 8.00s and 19.03s, detection 43.55s against
44.03s and 32.02s. `promotion_latency_ms` **52572.026** and
`cluster_recovery_latency_ms` **53072.558** are separated by one observer round
where the baseline reported one number twice.

The probe cadence result is §5.2's, and it is this rung's headline.

### 10.6 An unplanned abort, and what it incidentally proved

The first native exact-200 attempt (`gate-20260813T091947Z-203abf7e`) was killed
by the launch method rather than by the product - `scripts/ecs_gate.py` **execv's
into the CLI**, so a watcher matching `ecs_gate.py` matches nothing once the run
starts, and the detached-launch shape was wrong. It left 25 `valkey-server` per
host. `cli gate cleanup` from that run's `state.json` took all eight hosts to
**0 processes and 0 `vslab` firewall rules**, checked from outside the product
over ssh, with 40 cleanup actions, `resources_remaining` empty and no errors -
item 1.4's ownership machinery working on an abort nobody planned.
