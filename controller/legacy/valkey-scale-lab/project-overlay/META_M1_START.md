# Milestone 1 Goal Loop Entry

This is the entry point for the v3 Codex App Goal-mode loop. V3 preserves the
blocked v2 work through a verified migration and stores new state under
`../loop_evidence/meta_runs/milestone1-v3/`. V2 remains read-only.

## Resume The Existing Run

From this `project/` directory:

```bash
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop doctor
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop migrate-v2 \
  --receipt ../loop_evidence/meta_runs/milestone1-v3/migration/v2_snapshot_receipt.json
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop next
```

`migrate-v2` is idempotent. It imports O1-O4 as completed but requires one
full non-real regression before O5 can resume. The old 50-node admission
is quarantined as raw evidence; it is not treated as a v3 PASS.

## Controller Actions

- `WORK`: fix the current product gap, then run `evaluate`.
- `RECOVERY_WORK`: fix migration/full-regression failures, then run `evaluate`.
- `EVALUATOR_REPAIR`: strengthen only the returned versioned-evaluator
  allowlist; the already-failing hermetic tests remain immutable. Then run
  `accept-evaluator-repair`.
- `REVIEW_ACCEPTANCE`: submit `NO_GAP`, or one reproduced GAP classified as
  `PRODUCT_GAP` or `EVALUATOR_GAP`.
- `REVIEW_REPLAN`: submit a diagnosis and materially different focus.
- `DONE` or `BLOCKED`: stop.

```bash
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop evaluate
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop accept-evaluator-repair
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop review --report <review.json>
```

Never edit v2/v3 state by hand. Never modify the Controller Kernel or Goal
Contract during a run. Current-run evidence checks belong in the evaluator;
repository tests must be hermetic. Real gates may write only their v3 run root.

The Goal-mode prompt is in
`docs/codex/meta-m1/GOAL_MODE_START_PROMPT.md`; the frozen schedule is
`codex/meta_m1/control_block.json`.
