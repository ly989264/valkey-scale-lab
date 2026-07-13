# Milestone 1 V9 Goal Start

V9 is the versioned successor to the sealed V8 O1 controller-kernel gap. It
does not edit V7 or V8 kernel, control, evaluator, state, tests, or evidence.
Both frozen expected-failing reproductions remain historical proof and have
passing, kernel-sealed V9 successors.

The V9 migration accepts only the canonical sealed V8 iteration-2 state. It
verifies the V8 state and event seals, current control/kernel/evaluator digests,
the O1 PRODUCT_GAP test, anchor and failure log, and the complete V7/V6 receipt
chain. O1 starts at `REVERIFY` with its current attempt budget and two consumed
review rounds. It imports no PASS, cache, completion, or mutable reviewer check.

Check readiness without creating state:

```bash
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop_v9 doctor
```

After reviewing the migration contract, create V9 state exactly once:

```bash
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop_v9 migrate-v8 \
  --state ../loop_evidence/meta_runs/milestone1-v8/state/loop_state.json
```

There is no bootstrap command. Once migrated, scheduling remains
controller-owned:

```bash
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop_v9 next
```

Run `evaluate`, `review`, or `accept-evaluator-repair` only for the active work
item. A passing O1 `VERIFY` completes O1 because the preserved review budget is
already exhausted, then advances directly to O2.
