# MR-3 slice map: the fleet's first multi-replica evidence

Stage MR-3 of `multi_replica_support_map.md` §8, on the operator's real gce-m3b
fleet. Scope as given: write the two native multi-replica configurations, then
take one native 25×1-50 control, two native 10×4-50 candidates and one native
40×4-200. **No baseline was frozen** - the M3 rule and support map §8 leave
multi-replica baselines to M4's first runs.

Where this map and `multi_replica_support_map.md` disagree, this one wins, and
where it and `multi_replica_mr2_slice_map.md` disagree it says so explicitly:
MR-1 corrected the support map's central arithmetic, MR-2 corrected two of its
predictions, and this rung corrects one of MR-2's own - §6.2, which is the
result a reader should carry forward.

Everything below was run from the in-VPC controller, never the workstation. The
fleet manifest, the frozen native baselines and the fleet's only route all live
there, and a baseline-grade measurement taken over a laptop's 110 ms transport
could not be reproduced.

## §1 What each run can and cannot say

| leg | question | how it is read |
|---|---|---|
| control 25×1 vs frozen `real-exact-50-c58a762a` | did anything drift in the many commits since the baselines were frozen | a **score**, against the marks the baseline's own `BASELINE.md` pins |
| candidate vs control | what does the replica count itself move | a **delta table** against the declared predictions, plus a **vocabulary** comparison; never a score |
| candidate 1 vs candidate 2 | is a native multi-replica run deterministic | every view identical - and §7 is where it is not |
| 40×4-200 | does any of it change at fleet width | the same delta table, plus what only 200 nodes can show |

**The control was taken and it earned its place twice.** The frozen native
baselines are at `c58a762a`, which is item 1.7, the admission check, the
2026-08-13 failover/RTO work, MR-1's nine commits and MR-2's three ago. Without
a control every delta would have had two possible causes. It also found the
tooling defect in §3, which would otherwise have been read as a rung-A finding.

**Scores are meaningless candidate-to-control** and were not used as evidence:
measured, the candidate scores `runtime_start` 1/7, `cluster_form` 2/5,
`management_matrix` 2/8, `fault_matrix` 2/6, `cleanup` 1/2 against the control,
because the shape differs in every view the knob and the replica count move.
§6.3 is the instrument that works across a shape change.

## §2 The two configurations, and the decisions stated in them

`templates/configs/real_ecs_10x4_50.yaml` and
`templates/configs/real_ecs_40x4_200.yaml`, commit `26613317`. Each is its
one-replica sibling with only the lines that carry the shape changed.

**The 50's knob is `nodehosts_per_az: 4`**, and the file states it. Compiled at
`3b399469` and again at this HEAD through `validate_semantics`,
`build_cluster_plan` *and* the run path (`_node_specs` + `_process_nodehosts`,
which MR-1 §1 established is the authority), against the real fleet manifest:

| shape | knob | nodehosts = hosts | per nodehost | colliding | shard AZ split | fleet |
|---|---|---|---|---|---|---|
| **native 10×4-50** | `nodehosts_per_az: 4` | **8** | 7,7,6,6,6,6,6,6 | **0/10** | 3/2 ×10 | 25/25 |
| native 10×4-50 | shipped (2) | 6 | 9,9,8,8,8,8 | 0/10 | 3/2 | 25/25 |
| **native 40×4-200** | shipped | **8** | 25 × 8 | **0/40** | 3/2 ×40 | 100/100 |
| *ref* `real_ecs_50` 25×1 | shipped | 4 | 13,13,12,12 | 0/25 | 1/1 | 25/25 |
| *ref* `real_ecs_200` 100×1 | shipped | 8 | 25 × 8 | 0/100 | 1/1 | 100/100 |

Rung A at 4/AZ reproduces MR-2's Docker layout exactly - the same 8 nodehosts
holding 7,7,6,6,6,6,6,6 - so the two rungs are diffable in the four views the
knob moves, and rung B lands on the same eight nodehosts at shipped knobs. The
§7.1 placement policy is observed at four replicas on real hosts for the first
time: every shard 3/2 and the fleet exactly even, at both scales.

