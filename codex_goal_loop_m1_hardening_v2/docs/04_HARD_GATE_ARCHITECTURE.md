# 04_HARD_GATE_ARCHITECTURE.md

## Required gate framework

H00 must create the following gate family under `scripts/m1h/`:

```text
scripts/m1h/build_evidence_manifest.py
scripts/m1h/assert_evidence_taxonomy.py
scripts/m1h/assert_no_fixture_fallback.py
scripts/m1h/assert_no_legacy_m1_pass.py
scripts/m1h/assert_no_simulated_subagents.py
scripts/m1h/assert_stage_exit.py
scripts/m1h/assert_setup_core_metrics.py
scripts/m1h/assert_command_audit_real.py
scripts/m1h/assert_management_exact_scale.py
scripts/m1h/assert_workload_benchmark_strength.py
scripts/m1h/assert_fault_timeline_real.py
scripts/m1h/assert_system_metrics_real_windows.py
scripts/m1h/assert_report_input_quality.py
scripts/m1h/assert_final_milestone1_hardened.py
```

The exact names may be extended, but the capabilities above are mandatory.

## Gate result output

Every gate must write a JSON artifact under:

```text
runs/m1-hardening/<stage_id>/artifacts/gates/<gate_name>.json
```

Each gate result must include:

```json
{
  "schema_version": "v1",
  "artifact_type": "m1h_gate_result",
  "stage_id": "Hxx",
  "gate_name": "...",
  "status": "PASS|FAIL|BLOCKED_WITH_REASON",
  "checked_at": "...",
  "inputs": [],
  "violations": [],
  "blocked_reasons": [],
  "source_commit": "..."
}
```

## Exit code convention

- PASS -> exit 0
- FAIL -> exit 1
- BLOCKED_WITH_REASON -> exit 2 unless the stage explicitly allows blocked status

For final acceptance, `milestone1_status: BLOCKED_WITH_REASON` may still yield hardening-loop PASS, but never milestone PASS.
