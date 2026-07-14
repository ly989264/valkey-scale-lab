# 02_STRICT_STAGE_MANIFEST.md — Stages P27-P40

The existing repository may already contain and complete P00-P26. The strict loop appends P27-P40. P27 is a bootstrap stage that updates the manifest and harness to recognize the stricter goal.

## Stage list

| Stage ID | Title |
|---|---|
| P27_STRICT_MATRIX_REBASE_HARNESS | Strict matrix harness rebase |
| P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER | Coverage registry and scenario compiler |
| P29_QUANT_TELEMETRY_COLLECTOR_HARDENING | Quant telemetry collector hardening |
| P30_MANAGEMENT_MATRIX_50_REAL | Real 50-node management matrix |
| P31_MANAGEMENT_MATRIX_100_REAL | Real 100-node management matrix |
| P32_MANAGEMENT_MATRIX_200_REAL | Real 200-node management matrix |
| P33_FAULT_FAILOVER_MATRIX_50_REAL | Real 50-node fault/failover matrix |
| P34_FAULT_FAILOVER_MATRIX_100_REAL | Real 100-node fault/failover matrix |
| P35_FAULT_FAILOVER_MATRIX_200_REAL | Real 200-node fault/failover matrix |
| P36_FULL_FLOW_E2E_50_100_200_REAL | Full-flow E2E at 50/100/200 |
| P37_200_PLUS_DRY_RUN_SUPPORT | 200+ node dry-run support |
| P38_CROSS_SCALE_ANALYSIS_REGRESSION | Cross-scale quantitative analysis and regression |
| P39_VISUAL_REPORT_QUALITY_GATE | Visual report quality gate |
| P40_STRICT_FINAL_AUDIT_CLOSEOUT | Strict final audit closeout |

## Required manifest behavior

P27 must update `codex/phase_manifest.json` and harness code so that:

```text
automatic_stop_after = P40_STRICT_FINAL_AUDIT_CLOSEOUT
P14_SCALE_1000_OPTIN_DRYRUN remains non-automatic
P27-P40 are automatic unless the stage document explicitly says otherwise
real 200-node stages are bounded exceptions and do not raise default_max_nodes above 100
>200 support is dry-run-only and must not require live Valkey
analysis/report stages require real artifact provenance even if they do not start new clusters
```

## Stage dependency chain

```text
P27 harness rebase
  -> P28 coverage registry
    -> P29 telemetry collector
      -> P30 management 50
        -> P31 management 100
          -> P32 management 200
            -> P33 fault/failover 50
              -> P34 fault/failover 100
                -> P35 fault/failover 200
                  -> P36 full-flow E2E 50/100/200
                    -> P37 >200 dry-run support
                      -> P38 cross-scale analysis
                        -> P39 visual report quality
                          -> P40 final strict audit closeout
```

Do not reorder stages. Do not combine stage commits.

## Required common artifacts for every P27-P40 stage

Every strict stage must produce these Markdown artifacts:

```text
artifacts/goal_loop_strict/<STAGE_ID>/CONTEXT_RELOAD.md
artifacts/goal_loop_strict/<STAGE_ID>/DESIGN_BRIEF.md
artifacts/goal_loop_strict/<STAGE_ID>/WORKER_SUMMARY.md
artifacts/goal_loop_strict/<STAGE_ID>/REVIEW.md
artifacts/goal_loop_strict/<STAGE_ID>/COMPLETION.md    # only after pass
artifacts/goal_loop_strict/<STAGE_ID>/BLOCKED.md       # only when blocked
```

Every strict stage must produce or update:

```text
artifacts/goal_loop_strict/STRICT_STAGE_JOURNAL.md
artifacts/phases/<STAGE_ID>/phase_summary.json
artifacts/phases/<STAGE_ID>/quant_summary.json
artifacts/gates/<STAGE_ID>/gate_result.json
audit/<STAGE_ID>/AUDIT.md
audit/<STAGE_ID>/audit_decision.json
```

Real execution stages must additionally produce:

```text
artifacts/phases/<STAGE_ID>/valkey_e2e_evidence.json
artifacts/phases/<STAGE_ID>/cleanup_report.json
artifacts/phases/<STAGE_ID>/events.jsonl
artifacts/phases/<STAGE_ID>/metrics_timeseries.jsonl
artifacts/phases/<STAGE_ID>/workload_windows.json
artifacts/phases/<STAGE_ID>/coverage_ledger.json
```

## Required common gates

Each stage manifest entry must include gates equivalent to:

```text
python3 scripts/codex_gate.py precheck --phase <STAGE_ID>
python3 scripts/safety_scan.py
python3 -m compileall -q scripts src
python3 -m pytest -q tests/unit tests/integration
python3 scripts/assert_strict_stage_contract.py --phase <STAGE_ID>
python3 scripts/assert_no_bypass.py --phase <STAGE_ID>
```

Real execution stages must include exact-scale real Valkey gates and cleanup gates. Analysis/report stages must include provenance and report quality gates. Dry-run stages must include no-runtime-created gates.

## Strict stage close rule

A stage can close only after:

```text
design subagent produced DESIGN_BRIEF.md
worker subagent produced WORKER_SUMMARY.md
all gates passed
review subagent produced REVIEW.md with Decision: PASS
audit files cite gate result SHA and every required artifact
postcheck passed
mark-complete passed
stage commit was created
stage commit was pushed
COMPLETION.md records commit hash and push result
```

If any item is missing, the stage remains incomplete.