**The 200 keeps `profile_name: scale_200`, because that string is a key rather
than a description.** `_is_exact_200_bounded_exception` is implemented three
times over (`planner/plan.py:296`, `resource.py:344`,
`runtime/docker_runtime.py:1065`) and carries no shard-shape term, so 40×4 rides
the existing exception: compiled, the plan reports
`exact_200_bounded_exception: true`. Renaming it would have turned rung B into a
plan-time refusal discovered after the fleet was up, and widening the guard to
accept a new name would be a semantic change to a validation contract - the
operator's call, not a rung's. The bare validator's `NODE_CAP_EXCEEDED` is the
same answer the shipped `real_ecs_200.yaml` gives and is the normal state.

**The 50's `profile_name` differs from its control's**, deliberately.
`real_ecs_50.yaml` keeps `native_50` so no field moves for readability, but a
25×1 name on a 10×4 run would be actively wrong. Nothing keys on it at 50 nodes;
it lands in three known fields, declared in the file rather than found in a diff.

## §3 A tooling defect the control found, which no product run could have

**The control scored `runtime_start` 3/7 and `cleanup` 1/2 against a baseline
that calibrates 7/7 and 2/2 against itself**, and the entire difference in both,
every hunk of it, was one string: `001-real.local.full-flow` against
`001-real.ecs.full-flow` inside artifact paths.

The Gate names each selected test's directory `NNN-<test-id>`, so an artifact
path records which catalog entry was invoked. `diff_stage_artifacts.py` scrubbed
the gate run id and the artifacts root and not that segment. The frozen native
baselines were taken through `real.local.full-flow`; **every acceptance run since
item 1.7 registered `real.ecs.*` is taken through `real.ecs.full-flow`**, so two
stages would have reported a delta on every future native candidate for a reason
no product change could remove.

Measured before changing anything: rewriting that one name in a copy of the
candidate and re-diffing gives **7/7 and 2/2 with nothing else moving**. Fixed at
`f9b10814` by scrubbing it to `<GATE_TEST>`, anchored on the `<GATE_RUN>/` token
the existing substitution already produces, so it can only ever match the Gate's
own run-scoped directory. Both call sites now share one definition.

**Calibration alone would not have justified it, so four regressions were seeded
into a copy of the passing control and each was required to be caught by the view
that owns it:** a node config artifact pointing at the wrong node's file (6/7), a
residual scan reporting `found: 1` (1/2), a changed `effective_io_threads` (6/7),
and - the one this change could have broken - an `artifacts_dir` pointing outside
the run's own test directory (1/2). The unseeded copy stays 7/7 and 2/2.

This is a defect in the acceptance instrument, not in the product, and it is
worth naming as such: it would have been read as MR-3's first finding.

## §4 The control, and the drift answer

`gate-20260814T122756Z-575caf8f`, **PASS 889.15 s**, `real_ecs_50.yaml`, four of
eight hosts.

- `run_verdict` **PASS, 12/12 checks OK**, `tool_errors` empty, 12 lifecycle
  steps PASS.
- Fault lane **9 scenarios / 12 command rows / 15 windows**, nine `REAL_PASS`.
- `cleanup_report` **20 rows** in four kinds, `resources_remaining` and
  `cleanup_errors` empty, all four residual scans `found: 0`.
- `management_command_log` **1606 rows**; rolling restart **14 batches, max
  concurrent 4** on both operations; Sentinel `canary_count` **25**;
  `cluster-allow-replica-migration` in **zero** of the 50 node configs, which is
  MR-1's conditional emission holding at r=1.
- 50 of 50 node journals; `host_evidence` PASS over 4 nodehosts, each with a
  `host_id` and two clock readings; offsets **+4.99 to +5.51 ms** inside bounds
  of **6.5-7.5 ms**.
- The string `ERROR` in **no** artifact.

| stage | baseline self-calibration | control |
|---|---|---|
| `runtime_start` | 7/7 | **7/7** |
| `cluster_form` | 5/5 | **5/5** |
| `management_matrix` | 6/8 (cannot self-calibrate) | **6/8** |
| `fault_matrix` | 6/6 | **4/6** |
| `cleanup` | 2/2 | **2/2** |

`fault_matrix` 4/6 is the 2026-08-13 failover/RTO work's declared delta, at its
declared shape: exactly two differing views, `fault_sequence` and
`failover_observation:verdicts`, and no third. Everything else is unmoved.
**No control mark moved**, so nothing drifted in the many commits since the
baselines were frozen, and every delta rung A shows is the replica count's.

