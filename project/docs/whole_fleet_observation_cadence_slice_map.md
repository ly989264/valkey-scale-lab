# M4-1: bringing whole-fleet observation into conformance, measured

Roadmap: not a rung of M4, a precondition for it. M4's target is 1280 nodes on
the eight-host `gce-m3b` fleet; the whole-fleet observation cadence is the one
thing certain to break there, it needs neither quota nor a contract change, and
it can be fixed and proved today at exact-200.

**No baseline was frozen and no frozen baseline was touched.**

## §1 The measurement had to be taken from outside the product

A run's own evidence cannot see this. `LightClusterProbe` speaks RESP over a
pooled connection and never reaches `CommandRecorder`, so **not one whole-fleet
light round appears in a run's command audit**. What the audit does record is
`_process_node_snapshot`'s `CLUSTER INFO` + `CLUSTER NODES` pair, because that
goes through `_node_command`; those are the 1466 `cluster_probe` rows in a real
exact-200 and they are a different lane (§3).

`runtime_timing_breakdown_local_full_flow.json` records
`runtime_all_node_light_probe` with a `count`, but only the setup path threads
`timings` into a wait, and that wait converges on its first round: the count is
**1** in the 8-host control run of 2026-08-15. So the whole-fleet round volume
of this product was, before this item, unmeasured and unmeasurable from its own
artifacts.

The instrument is therefore the one
`observability_connection_scale.md` used: a `sitecustomize.py` on `PYTHONPATH`,
outside the repository, wrapping `LightClusterProbe.collect`,
`TopologyObserver.run`, `FullClusterValidator.run` and the four whole-fleet
entry points in `docker_runtime`, recording one row per round with the product
call chain above it. Its cost is a list append and a stack walk of at most eight
frames per round; the earlier instrumentation that perturbed a run wrapped
`socket.create_connection`, which fires per node per round. It is placed at
`src/sitecustomize.py` on the controller only, because `real.ecs.full-flow`'s
runner argv sets `PYTHONPATH={project_root}/src` and so overrides any other.

**This is itself a finding and it is left open**: the two backends are meant to
be comparable and neither records its observation volume. Closing it means
either routing the light probe through the recorder - which would add ~500,000
rows to an exact-200 command log - or recording round counts in the timing
breakdown. Both are their own change with their own artifact delta.

## §2 What one real exact-200 actually spends

One instrumented run on the eight-host fleet, `gate-20260815T154907Z-b98f66ee`,
**PASS 1380.02 s**, 12/12, at `038dba16` - the state M4-1 started from:

| | |
|---|---|
| whole-fleet 200-node light rounds | **430** |
| RESP commands issued in them | **515,976** |
| `CLUSTER MYSLOTS` bitmap transferred | **176.1 MB** |
| wall clock spent inside them | 18.0 s of 1370 s |

430 rounds in a 1370 s run is one every 3.2 s sustained, and during cluster
formation one every 2.03 s. §4.4 budgets one whole-fleet light round per **60
seconds**, with the N requests rolled evenly across those 60 seconds. The
formation wait was running at **30x** that.

By owner, and the split is what decided the change:

| owner | rounds | shape |
|---|---|---|
| `FullClusterValidator.run` retry, cluster formation | **77** | clock-driven, 0.5 Hz over 156.7 s |
| `_management_topology_snapshot` | **136** | one-off per snapshot, but **two rounds per snapshot** |
| `_management_wait_clean_cluster` | 71 over 58 calls | clock-driven, 1 Hz, but 57 calls returned on their first round |
| `_wait_process_light_clean` in the partition probe | **51** over 3 calls | clock-driven, 1 Hz over 16.7 s each |
| `_management_require_live_topology` | 42 | one-off precondition |
| `_management_matrix_execute_operation` health before/after | 22 | one-off evidence |
| everything else | ~31 | |

Two things fall out of that table that reading the code could not have told you.
**The site named as the worst offender is not the worst offender**:
`_management_wait_clean_cluster` is a 1 Hz whole-fleet loop by construction, and
in a healthy run it costs one round per call - its 58 calls cost 71 rounds, and
one 16.9 s wait accounts for 17 of them. And **the largest single item is not a
loop at all**: `_management_topology_snapshot` takes two whole-fleet rounds
where one would do, which is 32% of every whole-fleet round the run made.

