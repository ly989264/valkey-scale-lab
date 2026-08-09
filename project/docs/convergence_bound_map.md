# Map: the post-formation convergence bound

Narrow scope on purpose. This is about one constant -
`CONVERGENCE_TIMEOUT_SECONDS` in `observability/cluster.py:43` - and the wait it
bounds. It is not about the whole-fleet cadence item, which is a different
defect in the same file. Written before changing anything, argued from
measurement taken 2026-08-09 at `4dd0fa1b`.

## What was measured

A harness ran the product's own formation unmodified, then replaced everything
downstream with an observation loop calling `FullClusterValidator` with
`convergence_timeout=0.0` - one observation per round, the same call the failover
lane already uses - so it measured the same predicate the bound is applied to,
without applying the bound. 900s window.

| Run | Converged | Rounds | Distinct laggards | Persistent unhealthy node |
| --- | --- | --- | --- | --- |
| exact-30 | 26.53s | 14 | - | none |
| exact-200 A | 102.46s | 49 | 4 | none |
| exact-200 B | 152.03s | 72 | 7 | none |
| exact-200, real gate run | >180s, failed | 86 | - | - |

Neither exact-200 run had a node that stayed unhealthy across all rounds, and
neither ever raised `SemanticFailure`. Given 900s, both settled well inside it.
**So the failure is a bound that is too tight, not a cluster that does not
converge.**

## The structure, which is what decides the fix

Convergence is a strictly serialised queue. Exactly one node is unhealthy at any
moment; it clears, then the next appears, with no overlap:

    run A   a0e68e70  0.00→ 49.00s   4d70d4f8 51.13→ 72.44s
            3016b1e0 74.56→ 76.70s   bd816ff2 78.84→100.31s  → healthy 102.46s

    run B   12e490c7  0.00→  6.39s   03140b58  8.52→ 27.73s
            3da15025 29.87→ 42.70s   6eb1744e 44.84→ 49.12s
            b2ff4626 51.25→ 93.96s   fb255699 96.10→119.72s
            ea3dbf4f121.87→149.87s                           → healthy 152.03s

This is the mechanism the constant's own comment describes - a replica reports
`loading` until each observer learns its non-zero replication offset through
gossip - resolving one replica at a time rather than in parallel. So

    convergence ≈ (replicas still loading) × (per-laggard clear time)

Run A drew 4 laggards, run B drew 7. Per-laggard spans were 2.1s to 49.0s, the
longest being 49.00s (A) and 42.71s (B). The variance between runs is in the
**count**, not the per-node time.

## Two defects, not one

1. **The bound is calibrated at the wrong scale.** Its comment claims "roughly 3x
   headroom over that tail", measured on exact-50. Against the same code:
   30 nodes 26.5s (6.8x), 200 nodes 102-152s (**1.2-1.8x**). The headroom is
   already gone at 200, and because the queue is serialised, convergence grows
   roughly linearly with replica count. A fixed 180s cannot survive M4's 500,
   1000 and 2000.
2. **The bound cannot tell a slow cluster from a stuck one.** Both spend the full
   budget and both report the same `ConvergenceFailure`. That is the defect that
   actually matters: at 2000 nodes a genuinely stuck node would take the whole
   bound to report something knowable in a fraction of it, and a healthy cluster
   would be rejected for the same reason.

## The options

**A. Keep it fixed, raise the number.** Rejected. Three samples cannot pick a
constant; it would replace one under-measured number with another. It also fixes
only defect 1 and leaves defect 2 untouched.

**B. Scale-aware: bound = f(node_count).** Fits the mechanism - queue length
grows with replica count - and the two anchors (26.5s at 30, ~127s mean at 200)
are roughly linear. But the constant of proportionality is the *per-laggard clear
time*, which depends on host speed and gossip, so it still needs re-calibration
per environment, and it still cannot separate slow from stuck.

**C. Progress-aware: fail when the unhealthy set stops changing, with an absolute
ceiling.** Progress is scale-free, so the same rule is right at 30, 200 and 2000
without a per-scale number. It separates slow from stuck - the distinction the
measurement was run to make - and reports a stuck node *sooner* at large scale
rather than later, so it tightens the check rather than loosening it. It needs an
absolute ceiling anyway, because "laggards keep arriving forever" is otherwise
unbounded.