## §5 Rung A: two native 10×4-50

`gate-20260814T124801Z-4ef89812` **PASS 701.21 s** and
`gate-20260814T130202Z-f2e11200` **PASS 718.49 s** - the fleet's first
multi-replica runs. Both: `run_verdict` **PASS 12/12 OK**, `tool_errors` empty,
12 steps PASS, fault lane **9/12/15** with nine `REAL_PASS`,
`resources_remaining` and `cleanup_errors` empty, every residual scan `found: 0`,
50 of 50 journals, `host_evidence` PASS over **8** nodehosts each with a
`host_id` and two clock readings, and the string `ERROR` in **no** artifact.

### §5.1 Every declared quantity, measured

| quantity | prediction | control 25×1 | cand 1 | cand 2 |
|---|---|---|---|---|
| nodehosts / hosts | 8 | 4 | **8** | **8** |
| `management_command_log` rows | ≈956 by the row law | 1606 | **958** | **958** |
| rolling-restart batches, each operation | 10 | 14 | **10** | **10** |
| max concurrent restarts | 8 | 4 | **8** | **8** |
| `cleanup_actions` rows | **40**, not 41 - see below | 20 | **40** | **40** |
| Sentinel `canary_count` = shard count | 10 | 25 | **10** | **10** |
| node configs carrying the §2.4 pin | 50 | 0 | **50** | **50** |
| fault lane | 9/12/15 invariant | 9/12/15 | **9/12/15** | **9/12/15** |

The row law predicted 956 and both runs measured **958** - the same two-row miss
MR-2 measured on Docker, so the law's error is a property of the law and not of
the runtime. The batch geometry was compiled in advance through the real batcher,
which reproduces the frozen baseline exactly (14 batches / max 4), and matched.

**One inherited prediction was wrong and it was the handover's, not a run's.**
The table MR-3 was given says `cleanup_actions` = 41 rows at both rungs. That is
the *Docker* law, `5×nodehosts+1`, whose `+1` is the network-remove row. A native
run emits no network row - five rows per nodehost and nothing else - which the
frozen native baselines already say: **20 rows at 4 nodehosts and 40 at 8**.
Corrected before running rather than discovered in a diff; both rungs measured
**40**, in the four kinds `nodehost_valkey_processes`, `nodehost_firewall_rules`,
`nodehost_run_state` and `nodehost_residual_scan`.

### §5.2 Support map §3.1 was exercised for the first time, and did not fire

§3.1 predicts an intermittent failure of the down-window full validation, which
runs with `require_replica_connected=True` and `convergence_timeout=0.0`
exempting only the killed node: vacuous at one replica, and meeting three
siblings mid-reattach at four. MR-2 could not observe it, because a different
defect stopped the observer ever reaching a candidate.

Here it ran, and the artifacts say so rather than implying it. In both
candidates the observer reached a candidate in **2 rounds**, called
`full_validation`, and it validated **49 nodes** - every node but the killed one -
with the affected shard holding one promoted primary and **three siblings
re-attaching to it**. Both returned `status: OK`. The control's own affected
shard has exactly one survivor, so the check is vacuous there, which is the r=1
behaviour §3.1 describes.

So the hazard has now been met on a real network with real latency, twice, and
did not fire. **That is not a disproof** - it is intermittent by nature and four
observations across two environments is not a probability - but it is the first
evidence of any kind, and it is stronger evidence than MR-2's because MR-2's
never reached the check under contention. The discriminating message
(`formal full validation did not confirm failover convergence`) appears in no run.

### §5.3 Support map §3.2 is now observed on the real fleet, three ways

`replacement_logical_id` is written before the kill as the target shard's first
replica, and both candidates record `shard-0001-replica-00`. The observed winner
was **`shard-0001-replica-01`** in candidate 1 and **`shard-0001-replica-02`** in
candidate 2 - so across MR-2's two runs and MR-3's two, the prediction has now
been wrong three times out of four, with nothing failing. Left untouched by
instruction; this rung's contribution is that it happens on the real fleet too
and that a *third* distinct replica can win.

## §6 What the replica count actually moved

### §6.1 Founding data, compared against nothing

Every r=1 figure below was **re-derived from the frozen baselines' own retained
rounds** through `_derive_failover_timeline`, not quoted from prose, so the two
columns are the same measurement. The baselines predate `failover_timeline`, and
the fact that they can be re-read at all is the property the 2026-08-13 work was
built on.

