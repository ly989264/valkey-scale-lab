# Multi-replica support map: what 1–4 replicas per primary needs before M4

Written 2026-08-14 at `58373a42` on `fast-iter`. This is an exploration and
design document, not a slice map of work done: **no product code changed, no
live cluster was run.** The operator's M4 goal is a real cluster of 256
primaries with 4 replicas each (1280 valkey-servers), and the operator's
standing assumption for this work is **at least 1 and at most 4 replicas per
primary**. Every run this product has ever taken — every baseline, every
constant, every band — is `replicas_per_shard: 1`, so multi-replica is a
prerequisite program, not a knob turn.

Provenance: four independent read-only code sweeps (fault lane; failover/RTO
and management matrix; formation; planner/schemas/evidence/diff views), each
returning file:line findings, plus real compiles through `cli config validate`,
`cli plan` and `build_cluster_plan` at this HEAD. Where a claim below is
derived rather than compiled or executed, it says so. The implementation and
the runs belong to later sessions; §8 is their plan.

## §1 The ladder arithmetic, compiled at HEAD

All shapes below were pushed through the real validator and planner (not hand
arithmetic). "knob" is the one config addition each shape needs.

| shape | nodes | knob | nodehosts | colliding shards | formation branch | profile |
|---|---|---|---|---|---|---|
| 6×4 | 30 | `nodehosts_per_az: 4` | 8 | 0/6 | **small (`<=30`)** | exact-30 |
| 10×4 | 50 | `nodehosts_per_az: 4` | 8 | 0/10 | large | exact-50 |
| 40×4 | 200 | none (density gives 4/AZ) | 8 | 0/40 | large | exact-200 |
| 256×4 | 1280 | none (density gives 26/AZ) | 52 | 0/256 | large | **none — M4's to add** |

- At shipped knobs (`nodehosts_per_az: 2`) the 30- and 50-node shapes are
  **refused at plan time**: `_primary_replica_nodehost_safe`
  (`nodehost_density.py:279`) requires every member of a shard on a distinct
  nodehost, and 2 nodehosts per AZ cannot hold a shard's same-AZ replicas. The
  refusal message names neither the knob nor the replica count (§7.5).
- The 40×4 compile was made through `build_cluster_plan(capability_id=
  "local_full_flow", scenario="local_full_flow")` because the bare
  `cli plan`/`cli config validate` path refuses every 200-node config,
  including the unmodified `scale_200.yaml` — the bounded exception applies
  only in the Gate's capability context. `_is_exact_200_bounded_exception`
  carries **no shard-shape term**, so 40×4 rides the existing exception.
- **8 nodehosts is the gce-m3b fleet's exact size**: every prerequisite rung
  runs on hosts that already exist. Only M4 itself (52 hosts) provisions.
- Profile resolution is total-count-only (`profile_for_exact_nodes`,
  `execution.py:202`): 6×4 resolves to `exact-30` exactly as 15×1 does. 1280
  resolves to nothing and raises — a new `ExecutionProfile` is M4's, not this
  program's.
- **Caveat on every row above:** these compiles went through the *planner's*
  AZ assignment. The run path builds its nodes through `_node_specs`, whose AZ
  formula differs at r≥2 (§2.3), so nodehost counts on the run path can differ
  until §2.3 is fixed. The knob conclusion (4/AZ suffices at r=4) holds under
  both formulas — the planner layout needs 4 same-AZ domains, the runtime
  layout 3.

## §2 Hard breaks — a multi-replica run cannot pass until these are fixed

### §2.1 The rolling-restart health gate demands a half-primaries census