**Recommended: C, with B's shape used only for the ceiling.** The primary
condition becomes a no-progress window; the ceiling is a backstop whose job is to
bound the run, not to discriminate, so it can be generous and scale-proportional.

## The non-obvious part, which a plausible implementation would get wrong

Progress must be measured as **departures from the unhealthy set, by identity**,
not as the set's size.

In both runs the set held exactly one node from the first round to the last:
`first_round_unhealthy_count` 1, `last_round_unhealthy_count` 1. The size never
decreased until it hit zero. An implementation that failed when "the count has
not decreased for N seconds" would fire on a perfectly healthy 200-node cluster
within the first minute. The signal is that `a0e68e70` left and `4d70d4f8`
arrived - membership churn - which is only visible if identities are tracked.

The stuck case is then exactly the complement: the same id present in every round
of the window with no departures. The harness already computes that discriminator
(`unhealthy_in_every_round`) and it separated the two hypotheses cleanly, which is
the empirical argument that the metric works.

## Sizing the window, and what is still unmeasured

A no-progress window has to exceed the longest single laggard span, which is the
quantity that must be calibrated. Observed maxima: **49.00s** and **42.71s**,
across two runs at one scale on one host. That is thin - a third run could show
80s.

But it is thin about a **scale-invariant** quantity. Total convergence time grows
with node count and so must be re-measured at every scale; per-laggard clear time
should not, and can be sampled at exact-30 as cheaply as at exact-200. That is
the substantive reason to prefer C: it moves the calibration burden onto
something that does not move.

Not decided here, and deliberately: the window's value. It wants more samples,
including at 30 and at least one at a scale between, before a number is written
down. This map argues the shape, not the constant.

## Blast radius

Small, which is the other reason to do it now.

- `CONVERGENCE_TIMEOUT_SECONDS` and `CONVERGENCE_POLL_SECONDS` are read in one
  place: the `FullClusterValidator.__init__` defaults (`cluster.py:823-824`).
- Seven `FullClusterValidator(...)` call sites in `src/`. Exactly one passes an
  explicit `convergence_timeout` (`docker_runtime.py:8935`, the failover lane's
  `0.0` single-observation call); the other six take the default and would take
  the new behaviour without changing.
- **No test pins 180.0.** The tests that exercise convergence pass explicit
  values (30.0, 5.0, 1.0), so they keep working and stay meaningful.
- The design document does not fix this bound. §9.3's 500ms / two-consecutive-
  rounds rule governs the *failover* lane, not formation, and §17 leaves
  implementation choices open provided semantics do not change. Waiting longer or
  shorter for the same predicate does not change what is checked, so this is an
  implementation constant with a documented rationale - it needs its own
  evidence, not a contract amendment.
- Existing precedent for progress-based conditions in this codebase:
  `AffectedShardObserver` requires two identical healthy rounds (§9.3), and the
  Sentinel probe counts a stability streak that any failure resets (§7.6, design
  line 309). C is the same shape applied to formation.

## What must not change

`ConvergenceFailure` stays a `SemanticFailure`, so an exhausted bound is still a
`FAIL` and never an `ERROR`: the cluster was observed and did not reach the
expected state. Nothing here interacts with the ERROR verdict work. §12.1's
retry-once rule is about collector failure and is untouched.

The predicate itself - every node `online` or `healthy` in `CLUSTER SHARDS`
across three observers - does not move. Only the waiting rule does. A change that
narrowed what counts as healthy would be softening the contract to make the
symptom disappear, which is what this map exists not to do.

## Acceptance for this change

- Hermetic: a fake validator whose unhealthy set churns by identity while never
  shrinking must converge, not time out - the exact case a size-based rule gets
  wrong. A fake whose set holds one id must fail, and fail *before* the absolute
  ceiling. Both directions, since the danger is a rule that never fails.
- Real: two exact-200 formation runs through the harness above, both converging,
  with the no-progress window never approached. One exact-30 to confirm the rule
  is scale-free rather than tuned to 200.
- The three failing observations in this map's table are the regression cases: a
  run drawing ~9 laggards must now pass, and that is the run the current bound
  rejects.
- `./gate suite repository.all` at 91/91, and a real exact-50 pair, because six
  call sites take the new default.
