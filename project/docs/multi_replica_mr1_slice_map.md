# MR-1 slice map: the multi-replica fixes, and what implementing them corrected

Stage MR-1 of `multi_replica_support_map.md` §8. Scope as given: §2.1, §2.2,
§2.3 under the §7.1 decision, §2.4 under §7.2, §7.3, §7.5, the §6 hermetic tests
with a mutation check on each. **No multi-replica run of any kind was taken** -
that is MR-2's, and it needs operator approval. §2.5's two M2-lane breaks are
left alone by decision §7.4.

Eight commits, `c72dd986` through `28257709`, each with its own observation, each
leaving `./gate suite repository.all` green.

## §1 The headline: the map's central arithmetic was wrong, and only running it said so

`multi_replica_support_map.md` §1 tabulates the shapes the ladder will use and
concludes that ten shards of four replicas needs `nodehosts_per_az: 4`, giving
8 nodehosts and **0 of 10 shards colliding**. §1's own caveat is that those
compiles went through the *planner's* AZ assignment while a run builds its nodes
through `_node_specs`, and it predicts only that "nodehost counts on the run path
can differ". It then says the knob conclusion "holds under both formulas".

Measured at HEAD, over `nodehosts_per_az` 1 to 16, both node orderings, both AZ
policies:

| shape | AZ policy | node ordering | fault-domain-safe at |
|---|---|---|---|
| 10×4 | alternating (§7.1's) | runtime | **nothing** |
| 10×4 | alternating | planner | 3 and up |
| 10×4 | all-opposite (old) | runtime | 4 and up |
| 40×4 | alternating | runtime | **nothing** |
| 40×4 | alternating | planner | 1 and up |

The run path collides at **every** value under the policy the operator decided
on. More fault domains do not help, so the density refusal could not have been
escaped by any knob, and MR-2's first rung would have been refused at plan time
however it was configured.

The cause is not the AZ formula on its own. Within an AZ the nodehost assignment
was round-robin by position in the ordinal-sorted list, and `_node_specs`, the
semantic validator and the resource preflight all order **every primary before
every replica**. So a shard's primary sits in the leading block and its same-AZ
replicas far down the tail, and whether the two land together is decided by
where the stride happens to fall, not by how many nodehosts exist. The planner
interleaves each primary with its own replicas instead, which is why the map's
compiles were clean and a run's would not have been.

The fix is in §3.3. Its consequence is that the safe threshold becomes exactly
`ceil((replicas + 1) / AZs)` for both orderings - so the minimum §7.5 asks the
refusal to name is now *sufficient* as well as necessary, which it was not
before.

**Second correction, smaller.** §7.1 says the unified formula was "spot-checked
to agree with the planner's formula at r=1 for both 2 and 3 AZs". At three AZs
that is false: from shard 3 onward the two pick different AZs, because the old
one indexes the two candidates left after excluding the primary's while this one
indexes all three. It moves nothing - `_validate_network` admits exactly one AZ
in single mode and exactly two in multi, so three is unreachable - and it is
pinned by its own test rather than left in prose. MR-1 was told to prove the
identity with a test rather than carry it, and the test is what found this.

## §2 What each change was, in one line

| map § | commit | change |
|---|---|---|
| §2.1 | `4ef64477` | the rolling restart's health gate counts primaries instead of halving |
| §2.2 | `253695cc` | the partition recovery wait does the same |
| §1 caveat | `4f02c36e` | a shard's members never share a nodehost |
| §2.3, §7.1, §2.6 | `fedfce30` | one AZ placement function; `primary_replica_distinct_az` → `shard_az_balanced` |
| §7.5 | `6d3e34f2` | the per-AZ fault-domain minimum is stated, and the refusal names it |
| §2.4, §7.2 | `76f62659` | `cluster-allow-replica-migration no`, at two or more replicas only |
| §7.3 | `7437234e` | replicas per shard bounded at 1..4 |
| §4, §6 | `28257709` | the r-generic machinery exercised at four replicas |

## §3 The changes in detail

### §3.1 The two `// 2` census defects (map §2.1, §2.2)

`_management_matrix_clean_health` expected `node_count // 2` primaries. A
10-shard, 4-replica cluster reports 10 primaries and 40 replicas against an
expectation of 25/25, a census it can never satisfy, so every batch of both
rolling-restart operations would burn its 180 s and raise at batch 1.
`_local_full_flow_wait_clean_cluster_snapshot` has the same expression, and all
three partition scenarios call it in their recovery `finally`.

Both now count the planned roles. That is what already survives the role swaps
these stages perform - a promotion exchanges a primary for a replica and leaves
both totals unchanged - and it is why `_management_wait_clean_cluster`, the
sibling wait in the same file, has always counted rather than halved.

One existing test moved with the second: `test_local_full_flow_fault_recovery_
uses_one_strict_snapshot` built six nodes carrying **no `role` at all**, because
halving never needed one. Three shards of one replica is the same 3/3 it always
asserted.

### §3.2 One AZ placement decision (map §2.3, §7.1, §2.6)

Four modules answered it independently: `planner/plan.py`, `config/validation.py`
(the semantic node model), `resource.py` (the preflight's) and
`runtime/docker_runtime.py`'s `_node_specs`. The map named the first three as one
group and the fourth as the odd one out; `resource.py`'s `_preflight_replica_az`
was a fourth copy the map did not name, byte-identical to the validator's.

`placement.py` holds the decision now: `primary_az`, `replica_az` and
`shard_az_balanced`. The policy is the runtime's, per the §7.1 decision, and both
required properties hold by construction rather than by search - a shard takes
`replicas + 1` **consecutive** AZ indices from its own, and consecutive residues
modulo the AZ count cannot differ in frequency by more than one (P1); summing
that window over the shards gives P2, exactly even when the AZ count divides the
shard count and off by at most one otherwise, at any replica count.

That is also what dissolves §2.6 structurally: the old policy's per-AZ skew over
two AZs at an odd shard count is exactly `replicas - 1`, so odd shard counts at
three or more replicas raised `PlannerError("planner constraints failed")`. Under
this one the skew is at most 1 for every shard count and every replica count.

**The constraint is renamed**, per §7.1's instruction, because a name saying
"distinct AZ" must not report true over the 3/2 split a five-member shard has:
`primary_replica_distinct_az` → `shard_az_balanced`, asserting P1. At one replica
over two AZs the two properties are the same statement and the value is unchanged
in every existing plan. The precondition §7.1 set was checked first:
`cluster_plan.json` appears in **no** view of `scripts/diff_stage_artifacts.py`,
so the rename moves no diff. `cluster_plan.schema.json`'s `constraints.required`,
`scripts/assert_plan_constraints.py` and the planner tests move in the same
commit. `primary_replica_opposite_az_pair` is left as it was - it already skips
any shard without exactly one replica, so it is an r=1 statement and stays one.

`scripts/assert_plan_constraints.py` also had the old property inline (`replica
shares AZ with primary`); it asserts per-shard balance now, counted over the
plan's declared AZs.

### §3.3 The nodehost assignment (the map's §1 caveat, measured)

Described in §1 above. Where the positional assignment would put two members of
one shard on one nodehost, the AZ's nodes are walked a shard at a time, each
shard's members taking consecutive nodehosts from a running cursor. Distinct
whenever the AZ has at least as many nodehosts as the shard has members in it,
and the per-nodehost counts stay within one of each other because the cursor
never rewinds.

**Used only where the positional assignment fails**, and that conditional is
load-bearing rather than caution: on a single-AZ non-HA plan the two differ, and
walking by shard there would gather every primary onto one nodehost. Both
directions are mutation-checked.

### §3.4 The per-AZ fault-domain minimum (map §7.5)

`min_fault_domains` was computed only for the single-AZ case, where it reads
`replicas + 1`; multi-AZ was hardcoded to 1, which is correct at one replica
because a shard then never has two members in one AZ. One expression covers both
now - `ceil((replicas + 1) / AZs)` - which *is* the old single-AZ expression at
one AZ and 1 at one replica over two, so nothing existing moves.

The refusal names the shard, the nodehost it shares, the shard shape and
`runtime.nodehosts_per_az` with its configured value and the required minimum.
With the minimum hoisted and the assignment shard-aware, every layout the
placement policy produces is separable, so the refusal is a **fail-closed
backstop rather than a step a supported shape walks through** - its test reaches
it by handing the planner an AZ layout the policy would not produce, and says so.

**A number for MR-2 that differs from the map's.** Ten shards of four replicas
now plans at the **shipped** `nodehosts_per_az: 2`, with **6 nodehosts**, not the
8 the map's table gives for `nodehosts_per_az: 4`. Both are valid; 4 still yields
8. Forty shards of four still plans 8 nodehosts at shipped knobs, because
`ceil(100/25) = 4` per AZ binds above the minimum of 3. Twenty-five shards of one
replica still plans 4.

### §3.5 The topology pin (map §2.4, §7.2)

The generated node config set neither `cluster-migration-barrier` nor
`cluster-allow-replica-migration`, so Valkey's defaults governed: barrier 1,
migration allowed. At one replica a shard has no spare above the barrier and
migration can never trigger. At two or more it can, and the formation validator
enforces planned shard membership one for one, so an auto-migration would be a
permanent `SemanticFailure` nothing could attribute.

`cluster-allow-replica-migration no` is emitted when `replicas_per_shard >= 2`,
per §7.2 - stating the intent rather than tuning the barrier to a number that
means the same thing. The shape reaches the config generator as an argument
rather than off the node, because it is a property of the cluster, and the
lifecycle is the layer holding the configuration.

### §3.6 The 1..4 bound (map §7.3)

`REPLICAS_PER_SHARD_ABOVE_MAX` is unconditional. `REPLICAS_PER_SHARD_BELOW_MIN`
applies only to real execution, and names the two shapes still admitted: a
dry-run projection, and a single-AZ plan carrying `cluster.non_ha_allowed`. The
schema keeps `minimum: 0`; the semantic layer owns the policy as it does for
every other cap.

### §3.7 The r-generic machinery, now exercised (map §4, §6)

Nothing here is a fix. Map §4 lists parts that are already replica-generic by
design, and three of them had no test that could tell: `redundancy_recovery` had
none at all, every affected-shard observer fixture had one or two survivors, and
`_cluster_form_nodes` hardcoded one replica. All three behave as §4 says. Added:
`redundancy_recovery` at one and four replicas plus both ways a four-replica
shard is short; the observer at four survivors, with a TRANSIENT sibling voiding
a round and restarting the streak, and two survivors reporting primary at once;
and formation driven at 6×4 (30 nodes, small branch) and 10×4 (50, large branch).

## §4 Proof

- **`./gate suite repository.all` 92/92 PASS**, invocation
  `gate-20260814T081837Z-b44262d7`. Catalog stays **99** and the M1 plan **91**,
  because every added test joined a module the catalog already registers - the
  two contract assertions that pin those numbers are inside the suite.
- **The pytest tree is 845**, measured by collection at this HEAD against **824**
  at `58373a42` in a clean worktree: 21 tests added.
- **Every regression test was mutation-checked**: the fix reverted, the test
  watched to fail, the fix restored. Twelve mutations in all, including both
  directions of the assignment conditional and both directions of the topology
  pin.
- **Two r=1 no-op proofs taken against the frozen baselines themselves**, not
  against a second copy of this code:
  - `_node_specs` plus `_process_nodehosts` reproduce the node-to-nodehost map of
    both frozen runs exactly - **50 of 50** and **200 of 200** - and their
    `logical_nodes_per_nodehost`.
  - `_process_config_text` at one replica reproduces the frozen exact-50
    baseline's `node_configs/shard-0000-primary.conf` **byte for byte**.
- **Two consecutive real Docker exact-50 runs** - see §5.

## §5 The real runs

Two consecutive real Docker exact-50 at the existing 25×1 shape, on this HEAD:
**PASS 894.81s** (`gate-20260814T082524Z-a35c1482`) and **PASS 841.09s**
(`gate-20260814T084052Z-37b09420`). Both:

- `run_verdict.json` **PASS, 12/12 checks OK**, `tool_errors` empty.
- `cleanup_report` PASS, **21 rows**, `resources_remaining` empty,
  `cleanup_errors` empty; zero `vslab` containers or networks left, asked of
  Docker from outside the product.
- The string `ERROR` in **no** artifact of either run.
- Fault lane **9 scenarios / 12 command rows / 15 windows**, status PASS.
- Primary-kill RTO **48.957s** and **47.197s**, both inside the 45-50s exact-50
  band.

Diffed against the frozen `exact-50-6b6f57fd` baseline, calibrated
baseline-to-baseline first at 7/7, 5/5, 8/8, 6/6, 2/2:

| stage | expected | run 1 | run 2 |
|---|---|---|---|
| `runtime_start` | 7/7 | **7/7** | **7/7** |
| `cluster_form` | 5/5 | **5/5** | **5/5** |
| `management_matrix` | 6/8 | **6/8** | **6/8** |
| `fault_matrix` | 4/6 — see below | **4/6** | **4/6** |
| `cleanup` | 2/2 | **2/2** | **2/2** |

**The two runs are identical to each other in every view of every stage** -
7/7, 5/5, **8/8**, **6/6**, 2/2 diffed against one another - including the two
that differ from the baseline.

Both inherited `management_matrix` deltas are at their declared shapes in both
runs: **+14 rows**, `cluster_migrate_keys` **4 → 18**,
`owned_valkey_process_remove_nodes_conf` **4 → 0** and
`owned_valkey_process_discard_prior_state` **0 → 4**, **three kinds changed and
fourteen unchanged**. There is no third.

Two direct checks of this work's own r=1 no-op claims, on the runs themselves:
`nodehost_density_plan.json` is **byte-identical to the frozen baseline's** in
both runs, and `cluster-allow-replica-migration` appears in **zero** of the 100
generated node configs.

### §5.1 `fault_matrix` is 4/6, and 5/6 is a stale expectation

The task set the bar at `fault_matrix` 5/6. Both runs score **4/6**, and that is
the current expectation rather than a regression: the failover/RTO work of
2026-08-13 (`5c8d3cb0`..`85a841de`, in this branch's history) declares in
CLAUDE.md that its measured delta is "`fault_matrix` **4/6**, one new differing
view, nothing else moved", proven there on two Docker exact-50 and on native
exact-50 and exact-200.

Checked at the field level rather than taken on trust. The two differing views
are `fault_sequence` and `failover_observation:verdicts`, and the second differs
by **exactly one added key, `failover_timeline`** - which is that work's own
declared addition and nothing else. `fault_sequence` differs in the three
partition scenarios' isolated side (the inherited `85d5096a` delta:
`isolated_cluster_state_ok`, `success`, `response`, `error`, `observed`,
`cluster_state`, `reason`) and in the failover work's new metric fields
(`write_unavailability_ms`, `process_gone_to_pfail_ms`,
`pfail_to_promotion_ms`). Nothing in MR-1 touches either lane.

So 5/6 was the mark before 2026-08-13 and 4/6 is the mark after it. **No r=1
mark moved under this work.**

## §6 What MR-2 inherits

1. **The fleet arithmetic changed.** 10×4-50 plans at shipped knobs with 6
   nodehosts, or at `nodehosts_per_az: 4` with 8. 40×4-200 needs 8 either way.
   The map's §1 table assumed `nodehosts_per_az: 4` was required; it is not, and
   whichever is used has to be stated in MR-2's configuration rather than
   inferred.
2. **Multi-replica runs are a new baseline class**, unchanged from the map: the
   knob and the shape move `nodehost_density_plan`, every `nodehost_id`, the
   fault matrix's targets and the cleanup row count, so they are not diffable
   against the frozen one-replica baselines in those views.
3. **§3.1 of the map is still the predicted intermittent failure** - the
   down-window full validation with `require_replica_connected=True` and no
   convergence budget, which is vacuous at one replica and meets three resyncing
   siblings at four. Nothing in MR-1 touched it, deliberately: it is a
   verdict-adjacent change and belongs to the rung that can observe it.
4. **§3.2's promotion-winner artifact is untouched**, and its §6 test was
   deliberately not written: it asserts a fix that is not in MR-1's scope, so a
   test for it would have had to fail or to assert the defect.
5. **The planner and the runtime still order nodes differently** - the planner
   interleaves each primary with its replicas, the other three models block the
   primaries first - and therefore assign different ordinals, and so different
   `client_port`s, to the same logical node. It is pre-existing, it predates every
   part of this work, and at one replica nothing observes it. It is worth knowing
   because it is what made the map's compiles disagree with a run's, and because
   the *validator* is the one that matches the runtime, so where the two disagree
   about fault-domain safety the validator is right. Making them agree would move
   `cluster_plan.json`'s ports at one replica and is nobody's yet.
6. **Neither the frozen baselines nor any `templates/configs/` file was touched.**
   MR-2 writes the first multi-replica configuration.
