# Milestone 1 V8 Goal Start

V8 is the versioned successor to the sealed V7 controller kernel. It closes the
proven O1 retry-accounting gap without editing V7 code, control, state, or
evidence. The frozen V7 reproduction remains expected-failing historical proof;
the V8 successor test is an executable controller check.

The V8 migration accepts only the canonical sealed V7 iteration-3 state and
verifies its state/event seals, control/kernel/evaluator digests, active O1
PRODUCT_GAP, reviewer test anchor, failure log, and verified V6 receipt. It
preserves the already-consumed O1 attempt and review counters, starts O1 at
`REVERIFY`, and imports no PASS, cache, completion, or mutable reviewer check.

Check readiness without creating state:

```bash
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop_v8 doctor
```

After reviewing the migration receipt contract, create V8 state exactly once:

```bash
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop_v8 migrate-v7 \
  --state ../loop_evidence/meta_runs/milestone1-v7/state/loop_state.json
```

There is no bootstrap command. Once migrated, scheduling is controller-owned:

```bash
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop_v8 next
```

Run `evaluate`, `review`, or `accept-evaluator-repair` only for the active work
item returned by the controller. Do not manually edit controller state or rerun
unchanged failing and expensive checks outside the controller.