`docker_runtime.py:11785` `_management_matrix_clean_health`:
`expected_primaries = node_count // 2`. Enforced by
`_management_matrix_wait_rolling_restart_health` at `:11349`, `:11860`,
`:11878`, `:11882`. A 10×4 cluster reports 10 primaries / 40 replicas against
an expectation of 25/25, so every batch gate burns its 180 s and raises
`rolling restart health gate did not converge` at batch 1 of both restart
operations. The correct pattern already exists in the same file:
`_management_wait_clean_cluster` (`:6771`) counts `len(primaries)` /
`len(replicas)` from the plan and survives failover role-swaps because the
census is count-preserving. Fix: derive, don't halve. Proof: hermetic test at
a 10×4 fixture that fails on the `//2` form, plus mutation check.

### §2.2 The partition scenarios' recovery wait has the same `//2`

`docker_runtime.py:9713` `_local_full_flow_wait_clean_cluster_snapshot`:
`expected_primaries = len(nodes) // 2`, called at `:9658` in the recovery
`finally` of `_local_full_flow_network_disconnect_probe` — so all three
partition scenarios (`network_partition`, `minority_majority`,
`split_brain_detection`) fail after 180 s each on any r≥2 run. Same fix shape
and proof shape as §2.1.

### §2.3 The runtime and the planner disagree about replica AZ placement

Two formulas exist for the same decision, and they agree only at r=1:

- Planner `_replica_az` (`planner/plan.py:404`) and validation's
  `_semantic_replica_az` (`config/validation.py:733`), byte-identical:
  `candidates = [az != primary_az]` — **every replica opposite its primary**.
  At 2 AZs and r=4 a shard splits **1/4** (verified on the compiled 1280
  plan: 256 of 256 shards).
- Runtime `_node_specs` (`docker_runtime.py:3033`):
  `azs[(shard + replica + 1) % len(azs)]` — does **not** exclude the primary's
  AZ. At 2 AZs and r=4 a shard splits **3/2** with replicas 01 and 03 in the
  primary's own AZ.

`_node_specs` is what a real run starts (`docker_runtime.py:713`), so at r≥2
the executed topology contradicts the plan artifact and violates the plan's
own asserted constraint `_primary_replica_distinct_az` (`plan.py:411`, a
refusal at `:225`) without anything refusing. This break is also the choice
point §7.1 — the fix is to unify on one formula in one shared function, and
which formula wins is an operator decision because one of them requires
relaxing a declared plan constraint. **Both candidate policies are identical
at r=1**, so either unification moves nothing on any existing run.

### §2.4 An absent config directive lets Valkey rewrite the topology

The generated node config (`docker_runtime.py:3080-3113`) sets no
`cluster-migration-barrier` and no `cluster-allow-replica-migration`, so the
defaults govern: barrier 1, migration allowed. At r=1 a shard has 0 spare
replicas and migration never triggers, which is why this has never mattered.
At r≥2 a shard has `r-1` spares above the barrier and Valkey may
**auto-migrate replicas between shards**. The formation validator enforces
planned shard membership one-to-one (`observability/cluster.py:515-539` — a
replica observed under a different shard's primary is a permanent
`SemanticFailure`), so an auto-migration any time before a full validation is
a hard, unattributable failure. Fix per §7.2: pin the topology explicitly when
r≥2. Conditional emission keeps every r=1 run's `node_configs` byte-identical
to the frozen baselines.

### §2.5 The two M2-lane observers hardcode the promotion winner

- `scripts/fault_failover_timeline_gate.py:70` chooses
  `sorted(replicas)[0]` as `expected_replica_node_id`, and
  `observer/failover_timeline.py:1428` gates `first_promotion_seen_at_ms`,
  `first_slots_covered_at_ms` and `first_cluster_ok_at_ms` on **that exact
  node** promoting. Valkey elects by replication-offset rank, uncorrelated
  with node-id sort order: right by construction at r=1, right ~25% of the
  time at r=4, and the miss raises `FailoverTimelineError` from
  `derive_rto_metrics`.
- `scripts/fault_failover_gate.py:418` (`replicas[0]` as the expected
  promotion) has the same shape: at r=4 the legacy RTO gate reports
  `no promoted primary observed after primary stop` ~75% of the time.

