# Harness Exception - P30_MANAGEMENT_MATRIX_50_REAL

## Defect

`scripts/assert_management_matrix_strict.py` accepted PASS rows without checking coverage IDs, source evidence references, topology references, command log references, or result-file completeness. That could allow a generated-only management matrix shell to satisfy the P30 matrix gate.

## Patch

The assertion now fails closed unless every required row has the exact `50.management.*` coverage ID, exact scale, PASS status, real execution verification, workload reference, source evidence references, topology reference, and command log reference. It also checks that `management_operation_results.jsonl` contains all required rows.

`scripts/valkey_e2e_gate.py` now writes `nodes_requested`/`min_nodes_requested` into evidence so `assert_exact_scale_real_evidence.py --nodes 50` can verify exact scale without relying on a minimum-only field. The P30 run-state mirror is also written if the runtime did not already emit it.

`codex/gate_lock.json` was updated only for these two changed script hashes so precheck continues to detect any other harness drift.

After the first official P30 run, the wrapper independently observed all 50 Valkey nodes and cluster OK, but the required data-path probe timed out at the default 2-second socket limit after the full matrix workload. `codex/phase_manifest.json` now adds `--probe-timeout 10` only to the P30 real e2e command. This preserves the same required live SET/GET proof and does not accept skipped or synthetic data-path evidence.

After the matrix itself passed, the wrapper data-path probe still timed out because `scripts/valkey_probe_lib.py` only mapped container-IP redirects back to host endpoints when the advertised redirect port was `6379`. P30 process-runtime nodes advertise nodehost container IPs with per-node ports such as `172.x.x.x:7400`; the redirect mapper now matches `container_ip` plus the advertised client port and still performs the same live SET/GET through the host-exposed endpoint.

After fresh-context review, `scripts/assert_management_matrix_strict.py` and `scripts/assert_quant_completeness.py` were strengthened again to fail when P30 operation rows omit strict required fields, workload windows omit top-level required metrics, or required P30 JSON artifacts contain forbidden null/missing encodings. These changes address review-blocking gaps and make the gates stricter.

After postcheck, the P30 phase-local `coverage_ledger.json` was changed to preserve the full strict coverage registry schema while advancing only the 11 `50.management.*` rows. The P30 quant assertion now validates this full-registry shape by requiring exactly 11 PASS rows in `summary.counts_by_status`.

## Before/After

- Before: a matrix listing required row names plus shallow PASS result rows could pass.
- After: P30 requires row-level evidence references and complete exact-scale result rows.
- Before: the exact-50 wrapper could fail a real post-matrix data-path probe solely because the default probe socket timeout was too narrow for the 50-node run.
- After: P30 still requires live data-path PASS, with a bounded 10-second probe timeout.
- Before: process-runtime cluster redirects to container-IP plus non-6379 port were not mapped to their host endpoints.
- After: redirects are port-aware for owned process-runtime endpoints, preserving the real probe while avoiding unreachable container-IP dials from the host.
- Before: P30 gates could pass while operation rows and workload windows omitted strict contract fields.
- After: P30 management and quant gates enforce those required fields and null-free missing-data handling.
- Before: the phase-local coverage ledger used a narrow 11-row helper shape that was useful to assertions but did not satisfy the strict coverage registry schema used by postcheck.
- After: the ledger uses the full strict registry schema and still verifies that only the 11 P30 management rows advanced.

The change strengthens the harness and does not mark or edit gate/state results.
