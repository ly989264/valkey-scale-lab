# Milestone 1 v4 Goal-Mode Start

The v3 `DONE` result is historical and not an admissible completion result.
Milestone 1 continues through the v4 controller, which separates expensive raw
real-cluster capture from evaluator-versioned admission.

Start from `project/`:

```bash
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop_v4 doctor
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop_v4 bootstrap
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop_v4 next
```

For each work item, follow the same WORK, RECOVERY_WORK, EVALUATOR_REPAIR,
REVIEW_ACCEPTANCE, and REVIEW_REPLAN transitions described in
`docs/codex/meta-m1/GOAL_MODE_START_PROMPT.md`, using `meta_loop_v4` for every
controller command.

The v4 completion boundary additionally requires:

- evaluator changes invalidate admission-cache entries while preserving valid
  raw real-cluster captures;
- scenario provenance comes from observed scenario operations, never list
  position or rewritten labels;
- lifecycle PASS timing comes from measured start/end bounds, never generated
  zero-duration defaults;
- exact 50 and 200 captures execute the complete management and fault matrix;
- the current evaluator admits both scales before final closure and review.

Never edit v3 or v4 controller state, event journals, control blocks, or kernel
files after a run is bootstrapped. Never rewrite historical evidence.