## §3 The `CLUSTER NODES` question, answered and mostly closed already

§16 item 1 forbids the normal path from *periodically* running whole-fleet
`CLUSTER NODES`, and §14 says the same in the negative. That lane is visible in
the command audit, so it was measured from artifacts rather than instrumented,
in the 8-host control run and in both frozen baselines.

A passing exact-200 issues **1466 `CLUSTER NODES`** in 74 bursts. Grouped by how
many distinct nodes each burst covers: 36 bursts of 10 nodes and 22 of 18 - the
rolling-restart health gate, already scoped to representatives plus the batch's
own shards by `49b2e3ab` - and only **two bursts covering all 200 nodes**, plus
one of 102. At exact-50 the frozen baseline shows three whole-fleet bursts, one
of which is ~3 rounds in a row and is the health gate escalating.

So on the normal path this is **not periodic today** and needs no change here.
What remains is latent: `_management_matrix_wait_rolling_restart_health` escalates
to a whole-fleet `_process_node_snapshots_parallel` on *every* non-clean attempt,
at up to 1 Hz, and `CLUSTER NODES` at 1280 nodes returns ~1280 lines per node.
It fires 3-6 times per exact-50 run and never at exact-200. **Reported, not
changed**: it is a different lane with a different failure mode, and CLAUDE.md
already carries it as an open item.

## §4 The tension, and how it was resolved

Both clock-driven sites are **correctness gates**, not telemetry. They block a
stage until the cluster is clean, so their period is not a sampling resolution -
it is how fast a passing stage notices it has passed. A naive 60 s round would
turn a 17 s wait into a minute and add that to every management operation.

The design's 60 s is stated for the *observation* lane: §4.4 is headed 稳定期
频率 and governs the 120 s no-fault stability window, where sampling faster buys
resolution and costs the cluster. §14's complexity table and §16 item 3 are
about aggregate normal-path cost and say nothing about gates. So the design does
not answer the question directly, and the answer taken here is:

> A gate is exempt from §4.4's sampling cadence but not from §14's aggregate
> budget. The rule adopted is that **a gate's whole-fleet round count must be
> bounded by what it is waiting for, not by how long it waits.**

That has a second half which is what makes the change safe:

> **No gate returns on a subset observation.** The cheap observation decides
> *when* to look at the whole fleet; the whole-fleet round decides whether the
> gate passes. The accept condition is byte-identical to what it was, so the
> change cannot make a gate pass on less evidence than before.

## §5 The three changes

### §5.1 A formation retry re-reads the cheap layer (`d6312c00`)

`FullClusterValidator._run_once` ran the whole-fleet light validation and then
the three-observer topology check. Measured in the before-run: over 77 attempts
the light validation passed **77 of 77** and layer 2 raised **77 of 77**, because
what a freshly formed cluster is pending on is a replica an observer has not yet
learned is online - a `CLUSTER SHARDS` health field, which is §6.1's layer and
costs three commands.

So a *retry* reads the cheap layer first. Both layers are still required and the
accept condition is unchanged; only the order moves, and only while waiting. The
first attempt keeps the original order, so a permanent failure the light layer
alone can see is still reported at once instead of being waited out for the full
convergence deadline - which is the property the retry rule's own docstring
promises and the one this could have broken.

**77 → 2 rounds**, measured.

### §5.2 The two clock-driven gates spend a round when it can be the answer (`10b47ac0`)

`_WholeFleetRounds` decides when `_management_wait_clean_cluster` and
`_wait_process_light_clean` may take a whole-fleet round. The first observation
always takes one. After that a round is taken only when the representative set
reports the node-local part of the predicate holding - a whole-fleet clean state
implies a representative-clean one, so the prefilter cannot delay a wait that is
about to end - and never twice inside a backoff doubling from the wait's own
poll period up to `WHOLE_FLEET_RECHECK_SECONDS`.

