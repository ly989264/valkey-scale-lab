# Milestone 1 Goal Loop Entry

This is the only entry point for a new Codex App Goal-mode Milestone 1 run.
The loop state and current evidence are stored outside the project tree at
`../loop_evidence/meta_runs/milestone1-v2/`.

## Start

```bash
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop doctor
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop bootstrap
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop next
```

Give Codex the prompt in
`docs/codex/meta-m1/GOAL_MODE_START_PROMPT.md`. Thereafter the controller returns
exactly one of four actions:

- `WORK`: Codex chooses how to implement the objective, then runs `evaluate`.
- `REVIEW_ACCEPTANCE`: a fresh reviewer searches for one demonstrable uncovered
  requirement gap, then the main agent submits its JSON report with `review`.
- `REVIEW_REPLAN`: a fresh reviewer diagnoses stagnation and recommends a
  materially different focus, then the main agent submits its JSON report.
- `DONE` or `BLOCKED`: stop.

```bash
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop evaluate
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop review --report <review.json>
```

Do not edit `loop_state.json`, `events.jsonl`, the control block, controller
package, or exact-scale evaluator during a run. Do not run the 50/200 gates by
hand; the controller orders, caches, and budgets them.

The frozen scope and executable schedule are in
`codex/meta_m1/control_block.json`. Architecture and trust boundaries are in
`docs/codex/meta-m1/META_M1_ARCHITECTURE.md` and
`docs/codex/meta-m1/TRUST_AND_OPERATIONS.md`.
