# Milestone 1 v6 Goal Mode

V6 supersedes the frozen v5 run after v5 successfully captured the exact
50-node lifecycle but its evaluator computed the product digest with an older
controller-specific helper. V5 state, journal, logs, and evidence are immutable.

Start or resume only through the controller:

```bash
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop_v6 doctor
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop_v6 migrate-v5 --state ../loop_evidence/meta_runs/milestone1-v5/state/loop_state.json
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop_v6 next
```

The migration verifies the v5 event chain, state seal, successful capture
result, current product digest, and every manifest artifact hash. V6 then runs
only corrected admission against that read-only 50-node capture. Its own
evidence root is reserved for the required 200-node capture.

Follow only the returned work item until `DONE` or a genuine external
`BLOCKED` result.