`_node_local_clean` deliberately omits role counts. They are a property of the
probed set and no subset can evaluate them, so a wait blocked on a role count is
the one shape where the prefilter cannot help and only the backoff bounds the
rate. That is also where the latency cost lands (§7).

**`WHOLE_FLEET_RECHECK_SECONDS = 15.0`, and deliberately not §4.4's 60.** A
sampling cadence can be slowed to 60 s because waiting longer costs only
resolution. A progress gate cannot, because waiting longer costs the run wall
clock, and the worst case here is bounded latency rather than a rate.

**51 → 12** in the partition probe; **71 → 69** in the management wait, which is
the honest number: 57 of its calls already cost one round each and no rule can
make that cheaper.

### §5.3 A topology snapshot observes the fleet once (`7894ca62`)

`_management_cluster_health` and `_management_live_topology` are two derivations
of the same six commands to the same nodes, and `_management_topology_snapshot`
called both. All eleven call sites pass the same node list to both parameters,
checked at HEAD. One round now serves both, which also makes the pair more
consistent than it was: `nodes` and `slots` no longer come from two observations
taken milliseconds apart.

**136 → 68 rounds**, exactly halved.

## §6 The result at exact-200 on eight hosts

`gate-20260815T164843Z-c400007e`, **PASS 1361.69 s**, 12/12, same fleet, same
configuration, same instrument, one commit later:

| | before | after | |
|---|---|---|---|
| run | PASS 1380.02 s | PASS 1361.69 s | **-18.3 s** |
| whole-fleet light rounds | **430** | **238** | **-45%** |
| RESP commands in them | 515,976 | 285,576 | -45% |
| `CLUSTER MYSLOTS` bitmap | 176.1 MB | 97.5 MB | -45% |
| wall clock inside them | 18.0 s | 10.6 s | -41% |
| peak sustained rate (formation) | one per **2.03 s** | one per 62 s | |
| representative prefilter rounds (2 nodes) | 0 | 44 | |

Projected at M4's 1280 nodes, holding the round count: **3.30 M → 1.83 M RESP
commands** and 1.13 GB → 0.63 GB of bitmap through one 4-vCPU controller. The
peak matters more than the total: formation was issuing 1200 commands every
2.03 s at 200 nodes, which is **3783 commands a second at 1280**; the worst case
after the change is one whole-fleet round per 15 s, or 512 a second, and the
common case is one round per convergence rather than one per period.

**What is left, and it is O(1) per operation rather than O(time).** Of the 238
remaining rounds, ~226 are one-off: one per topology snapshot, one per
`require_live_topology` precondition, one per operation's before/after health.
Those grow as O(N) per management operation, which is exactly what §14's
complexity table budgets for the layer-1 check. **After this item no loop in the
product issues whole-fleet rounds at a rate set by a clock.**

## §7 The wall clock, reported rather than buried

The diff tool ignores durations, so a change like this can leave every view
green while making runs slower. It did not, but the parts moved in both
directions and the honest accounting is per gate rather than per run:

| | before | after |
|---|---|---|
| whole run | 1380.02 s | **1361.69 s** |
| `full_validation` total | 169.3 s | 134.7 s |
| `_management_wait_clean_cluster` total | 19.2 s (1 call over 1 round) | 51.4 s (4 calls over 1 round) |
| `_wait_process_light_clean` total | 50.2 s (16.7, 16.7, 16.7) | 67.9 s (20.2, 20.2, 27.2) |

**The gates got slower and the run did not.** The partition probe's three waits
each gained 3.5 to 10.5 s, all inside the 15 s bound the backoff sets. The
management wait's total moved from 19.2 s to 51.4 s, but that is four waits
needing convergence in the second run against one in the first, which is
run-to-run cluster behaviour and not a per-call regression - its 54 fast calls
are 38-44 ms in both. Formation is the term that dominates and it varies far
more than any of this: 156.7 s against 124.4 s between two runs of the same
configuration on the same fleet the same hour.

**Worst case, stated rather than measured**: a run makes 4-7 gate calls that
need convergence, and each can gain up to `WHOLE_FLEET_RECHECK_SECONDS`, so the
bound is about +105 s on a 1380 s run, or +7.6%. `WHOLE_FLEET_RECHECK_SECONDS`
is the single knob and the numbers above are what a later session should move it
on.