Disposition proposed (§7.4): **defer, declared.** Both are M2 machinery — the
real full-flow lane detects promotion as "any surviving shard member reports
primary" (`docker_runtime.py:8736`), which is r-generic — and M2 is parked.
They must not silently rot, so the deferral is recorded here and in the doc
that owns them.

### §2.6 Odd shard counts are refused at r≥3

`_az_balanced` (`plan.py:438`) requires per-AZ node counts within 1. Under the
*planner's* AZ policy the skew for an odd shard count over 2 AZs is exactly
`r-1`, so odd×r≥3 raises `PlannerError("planner constraints failed")` — a
message naming neither balance nor replicas (verified by direct call: shards
5/7/9/11 × r=3,4 all fail; every even count passes; 256×4 passes). Under the
*runtime's* alternating policy the skew is at most 1 for every shard count.
So §7.1's choice decides whether this is fixed structurally (policy b) or
documented as a supported-shape constraint with a better message (policy a).
The ladder's shapes (6, 10, 40, 256) are all even either way.

## §3 Evidence-honesty and intermittency risks — runs may pass while the evidence misleads

1. **The down-window validation will trip on resyncing siblings.**
   `docker_runtime.py:8975-8998` runs a single-shot full validation during the
   kill window with `require_replica_connected=True` and
   `convergence_timeout=0.0` (immediate re-raise, no retry), with only the
   killed node exempted. At r=1 the affected shard has zero remaining replicas
   so the check is vacuous there; at r=4 three siblings are mid-reattach to
   the newly promoted primary while it runs. Intermittent hard failure of the
   failover step. Design: exempt the affected shard's replicas during the
   window, or grant the validation a bounded convergence budget — either is a
   verdict-adjacent change and should be reported when made.
2. **The artifact predicts the promotion winner and publishes the prediction.**
   `docker_runtime.py:9201` picks the target shard's first replica as
   `replacement` before the kill; `:9363` writes it top-level as
   `replacement_logical_id`, while the *observed* winner lands only in
   `failover_details`. `analysis/validated.py:447` reads the top-level field,
   so at r=4 the validated report names the wrong promoted node ~75% of the
   time with nothing failing. Fix: write the observed winner (or both,
   labelled as prediction and observation).
3. **`precision_ms` is asserted, not measured, and gets dishonest at r=4.**
   `AffectedShardObserver.sample_round` (`observability/failover.py:111`)
   samples survivors serially with a 1.0 s per-connection timeout, and
   `wait_for_convergence` returns a hardcoded `round_interval_ms: 500`
   (`:198`) that `_derive_failover_timeline` stamps into `precision_ms`. One
   survivor keeps that honest; four survivors during an outage can stretch a
   round toward ~4.5 s while the artifact still claims 500. Same defect class
   the Sentinel probe's `_round_cadence` fix addressed — the observer needs
   the same treatment (measure the achieved cadence; parallelise the fan-out).
4. **Election retries are invisible.** `_failover_point` takes the first round
   in which any survivor says primary and never revisits. With 4 rank-delayed
   candidates a promotion can be attempted, lost and re-won by a different
   node; `first_promotion_at_ms` would time node A while
   `replacement_logical_id` names node C, with no epoch record to reconcile
   them. Recording config-epoch alongside the role flip closes it.
5. **`_FAILOVER_UNMEASURABLE_POINTS`' reasons are r=1 artifacts.**
   `docker_runtime.py:8620-8640` argues `first_fail_at_ms` is circular because
   "the surviving replica sets FAIL as it promotes itself". At r≥2 three
   non-promoting replicas are exactly the independent vantage the text says
   does not exist. The declaration must be re-derived (the point may become
   measurable), not copied forward — its "72 of 74 runs" evidence is all r=1.
