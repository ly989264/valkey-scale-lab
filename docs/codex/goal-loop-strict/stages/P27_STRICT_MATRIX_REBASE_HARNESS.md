# P27_STRICT_MATRIX_REBASE_HARNESS — Strict Matrix Harness Rebase

## Purpose

Add the strict P27-P40 loop to the existing repository and harden the harness so the clarified target cannot be bypassed.

## Special bootstrap rule

Before P27 exists in `codex/phase_manifest.json`, `python3 scripts/codex_gate.py next` may report that all automatic phases are complete. The main agent must still implement P27 because the human has supplied a stricter goal.

P27 may edit harness files only to strengthen the harness and add P27-P40 support. It must document every harness edit.

## Required implementation

P27 must update or create:

```text
codex/phase_manifest.json
scripts/codex_gate.py
scripts/assert_strict_stage_contract.py
scripts/assert_no_bypass.py
scripts/assert_coverage_registry.py
scripts/assert_exact_scale_real_evidence.py
scripts/assert_quant_completeness.py
scripts/assert_management_matrix_strict.py
scripts/assert_fault_matrix_strict.py
scripts/assert_full_flow_e2e.py
scripts/assert_200_plus_dry_run.py
scripts/assert_analysis_provenance.py
scripts/assert_report_quality.py
scripts/assert_final_strict_closeout.py
schemas/artifact/* strict schemas as needed
tests/unit and tests/integration coverage for strict harness behavior
```

The exact implementation may add subpackages, but the CLI contract in `AGENTS.md` must remain compatible.

## Required manifest changes

```text
automatic_stop_after = P40_STRICT_FINAL_AUDIT_CLOSEOUT
append P27-P40 in order
P32, P35, P36 are bounded 200-node real exceptions
P37 is dry-run-only for >200 and must not require live Valkey
analysis/report stages require real artifact provenance
```

## Required P27 artifacts

```text
artifacts/phases/P27_STRICT_MATRIX_REBASE_HARNESS/phase_summary.json
artifacts/phases/P27_STRICT_MATRIX_REBASE_HARNESS/quant_summary.json
artifacts/phases/P27_STRICT_MATRIX_REBASE_HARNESS/harness_extension_report.json
artifacts/phases/P27_STRICT_MATRIX_REBASE_HARNESS/strict_manifest_report.json
artifacts/goal_loop_strict/P27_STRICT_MATRIX_REBASE_HARNESS/CONTEXT_RELOAD.md
artifacts/goal_loop_strict/P27_STRICT_MATRIX_REBASE_HARNESS/DESIGN_BRIEF.md
artifacts/goal_loop_strict/P27_STRICT_MATRIX_REBASE_HARNESS/WORKER_SUMMARY.md
artifacts/goal_loop_strict/P27_STRICT_MATRIX_REBASE_HARNESS/REVIEW.md
```

## Required gates

P27 must pass gates equivalent to:

```text
python3 scripts/codex_gate.py precheck --phase P27_STRICT_MATRIX_REBASE_HARNESS
python3 scripts/safety_scan.py
python3 -m compileall -q scripts src
python3 -m pytest -q tests/unit tests/integration
python3 scripts/assert_strict_stage_contract.py --phase P27_STRICT_MATRIX_REBASE_HARNESS
python3 scripts/assert_no_bypass.py --phase P27_STRICT_MATRIX_REBASE_HARNESS
python3 scripts/assert_coverage_registry.py --bootstrap-only
python3 scripts/codex_gate.py run --phase P27_STRICT_MATRIX_REBASE_HARNESS
python3 scripts/codex_gate.py postcheck --phase P27_STRICT_MATRIX_REBASE_HARNESS
```

## Pass criteria

P27 passes only when:

```text
P27-P40 are discoverable by the harness
P27-P40 stage documents exist and are cited
strict review artifacts are required for P27-P40
strict assertion scripts fail closed on missing files
existing P14 remains non-automatic
real >200 execution remains impossible by default
200-node bounded exceptions are exact and explicit
no real runtime capability is falsely claimed by P27
```

## Blocking conditions

```text
manifest cannot be validated
harness lock is weakened or bypassed
P27-P40 are not discoverable
postcheck ignores strict review
assertions pass on missing artifacts
P14 becomes automatic
>200 real execution becomes possible by default
```