## §8 Acceptance: two consecutive real exact-200, and the equivalence diff

Both taken at `e4b0b0af` on the eight-host fleet from the in-VPC controller,
back to back, **with the instrument removed** so they run the product exactly as
committed:

| | candidate 1 | candidate 2 |
|---|---|---|
| invocation | `gate-20260815T171705Z-4a61b7f6` | `gate-20260815T174023Z-9bca9ac6` |
| result | **PASS 1397.60 s** | **PASS 1549.75 s** |
| `run_verdict` | 12/12 OK, `tool_errors` empty | 12/12 OK, `tool_errors` empty |
| fault lane | 9 scenarios / 12 rows / 15 windows, nine `REAL_PASS` | same |
| cleanup | 40 rows, `resources_remaining` empty, no errors | same |
| node journals | 200 / 200 | 200 / 200 |
| `ERROR` in any artifact | none | none |
| primary-kill RTO | 50.56 s | 49.07 s |

Both RTOs are inside the exact-200 spread the fleet already produces
(43.8-53.8 s across every run measured here).

**Calibration first, at this HEAD**, frozen `real-exact-200-c58a762a` run-1
against run-2: `runtime_start` 7/7, `cluster_form` 5/5, `management_matrix`
**7/8**, `fault_matrix` 6/6, `cleanup` 2/2 - reproducing `BASELINE.md` exactly,
so the diff tool has not moved under this item.

Against the frozen baseline's run-1:

| | candidate 1 | candidate 2 | cand-1 vs cand-2 |
|---|---|---|---|
| `runtime_start` | 7/7 | 7/7 | 7/7 |
| `cluster_form` | 5/5 | 5/5 | 5/5 |
| `management_matrix` | **8/8** | 6/8 | 6/8 |
| `fault_matrix` | 4/6 | 4/6 | 5/6 |
| `cleanup` | 2/2 | 2/2 | 2/2 |

**Every differing view is accounted for and none of it is this item's.**

- `fault_matrix` 4/6 is the **2026-08-13 failover/RTO work's declared
  addition**, and the frozen native baselines are `c58a762a` of 2026-08-12,
  which predates it. The delta is `failover_timeline_ref`,
  `pfail_to_promotion_ms`, `process_gone_to_pfail_ms`,
  `client_unavailable_to_recovered_ms` and `write_unavailability_ms` becoming a
  declared `MISSING` with §7.3's reason. `fault_command_log` is **SAME**.
- `management_matrix` at candidate 1 is **8/8** - better than the baseline pair
  calibrates - because `errors_observed_during_operation`, the §14.7 per-run
  observation `BASELINE.md` names, happened to agree. At candidate 2 it is 6/8
  for the reason in §9.
- `cluster_form`'s `runtime_all_node_light_probe` is a REPORTED row, not a
  scored one, and the two frozen runs already disagree on it (count 1 against
  count 15). Candidate 1 records count 1, the same as the baseline. **This
  item's changes move no scored view.**

## §9 What candidate 2 found, and it is not this item's

Candidate 2 ran 152 s longer than candidate 1 and is the only run of seven whose
`management_command_log` differs. One rolling-restart health gate - the
primary-handoff restart of `shard-0000-primary` - **retried 85 times over
116.8 s**, and its first attempt already shows why: `replica_count: 99` against
100, the node it had just restarted not yet seen as a connected replica. The
gate passed, `cluster_state_after_gate: ok`, and no verdict moved.

`_management_matrix_wait_rolling_restart_health` escalates to a **whole-fleet
`_process_node_snapshots_parallel`** on *every* non-clean attempt, and that is
`CLUSTER INFO` + `CLUSTER NODES` per node. Measured in that run's own command
audit:

| | candidate 1 | candidate 2 |
|---|---|---|
| `CLUSTER NODES` commands | 1,442 | **19,150** |
| `CLUSTER NODES` bytes | 36.6 MB | **484.3 MB** |

