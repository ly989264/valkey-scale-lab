# Context Reload: P36_FULL_FLOW_E2E_50_100_200_REAL

## Reload Metadata

- Reloaded at UTC: 2026-07-04T15:07:45Z
- Branch: codex/valkey-scale-lab-loop
- Current commit: 323ad65d4ce5d386afb15248e954791ed9778906
- `python3 scripts/codex_gate.py next`: P36_FULL_FLOW_E2E_50_100_200_REAL
- `git status --short`: clean before creating this reload artifact

## Required Documents Reread

1. `AGENTS.md`
2. `CODEX_START_HERE.md`
3. `CODEX_GOAL_LOOP_START.md`
4. `CODEX_STRICT_MATRIX_LOOP_START.md`
5. `docs/codex/goal-loop/00_INDEX.md`
6. `docs/codex/goal-loop/01_GOAL_CONTRACT.md`
7. `docs/codex/goal-loop/02_STAGE_MANIFEST.md`
8. `docs/codex/goal-loop/03_MULTI_AGENT_STAGE_PROTOCOL.md`
9. `docs/codex/goal-loop/04_CONTEXT_TRANSFER_PROTOCOL.md`
10. `docs/codex/goal-loop/05_STRONG_HARNESS_GATE_SPEC.md`
11. `docs/codex/goal-loop/06_QUANTIFICATION_SPEC.md`
12. `docs/codex/goal-loop/07_MANAGEMENT_OPS_SPEC.md`
13. `docs/codex/goal-loop/08_FAULT_MATRIX_SPEC.md`
14. `docs/codex/goal-loop/09_SCALE_AND_RESOURCE_POLICY.md`
15. `docs/codex/goal-loop/10_AUDIT_AND_COMMIT_POLICY.md`
16. `docs/codex/goal-loop-strict/00_INDEX.md`
17. `docs/codex/goal-loop-strict/01_STRICT_GOAL_CONTRACT.md`
18. `docs/codex/goal-loop-strict/02_STRICT_STAGE_MANIFEST.md`
19. `docs/codex/goal-loop-strict/03_MAIN_SUBAGENT_LOOP_PROTOCOL.md`
20. `docs/codex/goal-loop-strict/04_CONTEXT_LEDGER_PROTOCOL.md`
21. `docs/codex/goal-loop-strict/05_FAIL_CLOSED_HARNESS_CONTRACT.md`
22. `docs/codex/goal-loop-strict/06_COVERAGE_REGISTRY_SPEC.md`
23. `docs/codex/goal-loop-strict/07_QUANTIFICATION_DATA_CONTRACT.md`
24. `docs/codex/goal-loop-strict/08_MANAGEMENT_OPERATION_MATRIX_SPEC.md`
25. `docs/codex/goal-loop-strict/09_FAULT_FAILOVER_MATRIX_SPEC.md`
26. `docs/codex/goal-loop-strict/10_SCALE_EXECUTION_POLICY.md`
27. `docs/codex/goal-loop-strict/11_ANALYSIS_VISUAL_REPORT_SPEC.md`
28. `docs/codex/goal-loop-strict/12_AUDIT_COMMIT_NO_BYPASS_POLICY.md`
29. `docs/codex/goal-loop-strict/stages/P36_FULL_FLOW_E2E_50_100_200_REAL.md`
30. `artifacts/goal_loop_strict/STRICT_STAGE_JOURNAL.md`

## Stage Contract Summary

P36 must prove the full product flow at exact real scales 50, 100, and 200. For each scale, the stage must run or validate a real full-flow sequence: config validate, resource preflight, plan, cluster create, baseline workload, telemetry collection, representative management operation sequence, representative fault/failover sequence, recovery verification, analysis generation, report rendering, and cleanup verification.

Required P36 artifacts include `phase_summary.json`, `full_flow_matrix.json`, `full_flow_results.jsonl`, exact-scale scoped evidence under `full_flow_50/`, `full_flow_100/`, and `full_flow_200/`, canonical events and metrics, workload windows, quant summary, coverage ledger, and cleanup report.

Required gates include `assert_full_flow_e2e.py --scales 50,100,200`, exact-scale evidence checks for all three scoped artifact directories, quant completeness for `full_flow`, lifecycle coverage registry checks for scales 50/100/200, and cleanup assertion. P36 is blocked if any scale is omitted, the 200-node run downshifts, analysis/report uses fake data, cleanup fails, or full-flow artifacts are not tied to source evidence.

## Prior-Stage Journal Summary

P30-P32 completed exact-scale real management matrices for 50, 100, and 200 nodes. P33-P35 completed exact-scale real fault/failover matrices for 50, 100, and 200 nodes. P35 specifically proved exact 200-node real fault/failover evidence and strengthened the strict harness for P35 dispatch and sustained readiness. Lifecycle/full-flow rows, analysis/report aggregation, and >200 dry-run support remain incomplete after P35.

## Safety Constraints

- Do not fake real Valkey evidence.
- Do not downshift required 50/100/200 exact-scale runs, especially the 200-node full-flow bounded exception.
- Do not run real clusters above 200 nodes.
- Do not mutate host firewall, routing, PF, nftables, iptables, interfaces, or OS network services.
- Fault injection must stay within owned Docker/container namespaces, owned containers, or project-owned sandbox proxy paths.
- Do not manually edit gate results or phase state to force PASS.
- Do not mark complete, commit, or push before gates, review, postcheck, and mark-complete pass.

## Known Blockers

No blocker is known at reload time. Resource preflight for 200 nodes must pass before any real 200-node full-flow execution can be considered valid.

## Assumptions And 待验证

- 待验证: whether existing management and fault wrapper modules can be composed into a P36 full-flow orchestrator without rerunning every matrix row.
- 待验证: whether existing analysis/report commands can generate P36 scoped artifacts from P36 source evidence without scraping logs or relying on generated placeholders.
- 待验证: whether harness manifest already contains P36 full-flow gates or requires a strengthened `assert_full_flow_e2e.py` dispatch path.