6. **Operand bias: three management operations always land on `-replica-00`.**
   `add_replica`/`remove_replica`, `remove_primary_drained_or_safe_replaced`
   and `make_primary_restart_safe` all `next()` the first live replica in plan
   order. Replicas 01–03 are never an operand of anything: not a break, a hole
   in what the matrix proves at r=4. Cheap to rotate; operator's call whether
   to bother in the prerequisite or accept.
7. **The 240 s no-progress window meets a new load shape.** A replica-link
   `ConvergenceFailure` carries no `pending` set (`contracts.py:37`), so while
   replicas sync the only progress signal is the failure message naming a
   different node. 4-way concurrent first-syncs from one primary are a
   formation regime no calibration covers (the constant was sized on
   `CLUSTER SHARDS` dwells at r=1, and its own map says it is not scale-free).
   Not predicted to break — the first rung measures it.
8. **The preflight validates the profile's template, not the run's config**
   (`runtime/lifecycle.py:174-186` reads `full_flow_profile.config_template`,
   e.g. `scale_50.yaml` at r=1 shape). At equal node totals the numbers
   coincide today by accident. This is the already-open operator question from
   the M3-B handover — multi-replica makes it load-bearing, because the
   template and the run config now genuinely disagree about shape.
9. **A 30-node run takes the small formation branch** (`len(nodes) > 30` is
   strict, `docker_runtime.py:3580`), which omits the convergence-wait and
   final-snapshot timeline segments and every M2 setup event, and ignores
   `VSLAB_REPLICA_REPLICATE_PARALLELISM`. 6×4-30 is therefore not a drop-in
   small copy of the 50-node rung — which is one reason §8 makes 10×4-50 the
   first rung and 6×4-30 optional.

## §4 Already correct by design — do not "fix" these

- **The fault lane's 9 scenarios / 12 command rows / 15 windows are invariant
  under replica count.** Every term is a constant (9 probe-table entries, 5
  canonical windows + 1 all_run + 9 event windows, 3 fixed kill-lane rows);
  node, shard and replica counts appear nowhere in the arithmetic. The pinned
  invariant survives this program untouched.
- **The rolling-restart batcher** (`:11548`) is role-homogeneous,
  one-per-shard *and* one-per-nodehost per batch: a primary never co-restarts
  with its replicas, two replicas of one shard never co-restart, at any r.
- **`redundancy_recovery`'s arithmetic** (`docker_runtime.py:9056`) is exact
  at every r: target-shard members − 1 = r, and post-restore the shard holds
  exactly r replicas. (It has zero tests — §6.)
- **`AffectedShardObserver`** takes all surviving shard members and its
  verdict references no replica count; promotion detection is "any survivor
  reports primary". Plural-capable by construction.
- **Sentinel**: one canary per shard shared by all members, router is pure
  slot-routing, `prepare()` waits on every replica.
- **Schemas, evidence, analysis, report, native backend, actuator**: fully
  shape-neutral. `run_config.schema.json` already admits any replica count;
  state.json expresses membership as `role`+`shard_id` only; the actuator is
  purely node/nodehost-addressed; no `logical_id` string surgery exists
  anywhere in `src/`.
- **The Gate/catalog surface**: `real.*.full-flow` take `nodes` + `config`;
  nothing validates the total against `shards*2`; "plan is exact" is
  total-count-only.
- **Memory/FD preflight** charges every node its full limit, role-blind —
  correct for replicas holding full copies.
- **Load-lane file set** is fixed by memtier's output contract (18 files at
  any shape).

## §5 Declared deltas — predictions an r≥2 run must match, not normalise away

1. `management_command_log` row law, derived from the frozen baselines and
   closed-form checked against both (1592 at 25×1-50 ✓, 5814 at 100×1-200 ✓):
   `rows ≈ 38·S + 4·S + 4·N + ~4(N−1) + 2(B+Bp+1) + 98`. Predicts **≈980 at
   10×4-50** — the knob is shard count, not node count. The first rung tests
   this prediction; a big miss is a finding.