One `CLUSTER NODES` reply is **25.2 KB** at 200 nodes, and it grows with node
count. So this single gate transferred ~428 MB to learn, 85 times, what its
eight-node scoped probe had already told it on attempt 1.

**This is the latent §16-item-1 violation §3 identified and deliberately left
out of scope, now measured firing.** Three things follow, and they are for the
next item rather than this one:

1. **It is not caused by this item.** The rolling-restart health gate calls
   nothing these three commits touch, and the escalation count is 0 in six of
   seven exact-200 runs spanning both code states - both frozen baselines, the
   8-host control of 2026-08-15, the before-run at `038dba16`, the after-run and
   candidate 1.
2. **It corrects a claim in CLAUDE.md.** `real_fleet_ladder_slice_map.md` §9a
   and `simulated_ladder_slice_map.md` §16.2 both record the escalation as
   happening at exact-50 and **never** at exact-200. It happened at exact-200.
3. **At 1280 nodes this is the run-ending one.** A `CLUSTER NODES` reply scales
   with node count - 25.2 KB at 200 implies ~161 KB at 1280 - so the same 85
   escalations would move 108,800 replies and about **17 GB** through one
   4-vCPU controller in a single health gate. That is the O(N²) topology
   evidence §14 says the normal path must not produce.

The minimal fix has the same shape as §5.2: the scoped probe already detected
the condition, so the whole-fleet diagnostic is a diagnostic and belongs on a
rate floor rather than on every attempt. It was not made *before* the acceptance
runs above, because it would have invalidated them. **The operator approved it
afterwards and it landed at `f26769b3`; §11 is the change and its proof.**

## §11 The escalation, fixed on approval

The diagnostic now runs at most once per `WHOLE_FLEET_RECHECK_SECONDS` - the
same constant §5.2 uses, so there is one number for this rule in the module -
and the first one is still taken at once, because a gate that fails quickly
should still say what the whole fleet looked like.

**Why the rate limit cannot decide anything.** `scoped_nodes` is a subset of
`nodes`, and `_management_matrix_health_from_process_snapshots` reduces every
field with `min` or `max` over what was probed. So a scoped reading that is not
clean cannot become clean by probing more nodes *at the same instant*: probing
more can only lower a `min` and raise a `max`. All the escalation ever added was
a second reading a moment later, and the next attempt takes that one second
later anyway. The gate's own break, on the scoped probe, is untouched.

**One gap the change opened, and closed.** With the in-loop diagnostic no longer
running every second, a cluster settling inside the final
`WHOLE_FLEET_RECHECK_SECONDS` would time out where before a diagnostic a second
later would have ended the gate. So the reading taken on the way out is now
**decisive as well as diagnostic**: it is added to `full_probe_count` and to
`attempts`, and the gate raises only if it too is unclean. That leaves the rate
limit unable to fail a gate that would have passed, and it makes a failure's
message carry the fleet rather than whatever the scoped probe last saw.

### §11.1 What it is worth, measured, projected and declared

**Projected, not measured** - and labelled that way because the escalation fired
once in seven runs and is not reproducible on demand. Candidate 2's own retained
numbers are `retry_count: 85` over `health_gate_wall_ms: 116780.98`. Through the
new rule that gate takes `1 + floor(116.78 / 15) = 8` whole-fleet readings:

| | as it ran | through the new rule |
|---|---|---|
| whole-fleet readings in that gate | 85 | **8** |
| node probes | 17,000 | 1,600 |
| `CLUSTER INFO` + `CLUSTER NODES` | 34,000 | 3,200 |
| bytes at 200 nodes | ~428 MB | ~40 MB |
| bytes at M4's 1280 nodes | ~17 GB | ~1.6 GB |

**Measured hermetically**: a 120 s gate that never clears takes 9 whole-fleet
readings against 120, and a gate whose scoped probe clears at t=5 s still ends
at t=5 s having taken exactly one. Three regression tests, each
mutation-checked. The shared fixture's first version tied `known_nodes` to the
sample size, which made the scoped probe unable to be clean at all and the gate
able to end only on the diagnostic - the very thing under test - and it is
recorded in the helper's docstring rather than quietly corrected.

