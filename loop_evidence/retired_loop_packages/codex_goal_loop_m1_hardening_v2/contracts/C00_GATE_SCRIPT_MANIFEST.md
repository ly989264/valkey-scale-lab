# C00 Gate script manifest

H00 must implement this gate family under `scripts/m1h/`. Each script must have unit tests and must write gate result JSON.

| Script | Purpose |
|---|---|
| `build_evidence_manifest.py` | classify all candidate artifacts and write `runs/m1-hardening/evidence_manifest.json` |
| `assert_evidence_taxonomy.py` | validate evidence kinds, source paths, required fields |
| `assert_no_fixture_fallback.py` | reject fixture fallback for milestone PASS |
| `assert_no_legacy_m1_pass.py` | reject legacy-only evidence as M1 PASS |
| `assert_no_simulated_subagents.py` | reject simulated agent artifacts |
| `assert_stage_exit.py` | enforce stage exit conditions |
| `assert_setup_core_metrics.py` | validate real setup core telemetry |
| `assert_command_audit_real.py` | validate command log/audit semantics |
| `assert_management_exact_scale.py` | validate management matrix exact-scale M1 format |
| `assert_workload_benchmark_strength.py` | validate workload benchmark depth |
| `assert_fault_timeline_real.py` | validate real fault timeline |
| `assert_system_metrics_real_windows.py` | validate system metrics windows/scales |
| `assert_report_input_quality.py` | validate report source evidence quality |
| `assert_final_milestone1_hardened.py` | final hardened acceptance |