2. `add_replica`'s verify row `safe_path` becomes
   `"40_replicas_observed_replicating_for_10_primaries"`.
3. Sentinel `canary_count` = shard count: 6/10/40 against the r=1 table's
   15/25/100.
4. Rolling-restart batch geometry changes at constant node count (batch count
   ≈ ×r for replica passes); exact numbers depend on §7.1's layout and are
   measured, not predicted.
5. `cleanup_report` = 5×nodehosts+1 rows: 41 at 8 nodehosts (already seen at
   exact-200; new at a 50-node run).
6. Per-primary offered load rises ×2.5 at 10×4 (10 kQPS global ÷ observed
   primaries, by design doc §8.2 — aggregate unchanged, declare per-primary).
7. `node_configs` gain the §2.4 directive on r≥2 runs only.
8. **RTO at r=4 is a new number, not the 45–50 s band.** Election rank delays
   and 4 candidates change the promotion term; the r=1 bands and the
   47–54 s exact-200 spread carry no authority here. First rung founds the
   r=4 band; nothing exists to diff it against.
9. Formation dwell at 4-way sync fan-in (one primary serving 4 first-syncs;
   diskless-sync 5 s grouping window is an unpinned default) — measured at
   the first rung, compared against nothing.

## §6 Hermetic test plan

Current coverage, measured: **one** multi-replica test exists in the whole
tree (`tests/planner/test_planner.py:56`, a 9-node r=2 planner check).
`_cluster_form_nodes` hardcodes one replica; the fault-stage fixture hardcodes
2-node shards; observer tests use 1–2 survivors; `redundancy_recovery` has
zero tests; the density fault-domain refusal has zero tests at r≥2.

To add (all join catalog-registered modules, so `repository.all` stays 92 and
the catalog/M1-plan counts do not move):

- §2.1/§2.2 fixes: 10×4 fixtures that fail on the `//2` forms; mutation-check
  both (revert fix → test must fail).
- §2.3 unification: one shared AZ-assignment function; property test that
  planner nodes, semantic-validation nodes and `_node_specs` agree at r=1..4
  × 2–3 AZs × even/odd shard counts; regression test pinning r=1
  byte-identity of `_node_specs` output.
- §2.4: config-text test that r≥2 emits the pin and r=1 emits nothing.
- §2.6/§7.5: planner refusal tests at odd×r≥3 (or its structural fix), and a
  density-refusal test whose message names `nodehosts_per_az` and the
  required minimum.
- Bounds (§7.3): validation tests at r=0, 1, 4, 5.
- `redundancy_recovery` unit tests at r=1 and r=4, including the
  non-uniform-shard refusal it implies.
- `AffectedShardObserver` convergence at 4 survivors, including one survivor
  flapping TRANSIENT (streak reset) and a two-primaries round (None).
- Formation: extend `_cluster_form_nodes` to parameterised r; exercise both
  branches at r=4 (fake transport level).
- §3.2: test that the artifact's promoted-node field matches the observed
  winner under a faked election where replica-02 wins.

Run the mutation check on every regression test — the 2026-08-13 lesson.

## §7 Operator decision points

**§7.1 Replica AZ policy (decides §2.3 and §2.6).**
- *(a) Planner policy everywhere* — all replicas opposite the primary. Smallest
  change (one line in `_node_specs`); keeps `_primary_replica_distinct_az`
  as-is; costs: shard splits 1/4, so losing the replica AZ strips **all**
  redundancy from half the shards at r=4; odd×r≥3 stays refused;
  `nodehosts_per_az ≥ r` required.
- *(b) Runtime's alternating policy everywhere* — replicas spread over both
  AZs including the primary's (3/2 at r=4). Every shard keeps members in both
  AZs under any single-AZ loss; `_az_balanced` holds for every shard count
  (fixes §2.6 structurally); per-AZ fault-domain need drops to
  `ceil((r+1)/2)` = 3. Cost: `_primary_replica_distinct_az` must be relaxed to
  the actual HA property — "every shard has ≥1 replica in an AZ different
  from its primary" — which is a semantic change to a declared plan constraint
  (schema-required field), reported per the working rules, with
  `_semantic_replica_az` and `scripts/assert_plan_constraints.py` moving in
  the same commit.