**Declared artifact delta: none, in any run whose gates converge on their first
scoped probe.** `retry_count: 0` means the branch is never entered, and that is
six of the seven exact-200 runs measured here and both dense runs. The fields
that would move in an escalating run are `health_probe.full_probe_count`,
`node_command_count`, `attempts` and the `stdout_tail` JSON of the health-gate
command row - all of which the `management_command_log` and
`rolling_restart_results` views compare.

### §11.2 Proof on the fleet, and the no-op is exact

Two consecutive real exact-200 at `f26769b3`, `gate-20260816T022357Z-d3613c51`
**PASS 1424.78 s** and `gate-20260816T024742Z-40b02195` **PASS 1546.11 s**. Both
`run_verdict` 12/12 OK with `tool_errors` empty, fault lane 9 / 12 / 15 with
nine `REAL_PASS`, cleanup 40 rows with `resources_remaining` empty, 200 / 200
journals, no `ERROR` in any artifact, RTO 51.06 s and 48.67 s. Zero residue on
all eight hosts asked over ssh from outside. Both runs escalated **zero** times,
so both are the no-op case: `retry_count: 0`, `full_probe_count: 400` and
`representative_probe_count: 948` across their 80 gates, identical to every
non-escalating run of both code states, and `CLUSTER NODES` 1,464 and 1,430
against candidate 1's 1,442.

Against the frozen `real-exact-200-c58a762a` run-1, **both runs score
identically**: `runtime_start` 7/7, `cluster_form` 5/5, `management_matrix`
**7/8**, `fault_matrix` 4/6, `cleanup` 2/2 - and 7/8 is what the frozen pair
scores against *itself*, through the same `management_sequence` field.

**The isolating proof is the diff against M4-1's own candidate 1**, the same
configuration on the same fleet one commit apart, with only this change between
them:

```
runtime_start        7/7   cluster_form  5/5   management_matrix 7/8
fault_matrix         6/6   cleanup       2/2
```

`fault_matrix` **fully identical** and `management_command_log` **SAME**. Reduced
to fields, the entire difference between the two runs is **one boolean**:

```
-  "errors_observed_during_operation": true,
+  "errors_observed_during_operation": false,
```

which is §14.7's per-run observation that `BASELINE.md` already names. The two
rolling restarts' own convergence totals across candidate 1, run 1 and run 2 are
**285.9 / 285.7 / 285.5 s** and **354.4 / 354.2 / 353.7 s** - within 0.4 s and
0.7 s - which is the same statement in the stage that holds the gate.

**Where run 2's extra minute went, since it is not this change.** Its
`management_matrix` is 1047.4 s against run 1's 945.0 s, with `retry_count: 0`
throughout. Its convergence total is 797.4 s against 747.9 s, and the +49.5 s
sits in `remove_replica`, `remove_failed_node`, `remove_primary_*` and
`add_replica` - the four operations that call `_management_wait_clean_cluster`.
That is **M4-1's own declared role-count cost** of §10.2, one call at a time and
each bounded by `WHOLE_FLEET_RECHECK_SECONDS`, and it is the reason that knob is
named there as the thing to move next.

## §10 The same at 4x density, which is where the cost shows

`templates/configs/real_ecs_200_2host.yaml` packs the same 200 nodes onto two
hosts - 100 per host, 50 per vCPU, the densest shape the 200-node cap admits and
the closest available stand-in for M4's 80 per vCPU. Its before-numbers are the
three runs of `m4_density_calibration.md`, taken at `52033375` on 2026-08-15.

Two runs at `e4b0b0af`, `gate-20260815T181348Z-74875ed0` **PASS 2291.79 s** and
`gate-20260815T185200Z-297a8303` **PASS 2215.06 s**. Both 12/12 with
`tool_errors` empty, fault lane 9 / 12 / 15 with nine `REAL_PASS`, cleanup 10
rows with `resources_remaining` empty, 200 / 200 journals, and the string
`ERROR` in no artifact. Whole-fleet light rounds **234 and 235**, against the
238 measured at eight hosts - the round count is a property of the code, not of
the density, which is what it should be.

### §10.1 The wall clock did move here, and this is the finding

