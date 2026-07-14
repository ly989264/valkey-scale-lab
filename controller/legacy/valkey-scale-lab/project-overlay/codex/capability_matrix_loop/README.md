# Capability Matrix Loop

Supplemental loop for closing the Valkey capability matrix on top of the
completed P00-P13 harness. This loop does not replace or weaken the existing
phase harness.

Primary commands:

```bash
python3 tools/capability_matrix_gate.py next
python3 tools/capability_matrix_gate.py run --stage CML00_CAPABILITY_LOOP_BOOTSTRAP
```

All stage state is recorded under `artifacts/capability_matrix_loop/` and
`audit/capability_matrix_loop/`.
