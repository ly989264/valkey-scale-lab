# L08_30_50_100_FAULT_FAILOVER_SCENARIOS Read Context

Read timestamp: 2026-06-30T14:35:00Z

## Files Read

- `README.md`: confirms the repository is driven by `CODEX_START_HERE.md`, `AGENTS.md`, and the automatic loop; P14 is not automatic.
- `AGENTS.md`: controlling instructions. Non-negotiable safety includes no host network/firewall/routing/interface mutation, no default 1000 nodes, deterministic cleanup/state/ownership, real Valkey wrappers for real evidence, and explicit `MISSING`/`SKIPPED_WITH_REASON` semantics.
- `CODEX_START_HERE.md`: phase loop contract, automatic stop after P13, and P14 only with explicit opt-in plus required environment variable. L08 must not run P14.
- `codex/phase_manifest.json`: automatic Valkey phase manifest and real-wrapper expectations. P08 failover uses `scripts/fault_failover_gate.py`; P14 remains non-automatic.
- `.github/workflows/codex-gates.yml`: CI precheck, safety scan, script compile, and unit tests.
- `.github/workflows/github-coverage-gates.yml`: current broad fast gates include baseline tests, loop validation, committed artifact audit, provenance, scale build metrics, metric coverage, P13/P14 audit, small real parity audit, reports, and L07 scale-build tests.
- `codex/loop_engineering/README.md`: loop-engineering artifacts and state must be committed; stages require reread, harness-first design, multi-agent outputs, validation, commit, and push.
- `codex/loop_engineering/START_MAIN_LOOP.md`: every stage start must reread the required files, write `read_context.md`, choose the first incomplete stage, run the full stage protocol, and continue immediately after push.
- `codex/loop_engineering/00_OPERATING_CONTRACT.md`: previous harness must pass before current harness design; harness weakening requires a change request; all role outputs must be structured JSON.
- `codex/loop_engineering/01_STAGE_LOOP_PROTOCOL.md`: Phase A through H flow. L08 is currently in Phase A, then must run previous harness before design agents.
- `codex/loop_engineering/02_AGENT_PROTOCOL.md`: requires `requirements_analyst`, `harness_architect`, `risk_auditor`, `implementation_worker`, `review_agent`, `validation_agent`, and `anti_regression_guardian` JSON outputs.
- `codex/loop_engineering/03_HARNESS_POLICY.md`: previous harness baseline commands and real Valkey evidence boundaries. Resource preflight failure cannot be marked PASS.
- `codex/loop_engineering/04_STAGE_MANIFEST.md`: selected stage is `L08_30_50_100_FAULT_FAILOVER_SCENARIOS`. It must extend 30/50/100 fault/failover scenarios with fake deterministic tests, real gates for 30/50/100, safety guard, failover schema, and workload before/during/after windows.
- `codex/loop_engineering/05_VALIDATION_COMMANDS.md`: baseline validation and real Valkey wrapper guidance; 1000 dry-run commands are documented but forbidden for this session without explicit opt-in.
- `codex/loop_engineering/06_STATE_AND_ARTIFACT_CONTRACT.md`: required stage artifact layout and schemas for `stage_state.json`, command logs, and `stage_result.json`.
- `artifacts/loop_engineering/global_loop_state.json`: L00 through L07 are PASS and pushed; current stage is `L08_30_50_100_FAULT_FAILOVER_SCENARIOS`.
- `artifacts/loop_engineering/stages/*/stage_result.json`: L00-L07 results are PASS with pushed evidence commits. L06 records small-real failover split-brain duration as explicit `MISSING`; L07 records 30/50/100 cluster-build evidence and P14 dry-run-only boundary.

## Stage Summary

L08 must build or audit large-cluster fault/failover capability for 30, 50, and 100 real Valkey nodes. Required outputs per rung are:

- `fault_report_<N>.json`
- `failover_report_<N>.json`
- `workload_window_report_<N>.json`
- `valkey_e2e_evidence_fault_<N>.json`
- `cleanup_report_fault_<N>.json`

Required metrics include fault apply/clear latency, promotion observed, failover latency, cluster state and nodes observed before/during/after, availability window, workload errors/timeouts before/during/after, split-brain indicators or explicit missing reason, and cleanup residual count.

## Constraints

- Run previous harness baseline before designing L08-specific harness.
- Do not run P14 or any 1000-node real gate. P14 can only be boundary-audited as dry-run/planner/resource metadata unless the user explicitly opts in in this Codex App session and the required environment variable is set.
- Do not mutate physical host network configuration, global firewall, routing, PF, nftables, iptables, host interfaces, or unrelated processes.
- Fault injection must be scoped to owned Docker/container namespaces, owned containers, or explicit sandbox proxy layers.
- Real evidence must come from `scripts/fault_failover_gate.py`, `scripts/fault_safety_gate.py`, or `scripts/valkey_e2e_gate.py` as appropriate; project tests alone cannot be counted as real Valkey proof.
- Resource insufficiency for 30/50/100 real gates is a blocker, not a passing condition.
- Missing metrics must be encoded as `MISSING` or `SKIPPED_WITH_REASON`; values must not be invented.
- Report and visualization outputs remain views over machine-readable artifacts.

## Risks

- 30/50/100 real fault/failover gates may exceed local Docker resources. If preflight fails, L08 must write blocker artifacts rather than claim PASS.
- Large-cluster fault injection can accidentally cross the safety boundary if implementation uses host network commands; L08 harness must block host-level route/firewall/interface mutation.
- Existing small-real P08 failover evidence intentionally lacks split-brain timing; L08 must either measure it safely for large rungs or preserve explicit missing semantics.
- Workload windows around fault events can be misrepresented if they are derived from summaries instead of timestamped artifacts.
- Historical reports currently show failover coverage for small-real only; L08 must not count fake or small-real data as 30/50/100 coverage.
