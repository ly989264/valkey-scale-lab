# H06 Context Reload

stage_id: H06_WORKLOAD_BENCHMARK_HARDENING
source_commit_before: 038bf1cf50aa04b1c575352e4f326eeb91886e74

## Documents Reloaded

- `codex_goal_loop_m1_hardening_v2/START_HERE.md`: stage completion requires executable fail-closed gates, not Markdown notes.
- `codex_goal_loop_m1_hardening_v2/AGENTS_M1H_V2.md`: every stage must use real design, worker, and review subagents; stage completion requires code gates, artifacts, review PASS, commit, and push.
- `codex_goal_loop_m1_hardening_v2/docs/00_INDEX.md`: confirms the full hardening doc, contract, and stage set.
- `docs/01_PROBLEM_STATEMENT.md`: H06 directly addresses the prior false pass where workload benchmark evidence passed with only one metric row.
- `docs/02_NON_NEGOTIABLE_CONTRACT.md`: exact-scale missing evidence must be `BLOCKED_WITH_REASON`; fixtures, legacy evidence, skipped core metrics, fake or partial artifacts, and non-empty checks cannot satisfy PASS.
- `docs/03_EVIDENCE_TAXONOMY.md`: only `REAL_EXACT_SCALE` or allowed fully reconstructed real raw evidence can promote claims; fixture, legacy, dry-run, and small-smoke evidence cannot satisfy exact-scale workload claims.
- `docs/04_HARD_GATE_ARCHITECTURE.md`: H06 must use `scripts/m1h/assert_workload_benchmark_strength.py` and write gate JSON under `runs/m1-hardening/H06_WORKLOAD_BENCHMARK_HARDENING/artifacts/gates/`.
- `docs/05_EVIDENCE_MANIFEST_AND_CLAIM_LEDGER.md`: workload claims must be generated into `runs/m1-hardening/evidence_manifest.json`, not hand-edited.
- `docs/06_STAGE_PROTOCOL.md`: reload docs, write this context file, launch design, worker, and review subagents, then run `assert_stage_exit`.
- `docs/07_MULTI_AGENT_PROTOCOL.md`: role artifacts must be written in `agents/` with `agent_invocation: real_subagent`.
- `docs/08_CONTEXT_TRANSFER_PROTOCOL.md`: H06 must produce context, design, worker, review, completion, and next-stage handoff files.
- `docs/09_NO_SHORTCUT_RULES.md`: fixtures are limited to tests/parser/schema coverage; production acceptance cannot rely on fixture fallback or weak non-empty checks.
- `docs/10_ACCEPTANCE_MATRIX.md`: workload benchmark requires exact-scale claims at 30, 50, 100, and 200 nodes.
- `docs/11_REAL_SCALE_MATRIX.md`: exact-scale means 30/50/100/200 only; if resources are unavailable, the claim must be blocked with rerun guidance.
- `docs/12_REPORT_QUALITY_CONTRACT.md`: later reports cannot treat rendered output as proof of workload source quality.
- `docs/13_BLOCKED_STATUS_POLICY.md`: blocked claims must include precise capability, scale, reason, required artifacts, missing fields, and rerun command.
- `docs/14_GIT_PROTOCOL.md`: H06 must commit only this stage's work and push before moving to H07.
- `docs/15_REVIEW_RUBRIC.md`: review must inspect gates, manifest, diff, exact-scale claims, shortcut risks, and handoff sufficiency.
- `docs/16_FAILURE_MODES.md`: H06 must specifically prevent single-row workload metrics, skipped core metrics, legacy-only evidence, and report-only evidence from passing.
- `docs/17_COMMANDS_AND_GATES.md`: common compile, test, fixture, legacy, subagent, and stage-exit gates are required.
- `docs/18_STAGE_EXIT_CONTRACT.md`: stage exit must verify all gate results, review PASS, forbidden shortcut scan, completion references, and manifest update.
- `docs/19_FINAL_HANDOFF_CONTRACT.md`: final milestone can PASS only if every required workload claim passes; otherwise milestone must be blocked.
- `docs/20_SELF_AUDIT_OF_PREVIOUS_PACKAGE.md`: v2 hardening must keep false PASS prevention machine-checkable.

## Contracts Reloaded

- `C00_GATE_SCRIPT_MANIFEST.md`: `assert_workload_benchmark_strength.py` is mandatory.
- `C01_EVIDENCE_MANIFEST_SCHEMA.md`: workload claims require evidence kind, source artifacts, semantic checks, and status.
- `C02_STAGE_STATUS_SCHEMA.md`: stage status must record review, gates, claims, commit, and push.
- `C03_MILESTONE_ACCEPTANCE_SCHEMA.md`: milestone PASS cannot include blocked workload claims.
- `C04_EXACT_SCALE_REQUIREMENTS.md`: required workload claim ids are `workload_benchmark.real_exact.{30,50,100,200}`.
- `C05_STATIC_FORBIDDEN_PATTERNS.md`: production gates must not accept `metric_count > 0` or fixture fallback as real proof.
- `C06_SETUP_TELEMETRY_CONTRACT.md` and `C07_COMMAND_AUDIT_CONTRACT.md`: H06 should preserve earlier setup and command audit fail-closed checks.
- `C08_WORKLOAD_BENCHMARK_CONTRACT.md`: workload PASS requires profiles `smoke`, `uniform`, `hotspot`, `mixed_rw`, `write_heavy`, `read_heavy`; windows `baseline`, `pre_event`, `event`, `recovery`, `post_recovery`, `all_run`; required QPS, throughput, operation, error, latency, timeout, connection, and redirection metrics; enough rows; connections/pipeline evidence or explicit block; minimum operations per window; and full-slot coverage for non-smoke profiles.
- `C09_FAULT_TIMELINE_CONTRACT.md`, `C10_SYSTEM_METRICS_CONTRACT.md`, and `C11_REPORT_INPUT_QUALITY_CONTRACT.md`: later stages will depend on workload windows and cannot promote fake, partial, or low-quality workload inputs.
- `C12_NO_SIMULATED_SUBAGENT_CONTRACT.md`: H06 artifacts must not contain forbidden shortcut phrases.

## Current Repository State

- Current branch is `codex/valkey-scale-lab-loop` at `038bf1cf50aa04b1c575352e4f326eeb91886e74`.
- H05 was committed and pushed. Its gate artifact `assert_management_exact_scale.json` passed while keeping `management_matrix.real_exact.{50,100,200}` blocked.
- `scripts/m1h/assert_workload_benchmark_strength.py` is currently only the generic capability wrapper; H06 must replace or strengthen it with workload-specific fail-closed logic.
- `scripts/m1h/manifest.py` currently gives workload benchmark only weak checks: `exact_scale_observed`, `workload_windows_present`, and `qps_latency_error_metrics_present`.
- Existing H05 management workload checks enforce numeric fields for management windows, but they do not satisfy the C08 benchmark profile/window/depth contract.

## H06 Starting Risk

The known unacceptable state is a workload benchmark claim promoting with too few metric rows or without required profiles, windows, metrics, full-slot coverage, connections, pipeline, real Valkey 9.1.x evidence, and explicit blocked reasons. H06 must make that impossible through manifest semantics, a stage-specific gate, tests, real subagent artifacts, and `assert_stage_exit`.