| measurement | frozen r=1 exact-50 | control 25×1 | cand 1 10×4 | cand 2 10×4 | frozen r=1 exact-200 | **rung B 40×4** |
|---|---|---|---|---|---|---|
| **RTO** | 48.73, 47.90 s | 45.56 s | **46.36 s** | **46.67 s** | 51.77, 51.06 s | **49.98 s** |
| process gone → PFAIL | 42.52, 45.53 s | 42.53 s | 40.62 s | 36.18 s | 44.03, 32.02 s | 45.16 s |
| **PFAIL → promotion** | 6.50, 2.50 s | 3.00 s | **6.02 s** | **10.55 s** | 8.00, 19.03 s | **5.02 s** |
| promotion → slots covered | - | 0.000 s | 0.000 s | 0.000 s | - | 0.000 s |
| **formation dwell** | 47.4, 53.4 s | 22.33 s | **19.29 s** | **10.29 s** | 52.0, 72.1 s | **67.40 s** |
| probe cadence median | - | 100.10 ms | 100.10 ms | 100.10 ms | - | 100.10 ms |

RTO at exact-200 is **49.98 s**, inside the 47.6-53.8 s exact-200 spread, so
`simulated_ladder_slice_map.md` §15.6's watch item does not fire. `promotion →
slots covered` is 0.000 s in all four runs, which is the invariant the
2026-08-13 rounding fix restored, now also true at four replicas.

### §6.2 MR-2's central founding claim does not transfer, and the honest reason is variance

MR-2 §6 recorded PFAIL → promotion as **1.5-5.1 s at four replicas against
18.2 s at one** and read it as "four candidates elect faster than one, which is
the direction the support map guessed". Measured here against r=1 numbers derived
the same way on the same hosts:

| | r=1 | r=4 |
|---|---|---|
| exact-50 | 2.50, 3.00, 6.50 s | **6.02, 10.55 s** |
| exact-200 | 8.00, 19.03 s | **5.02 s** |

**The direction reverses with scale.** At 50 nodes r=4 sits at or above the top
of the r=1 range - candidate 2's 10.55 s is the largest control-plane term ever
measured at exact-50 in this project - and at 200 nodes it sits well below it.
So MR-2's claim holds at 200 and fails at 50, which means it is not a claim about
the replica count at all.

What MR-2 measured was not wrong; its *comparator* was. An 18.2 s r=1
control-plane term is a Docker-on-a-workstation number, and it has no counterpart
on this fleet, where r=1 at exact-50 is 2.5-6.5 s.

The narrow statement this rung supports, and it should not be widened:

> **The replica count's effect on election time is not established.** The r=1
> spread at each scale (2.5-6.5 s at 50, 8.0-19.0 s at 200) is wider than any
> gap to the r=4 points, and there are two or three runs per cell. What *is*
> visible is that r=1's control-plane term grows with node count while r=4's
> three points show no such growth - a hypothesis worth a designed experiment,
> not a result.

**This rung is itself an instance of the problem the failover/RTO work warned M4
about.** That work's closing note says one run per rung cannot separate 500 from
1000 and that several per rung must be budgeted. Here two runs of an *identical*
configuration produced 6.02 s and 10.55 s - a factor of 1.75 - while the
aggregate RTO they sit inside moved 0.3 %. Any M4 ranking built on single runs
will measure its own variance.

The one thing every leg agrees on: **the aggregate hides the term that moves.**
RTO across control and both candidates is 45.56 / 46.36 / 46.67 s, under 2.5 %,
while the term underneath it moves by a factor of 3.5. Rank on the split.

**Formation dwell does not reproduce MR-2's reading either.** MR-2 found dwell
dominated by shard count - 19-22 s at ten shards against 73 s at twenty-five, at
the same 50 nodes on Docker. Here twenty-five shards form in **22.33 s** and ten
in 19.29 s and 10.29 s: the same ten-shard range, but the twenty-five-shard
number is a third of Docker's, so most of MR-2's contrast was the workstation
rather than the shard count. Four-way sync fan-in cost nothing measurable at
either scale, and the 240 s no-progress window was never approached - the worst
dwell here is rung B's 67.40 s, inside the frozen exact-200 baselines' 52.0-72.1 s.

### §6.3 Nothing undeclared, measured as a vocabulary comparison

A score cannot compare two runs whose shape differs, so every artifact of every
run was reduced to its set of generalised key paths - list indices collapsed,
logical ids, nodehost ids, node ids and integers generalised - and the sets
compared. 38 artifacts, ~3,920 paths each.

**Control against candidate 2: one path differs**, a `CLUSTER INFO` counter.
Control against candidate 1: 17, all of the same family. And the result that
settles what that family is: **candidate 1 against candidate 2 - the same
configuration, run twice, an hour apart - differs in 16 paths**, more than the
control differs from a candidate.

So the differing paths are not a function of the replica count at all. Every one
is either a `cluster_stats_messages_<type>_sent`/`_received` counter, which Valkey
emits only once it has sent a message of that type, or
`sentinel_fault_probe.samples[].errors.control`. Both are MR-2 §5.3's
observations, confirmed on a second runtime and sharpened: MR-2 saw
`update_sent`/`_received` flap; here `fail_sent` and `meet_sent` flap the same
way. The control-canary error is 1 sample of 473, `CLUSTERDOWN`, probe status OK -
the control canary belongs to a shard that is not being failed over, and
CLUSTERDOWN is fleet-wide while any shard's slots have no owner.

**The replica count moved values, not shapes.**

## §7 Determinism, and where it does not hold

| stage | cand 1 vs cand 2 |
|---|---|
| `runtime_start` | **7/7 identical** |
| `cluster_form` | **5/5 identical** |
| `management_matrix` | **6/8** - the environment's, not the shape's |
| `fault_matrix` | **3/6** - see below |
| `cleanup` | **2/2 identical** |

**MR-2 §7's result reproduces exactly on the real fleet.** The two candidates
elected different replicas, so `fault_matrix` scores **3/6** while the rest is
identical, and the tool's whole `fault_command_log` delta is **a single token**:

    -      "<node:shard-0001-replica-01>"
    +      "<node:shard-0001-replica-02>"

in the `CLUSTER REPLICATE` that restores the killed primary as a replica.
`fault_sequence` and `failover_observation:verdicts` differ for the same one
cause and for nothing else.

**`management_matrix` 6/8 candidate-to-candidate is the fleet, not the replica
count**, and this is checked at field level rather than assumed. The two
differing views are `management_sequence` and `management_command_log`, and the
differing paths are exactly two: `[].stdout_tail` and
`result.operations[].workload_impact.errors_observed_during_operation`. Those are
the same two views and the same two fields the frozen baseline's **own**
run-1-against-run-2 calibration differs in - `BASELINE.md` names both. MR-2's
Docker candidates scored 8/8 here because a workstation's rolling restart does
not retry its health gate.

So a native multi-replica baseline could not be calibrated
candidate-to-candidate in **either** `fault_matrix` or `management_matrix`, and
whoever freezes one in M4 must plan its acceptance on the field-level delta and
on which node the artifacts agree about, not on those two view scores.

### §7.1 The field that makes it so, and a prior claim it corrects

`stdout_tail` on the `rolling_restart_health_probe_summary` rows is the
health-gate retry record, and counting it properly answers - for free, from runs
taken for another purpose - part of a carried-forward open question. Counted as
gates whose `probe_summary.attempts[]` holds more than one attempt:

| | r=1 | r=4 |
|---|---|---|
| exact-50 | 2/44, 4/44 (frozen), **5/44** (control) | **1/26**, **3/26** |
| exact-200 | **0/80** (frozen) | **0/64** |

So `simulated_ladder_slice_map.md` §16.2's inversion with scale holds - the
escalation happens at 50 and never at 200 - and **the replica count is not a
variable in it**. Nothing here is MR-3's to close.

**One prior claim needs correcting, and the frozen baselines correct it.**
`real_fleet_ladder_slice_map.md` §9a states that the real fleet escalates but
"never once reaches the diagnostic round", counted on
`sample_scope: all_nodes_diagnostic`. That counter reads zero because
**`stdout_tail.sample_scope` names the scope of the *last* attempt**, which is
the representative one on a gate that eventually passes; the escalated attempt
is only visible in `probe_summary.attempts[]`. Read there, the frozen real
baselines themselves reach `all_nodes_diagnostic` **2 and 4 times**, and today's
runs 5, 1 and 3 times. So the real fleet does reach the diagnostic round, the
simulated/real severity difference §9a drew is not supported by the field it was
drawn from, and the harness is no longer the surviving candidate for it. Two
records of the same event with different scopes is the defect underneath;
whoever takes up §16.2 owns it.

## §8 Rung B: native 40×4-200

`gate-20260814T131546Z-80d568cb`, **PASS 1146.58 s**, all eight hosts, 200 of
200 nodes. `run_verdict` **PASS 12/12 OK**, `tool_errors` empty, 12 steps PASS,
fault lane **9/12/15** with nine `REAL_PASS`, `resources_remaining` and
`cleanup_errors` empty, every one of the eight residual scans `found: 0`,
**200 of 200** node journals, `host_evidence` PASS over 8 nodehosts each with a
`host_id` and two clock readings, and the string `ERROR` in **no** artifact.

The bounded exception carried the shape as compiled: the run was admitted, and
`resource_preflight` records `profile_name: scale_200` with
`bounded_exception_nodes: 200` against 200 planned nodes.

### §8.1 The declared quantities at fleet width

| quantity | prediction | measured |
|---|---|---|
| nodehosts / hosts | 8 | **8**, 25 nodes each |
| `management_command_log` rows | ≈3480 by the row law, ±3% | **3456** (0.7 % under) |
| rolling-restart batches, each operation | 26 | **26** |
| max concurrent restarts | 8 | **8** |
| `cleanup_actions` rows | 40 | **40** |
| Sentinel `canary_count` = shard count | 40 | **40** |
| node configs carrying the §2.4 pin | 200 | **200** |
| fault lane | 9/12/15 invariant | **9/12/15** |

The row law's error changes sign with shape - two rows over at 10×4-50, 24 under
at 40×4-200, 186 over at the frozen 100×1-200 - so it is a sizing estimate and
not a contract. Every other quantity is exact.

### §8.2 The delta does not grow with fleet width

Against the frozen **100×1-200** baseline, the vocabulary comparison over 38
artifacts returns paths in exactly **three** groups, and the replica count is
none of them:

1. the 2026-08-13 failover/RTO work's `failover_timeline`, its refs in
   `analysis_summary`, `events.jsonl` and `fault_sequence`, its
   `missing_fields`, and `sentinel_fault_probe.round_cadence` - all declared by
   that work and absent from a baseline frozen before it;
2. MR-1's declared constraint rename, `constraints.primary_replica_distinct_az`
   → `constraints.shard_az_balanced`, appearing on a 200-node native run for the
   first time;
3. nothing else.

**So four replicas add no path at 200 nodes that the one-replica 200-node
baseline lacks.**

Rung A candidate 2 against rung B - the same shape at 50 and at 200 - differs in
15 paths, and each is either the exact-200 bounded exception writing its own
evidence (`resource_preflight.checks[].details.profile_name`,
`.scale_profile.*`, `.dry_run`, `.capability_id`, `.scenario_name`, and
`cluster_plan.constraints.selected_capability_id`/`selected_scenario_id`), or a
per-run field whose *presence* flaps. The flapping pair worth naming is
`timings[].details.last_attempt_kind`/`last_attempt_error`, the formation light
probe's retry record: it is present in **both** frozen baselines at both scales
and in rung B, and absent only from rung A's two runs, whose formation was fast
enough not to retry. Reading it as a 200-node property would be wrong; it is a
per-run observation, the same family as §6.3's counters.

### §8.3 Evidence volume

200 journals, **80 MB**, in a 192 MB run - against M3-A-6's 86.8 MB and 192.6 MB
for a 200-node one-replica run. So journal volume tracks node count and is
untouched by how those nodes are divided into shards, which is what M3-A-6's
"a node's log is dominated by gossip about peers" predicts.

## §9 Proof

### §9.1 From outside the product

All eight hosts asked directly over ssh from the controller, after all four runs
had completed - not from `cleanup_report`, which is the product's own account:

| checked | every host |
|---|---|
| `valkey-server` processes | **0** |
| `vslab` firewall rules | **0** |
| `VSLAB-*` chains | **0** |
| run trees under `/tmp/valkey-scale-lab/` | **0** |
| `/tmp/vslab-bundle-*` | **0** |

`/tmp/vslab-load-lane` is present and **empty** on one host and absent on the
others - unchanged from what `m3_acceptance_registration_map.md` §5.1 recorded,
and still the fixed root above the run-scoped parent that item 1.5 made the lane
remove. Nothing on the host attributes it to a run, which is why the residue scan
does not report it and why `found: 0` is truthful rather than convenient. No
`/tmp/vslab-resource-agent` root exists anywhere, which is item 1.4's move
holding.

### §9.2 Hermetic and counts

- `./gate suite repository.all` **92/92** on the Mac and **91/92** on the
  controller, the one being `product.integration.docker_runtime_contract`
  against the absent Docker daemon, which is the recorded and correct state
  there.
- **Catalog stays 99, the M1 plan 91, and the pytest tree 849.** Nothing was
  registered: `real.ecs.full-flow` takes `nodes` and `config` and admits 30..200,
  so both rungs are parameter changes.
- `scripts/assert_execution_axis_contract.py` PASS.
- The diff-tool change is proven by four seeded regressions (§3), not by
  calibration.

### §9.3 Runs

| run | shape | result |
|---|---|---|
| `gate-20260814T122756Z-575caf8f` | 25×1-50 control | **PASS 889.15 s** |
| `gate-20260814T124801Z-4ef89812` | 10×4-50 candidate 1 | **PASS 701.21 s** |
| `gate-20260814T130202Z-f2e11200` | 10×4-50 candidate 2 | **PASS 718.49 s** |
| `gate-20260814T131546Z-80d568cb` | 40×4-200 rung B | **PASS 1146.58 s** |

Four runs, four passes, no failed attempt. **No baseline was frozen.**

## §10 What M4 inherits, measured here rather than remembered

1. **A multi-replica baseline cannot self-calibrate in two views on this fleet**
   (§7). `fault_matrix` cannot, because Valkey elects by replication-offset rank
   among four candidates and three different replicas won across three runs;
   `management_matrix` cannot, for the environment reason `BASELINE.md` already
   records at r=1. Whoever freezes one must judge both on the field-level delta
   and on which node the artifacts agree about, never on the view score. The
   other three stages are byte-identical run to run.
2. **Rank on the split, and budget several runs per rung** (§6.2). Two runs of
   one configuration gave PFAIL → promotion 6.02 s and 10.55 s inside RTOs
   0.3 % apart. This rung could not separate r=1 from r=4 with two runs a side,
   and M4 will not separate 500 from 1000 with one.
3. **Support map §3.1 has been exercised and did not fire** (§5.2), twice, with
   49 nodes validated while three siblings re-attached. Still not a disproof;
   still the thing to watch first at higher replica counts or wider fleets.
4. **Support map §3.2 fires on the real fleet too** (§5.3):
   `replacement_logical_id` named the wrong promoted node in three of four
   multi-replica runs across two runtimes. Untouched by instruction, and now
   with real-fleet evidence behind it.
5. **The arithmetic, compiled and then run** (§2). 10×4-50 needs
   `nodehosts_per_az: 4` to land on eight nodehosts; 40×4-200 needs no knob.
   Both give every shard 3/2 and the fleet exactly even. The gce-m3b fleet holds
   both with no provisioning; only M4 provisions.
6. **`cleanup_actions` is `5×nodehosts` on a native run, not `5×nodehosts+1`**
   (§5.1). The `+1` is Docker's network-remove row. 20 rows at four nodehosts,
   40 at eight, at every replica count.
7. **The diff tool now scrubs the Gate's own test directory** (§3). Anyone
   comparing a pre-item-1.7 baseline against a current run before `f9b10814`
   would have seen `runtime_start` 3/7 and `cleanup` 1/2 and had to work out
   why.

Carried forward untouched and still nobody's: the aborted controller's ssh
masters (1.4 map §8.2), the resource-to-timeline monotonic correlation (1.3 map
§10.1), a failing run collecting no journals (1.3 map §10.2), `run` not
classifying a transport failure, a native run's command audit recording no ssh,
whether the preflight should validate the document the run uses, the absent
fault-path ownership check, the missing `signalled` count, `SamplerSpec`'s
duplication, `_state_nodehost` dropping `remote_bundle_dir`, why the health-gate
escalation inverts with scale, and support map §5.2's dead `add_replica`
`safe_path` dict entry. Support map §2.5's two M2-lane breaks stay deferred by
§7.4.