- **Decided 2026-08-14, by the operator's own statement of the requirement**
  (superseding the same-day delegation, and coinciding with it): a shard's
  members are **evenly distributed across all AZs**, and the fleet's total
  per-AZ server counts are **also even** — the operator's example being six
  5-member shards over 2 AZs as three shards at 3/2 and three at 2/3,
  totalling 15/15, with the note that which shards take which orientation may
  vary. This is two testable properties, and they are the acceptance criteria
  for MR-1's constraint work:
  - **P1, per-shard balance**: within one shard, per-AZ member counts differ
    by at most 1 (5 members over 2 AZs ⇒ 3/2; over 3 AZs ⇒ 2/2/1).
  - **P2, global balance**: total per-AZ node counts differ by at most 1
    (exact at even shard counts over 2 AZs). `_az_balanced` already asserts
    this; it stays.
  The runtime's alternating formula `azs[(shard + replica + 1) % len(azs)]`
  **produces exactly this** — computed at this HEAD for the operator's own
  example: shards alternate 3/2 and 2/3 with the total exactly 15/15, and at
  3 AZs each shard goes 2/2/1 with totals 10/10/10 — so the decision is
  implemented by unifying on that formula, not by writing a new placement
  algorithm. Grounds that independently supported it: under any single-AZ
  loss every shard keeps ≥2 surviving copies where all-opposite placement
  leaves half the shards at exactly 1; cross-AZ replication streams halve
  (2 per shard against 4 — billed traffic at M4's 256 shards); §2.6 dissolves
  structurally; the fault-domain floor drops to `ceil((r+1)/2)`.
  Recorded honestly: a **full** AZ loss halts the cluster under any placement
  (half of 256 primaries is not an election majority), so this buys surviving
  copies and partial-degradation resilience, not full-AZ availability.
  Implementation notes for MR-1: unify on that formula in one shared
  function — spot-checked to agree with the planner's formula at r=1 for both
  2 and 3 AZs, so r=1 byte-identity holds, but MR-1 must prove that property
  with a test, not carry it from here. The replacement plan constraint asserts
  **P1** (per-shard AZ balance within 1), which at r=1 over 2 AZs is exactly
  equivalent to the old distinct-AZ property, and which implies "≥1 replica
  in a different AZ from its primary" at every r. It should be **renamed**
  (a name that says "distinct AZ" must not report true over a 3/2 split);
  `cluster_plan.schema.json`'s `constraints.required`,
  `scripts/assert_plan_constraints.py` and the one existing multi-replica
  planner test (`tests/planner/test_planner.py:56`, which asserts the old
  all-opposite property at r=2 over 2 AZs and **will fail under this policy
  as written**) move in the same commit, per the machine-readable-contract
  rule. Verify before renaming that `cluster_plan.json` appears in no
  gate-run diff view; if it does, keep the field name and declare the
  semantics change instead.

**§7.2 The topology pin (decides §2.4).** Recommendation: emit
`cluster-allow-replica-migration no` on every node when
`replicas_per_shard ≥ 2` — it states the actual intent (planned topology is
fixed; the validator enforces membership, so migration is never wanted),
against tuning `cluster-migration-barrier` numerically. Conditional emission
keeps r=1 runs byte-identical.

**§7.3 Where "1..4" lives.** Recommendation: a validation rule refusing
`replicas_per_shard > 4` outright (`config/validation.py`, new error code),
and refusing `< 1` for real (non-dry-run) execution while leaving today's
r=0 admissions (dry-run projections, single-AZ `non_ha_allowed`) untouched.
The schema keeps `minimum: 0`; the semantic layer owns the policy, as it does
for every other cap.

**§7.4 The M2 lanes (§2.5).** Recommendation: defer both fixes, declared here
and cross-referenced from `failover_timeline_slice_map.md` §1's existing
finding that `observer/failover_timeline.py` never runs on a real full-flow
run. If M2 is ever unparked, its first multi-replica run hits both.

**§7.5 The density refusal should name the knob.** Hoist the per-AZ
requirement into `min_fault_domains` for the multi-AZ case
(`nodehost_density.py:74` today computes it only for single-AZ) so the
refusal says `nodehosts_per_az must be ≥ K for this shard shape` instead of
the current message, which names neither. Under §7.1(b), K =
`ceil((r+1)/2)`; under (a), K = r.

**§7.6 Design-doc amendments (report, do not silently violate).**
`scalable_cluster_observability_design.md` §9.4's sentence "after the primary
is killed the affected shard temporarily has no replica" is false at r≥2 (the
success conditions above it are already r-parameterised and stay). §7.3's
singular "the owning replica" should read plural (the implementation already
waits on every replica). §14 already declares the affected-shard control
plane O(shard replicas), so r=4 stays inside the design's stated bounds.

