# Milestone 1 v7 Goal Mode

V7 starts a new refactoring goal after the completed v6 Milestone 1 run. V6
source, control, state, logs, and evidence are historical and immutable. V7
must preserve the frozen safety and exact-scale behavior while separating Goal
scheduling, Gate orchestration, scenario definitions, execution, evidence
validation, analysis, and reporting behind explicit contracts.

Before product changes, verify and migrate the completed canonical v6 run:

```bash
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop_v6 doctor
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop_v6 next
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop_v7 doctor
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop_v7 migrate-v6 \
  --state ../loop_evidence/meta_runs/milestone1-v6/state/loop_state.json
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop_v7 next
```

`migrate-v6` is the only initialization path. It verifies completed v6 but
imports no objective status, attempts, review checks, cache entries, or PASS
results. V7 owns fresh state and fresh exact-50 and exact-200 evidence under
`../loop_evidence/meta_runs/milestone1-v7/`.

Follow only the work item returned by `next`. Use `evaluate`, `review`, or
`accept-evaluator-repair` as directed. Do not edit controller state, the v7
control block, the kernel manifest, kernel files, v6 files, or historical
evidence after migration. A kernel defect requires a new controller version.

Program checks run from Level 0 upward and stop on the first failure. The
controller-owned wrapper is the only path to real completion gates. Capture
and admission are distinct: evaluator changes invalidate admission without
turning an old admission into a new PASS. Product changes require fresh
capture.

The frozen scale contract remains unchanged:

- accept every exact requested node count from 30 through 2000;
- require real completion gates at exactly 50 and 200 nodes;
- keep 30 and 100 runnable but not required completion gates;
- never silently downscale;
- cap normal automatic development at 100 nodes;
- permit the required 200-node gate only as a controller-owned,
  preflight-gated bounded exception;
- never automatically execute above 200 nodes, and require explicit operator
  opt-in, resource preflight, and cost acknowledgement there.

Continue until `DONE` or a genuine external `BLOCKED` result.