| stage | before (2 runs, `52033375`) | after (2 runs, `e4b0b0af`) |
|---|---|---|
| `runtime_start` | 7.3, 6.4 | 6.3, 7.0 |
| `cluster_form` | 85.9, 46.9 | **141.8**, 61.9 |
| `management_matrix` | 1549.3, 1565.9 | **1578.9, 1651.7** |
| `fault_matrix` | 288.0, 306.5 | **344.3, 311.8** |
| `cleanup` | 3.1, 3.2 | 3.6, 3.5 |
| whole run | 2055.87, 2086.26 | **2291.79, 2215.06** |

**+129 s and +236 s, or +6% to +11%.** Both stages that hold a changed gate are
above both before-values: `management_matrix` holds
`_management_wait_clean_cluster` and `fault_matrix` holds the partition probe's
`_wait_process_light_clean`. Measured inside them: the management wait totals
47.6 s and 68.7 s across its 58 calls (54 of which are 37-41 ms in both runs, as
before), and the partition waits total 99.8 s and 61.8 s.

**At eight hosts the same comparison finds nothing**, and that contrast is the
useful part:

| stage | old code, 4 runs | new code, 3 runs |
|---|---|---|
| `runtime_start` | 4.6 4.6 4.6 4.6 | 4.8 4.7 4.6 |
| `cluster_form` | 52.0 72.1 10.9 11.4 | 11.3 48.1 71.4 |
| `management_matrix` | 931.2 930.2 905.9 911.3 | 910.6 923.4 1034.3* |
| `fault_matrix` | 279.6 299.6 286.7 278.0 | 291.7 287.8 285.4 |
| `cleanup` | 9.7 8.9 11.0 9.5 | 10.3 8.8 9.6 |

*1034.3 is candidate 2, whose §9 escalation accounts for 116.8 s of it; without
it, 917.5 and inside the range. **Every other stage of every new-code run at
eight hosts is inside the range the same fleet already produced.**

### §10.2 Where the added time goes, exactly

All of it is the role-count case of §5.2. When the whole-fleet round fails
because a node-local fact is wrong, the representative prefilter sees the same
thing and correctly blocks the next round until it clears, so the wait ends one
poll after the cluster does. When it fails only on `primary_count` or
`replica_count` - a property of the probed set that no subset can evaluate - the
prefilter says clean every time and only the backoff bounds the rate, so the
wait can end up to `WHOLE_FLEET_RECHECK_SECONDS` late. Four or five waits per run
are in that state; at 15 s each that is the +129 to +236 s observed.

**`cluster_form` is not this**, and it can be shown rather than argued.
Formation is `attempts x convergence_poll_seconds`, and the measured per-attempt
period is unchanged: 77 attempts over 156.7 s before, 63 over 124.4 s after, 107
over 212.4 s at density - **2.03, 1.97 and 1.99 s**. The change removes ~40 ms
of whole-fleet round from a 2 s cycle and cannot move the number of attempts,
which is the cluster's own. Formation at two hosts measured 46.9, 85.9, 61.9 and
141.8 s across the four runs of both code states, a 3x spread either side.

**Two ways to remove the cost, neither taken here.** Lower
`WHOLE_FLEET_RECHECK_SECONDS`: at 5 s the added latency is a third and the
whole-fleet round count roughly doubles, which at 1280 nodes is 77k commands per
long gate against 38k - both far under the 338k a 1 Hz loop would spend. Or make
the prefilter complete, by reading global role counts from the observers'
`CLUSTER SHARDS` - §6.1's own layer, three commands - which would remove the
role-count blind spot entirely and with it essentially all of the added latency.
The second is the better change and it is a new observation on a gate's path, so
it wants its own evidence.

### §10.3 One number to watch

Dense run 1's primary-kill RTO is **55.27 s**, above the 43.8-53.8 s spread every
prior exact-200 on this fleet has produced; dense run 2 is 48.96 s and inside it.
Recorded, not treated as a finding - one value outside a spread is not a shifted
spread, and the two before-runs at this density measured 46.66 and 46.27 s. A
second dense run above 54 s would make it one.
