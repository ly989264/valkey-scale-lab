# Milestone 1 v5 Goal Mode

V5 supersedes the frozen v4 run after its real-capture cache retained a Docker
permission failure across a capability change. The v4 state, event journal,
logs, and evidence remain immutable migration inputs.

Start or resume only through the controller:

```bash
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop_v5 doctor
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop_v5 migrate-v4 --state ../loop_evidence/meta_runs/milestone1-v4/state/loop_state.json
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop_v5 next
```

V5 preserves successful expensive-check caching but does not cache a real-gate
failure caused by unavailable or permission-denied Docker daemon access. This
allows a controller retry after the external capability changes without
perturbing product inputs or deleting controller state.

Follow only the returned work item. Use `evaluate`, `review`, or
`accept-evaluator-repair` as instructed until `DONE` or a genuine external
`BLOCKED` result.
