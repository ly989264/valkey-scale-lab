# P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER — Coverage Registry and Scenario Compiler

## Purpose

Create the canonical strict coverage matrix and deterministic scenario plans for all later stages. This stage prevents ambiguous scope and prevents “we covered most of it” claims.

## Required implementation

P28 must implement:

```text
strict coverage registry generator
scenario compiler for management 50/100/200
scenario compiler for fault/failover 50/100/200
scenario compiler for full-flow E2E 50/100/200
scenario compiler for >200 dry-run targets
coverage ID validation
coverage status transition validation
coverage CSV export
```

## Required coverage registry outputs

```text
artifacts/coverage/strict_coverage_registry.json
artifacts/coverage/strict_required_matrix.csv
artifacts/coverage/strict_scenario_plan.json
artifacts/phases/P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER/coverage_registry_report.json
artifacts/phases/P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER/phase_summary.json
artifacts/phases/P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER/quant_summary.json
```

## Required matrix cells

The registry must contain every cell required by:

```text
docs/codex/goal-loop-strict/06_COVERAGE_REGISTRY_SPEC.md
docs/codex/goal-loop-strict/08_MANAGEMENT_OPERATION_MATRIX_SPEC.md
docs/codex/goal-loop-strict/09_FAULT_FAILOVER_MATRIX_SPEC.md
```

## Required gates

```text
python3 scripts/assert_coverage_registry.py --registry artifacts/coverage/strict_coverage_registry.json --require-all
python3 scripts/assert_strict_stage_contract.py --phase P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER
python3 scripts/assert_no_bypass.py --phase P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER
```

## Pass criteria

P28 passes only when:

```text
all required 50/100/200 lifecycle rows exist
all required 50/100/200 management rows exist
all required 50/100/200 fault rows exist
all required >200 dry-run rows exist for 201/250/300/500/1000
all rows have deterministic coverage IDs
all real rows start as PENDING, not PASS
all >200 rows are execution_mode=dry_run
scenario plans map rows to later stages
```

## Blocking conditions

```text
any required row missing
coverage IDs are non-deterministic
real required row starts as PASS without evidence
>200 row permits real execution
scenario compiler omits cleanup or telemetry
```