## §8 The run ladder (for the implementing session; each rung stops and reports)

**MR-1 — fixes and hermetic proof, no gate run beyond controls.** Implement
§2.1, §2.2, §2.3 + §7.1 decision, §2.4 + §7.2, §7.3, §7.5; the §6 tests with
mutation checks. Acceptance: `repository.all` 92/92; **two real Docker
exact-50 at 25×1** with every mark identical to the current expectation
(7/7, 5/5, 6/8 with both inherited deltas, 5/6, 2/2) — proving the whole
program is a no-op at r=1, which is the property both §7.1 options and §7.2's
conditionality were chosen for.

**MR-2 — first multi-replica reality, Docker.** One Docker **25×1-50 control**
and two Docker **10×4-50** candidates at the same commit. The three-way diff
is the design: control vs frozen baseline proves no drift; candidate vs
control isolates the replica-count delta; the delta must match §5's
predictions (row law ≈980, safe_path string, canary 10, batch geometry,
9/12/15 unchanged) and contain nothing undeclared. Record the first r=4 RTO
and formation dwell as founding data. Watch §3.1 specifically — it is the
predicted intermittent failure.

**MR-3 — native, on the existing fleet.** Two native **10×4-50** on gce-m3b
(`nodehosts_per_az: 4`, 8 hosts), then one native **40×4-200** (shipped
knobs). Zero residue checked over ssh from outside, journals complete,
`host_evidence` complete, fault lane 9/12/15. This is the fleet's first
multi-replica evidence and the last gate before M4 planning.

**Out of this program's scope, listed so nobody adopts them silently:** the
exact-1280 `ExecutionProfile` and its safety exception (a validation-contract
change, operator-approved); `milestones/m4/milestone.json` rewritten from the
500/1000/2000 ladder to the 256×4 goal; the 52-host provisioning; multi-run
budgets per M4 rung (the failover-timeline work's variance finding); and
whether multi-replica baselines are frozen from MR-3 or from M4's first runs
(the M3 rule — freeze from the environment acceptance runs in — says M4's).

## §9 What this map did not do, honestly

No live cluster ran. Everything above about Valkey's own behaviour at 4
replicas — rank-delayed elections, diskless-sync grouping of concurrent first
syncs, sibling re-parenting after promotion — is expected from documented
behaviour of the pinned 9.1 line, not measured through this product. The
numbers nobody can predict from here: r=4 RTO, formation dwell under 4-way
sync fan-in, the §3.1 failure probability, the health-gate escalation shape
(its scale inversion is still unexplained at r=1), and whether the 240 s
window holds. That is what MR-2 exists to measure, and it is why the fixes in
§2 must land first — a first multi-replica run that fails inside a known
`//2` has measured nothing.
