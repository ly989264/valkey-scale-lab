# Harness Exception — P32_MANAGEMENT_MATRIX_200_REAL

## Defect

`scripts/assert_quant_completeness.py` was already the strict quantification gate for management stages, but before P32 it recognized only:

- `P30_MANAGEMENT_MATRIX_50_REAL`
- `P31_MANAGEMENT_MATRIX_100_REAL`

That meant the P32 manifest's required command:

```text
python3 scripts/assert_quant_completeness.py --phase P32_MANAGEMENT_MATRIX_200_REAL --category management --scale 200
```

could not apply the strict management artifact semantics to the 200-node stage. Leaving the script unchanged would weaken the P32 harness by allowing the command to succeed without P32-specific management checks.

## Patch

The P32 worker made the smallest strengthening change:

- added `P32_MANAGEMENT_MATRIX_200_REAL` to `STRICT_MANAGEMENT_STAGES`;
- required exact scale `200`;
- required coverage prefix `200.management.`;
- required timing artifact `runtime_timing_breakdown_strict_management_matrix_200.json`;
- refreshed only the corresponding locked hash in `codex/gate_lock.json`.

No schema, gate result, or phase state file was manually edited.

## Before And After Behavior

Before:

- P30/P31 management quant artifacts were checked strictly.
- P32 management quant artifacts were not matched by the strict management stage table.

After:

- P30/P31 behavior is preserved.
- P32 must emit the same strict management artifact family with exact `scale=200`, `node_count=200`, 11 operation rows, 11 coverage passes, real data-path evidence, cleanup PASS, canonical workload windows, and no forbidden missing placeholders.

This change preserves the original fail-closed requirement and strengthens P32 coverage.

## Follow-Up Patch: Inner P32 Setup Timeout

Fresh P32 gate evidence showed the outer manifest gate already allowed 7200 seconds, but the inner `scripts/valkey_e2e_gate.py` wrapper still used its default setup timeout of 900 seconds:

```text
TimeoutExpired(..., 900)
```

The follow-up worker added only P32-specific bounded wrapper arguments to the `real_valkey_e2e` manifest command:

```text
--setup-timeout 2400 --probe-timeout 10
```

This does not change the required 200-node scale, evidence semantics, cleanup assertion, or the outer 7200-second manifest timeout. It strengthens the bounded 200-node run by aligning the inner setup budget with the already-approved outer gate budget, while preserving fail-closed behavior if setup still exceeds the explicit bound.
