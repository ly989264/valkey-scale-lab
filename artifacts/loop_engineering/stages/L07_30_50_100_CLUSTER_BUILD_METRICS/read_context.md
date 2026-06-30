# L07 Read Context

## Files Read

- `README.md`: bootstrap notes; automatic loop stops after P13 and P14 is not automatic.
- `AGENTS.md`: controlling safety and phase-loop contract; no default 1000-node run, no host-network mutation, real Valkey evidence must come from wrapper scripts, missing metrics must be explicit.
- `CODEX_START_HERE.md`: automatic loop through P13 only; P14 requires explicit opt-in environment variable.
- `codex/phase_manifest.json`: confirms automatic stop after `P13_SCALE_LADDER_50_100`; P12 and P13 contain real scale gates for 10/30/50/100, while P14 is opt-in dry-run/resource/planner only.
- `.github/workflows/codex-gates.yml`: base CI harness precheck, safety scan, compile, unit tests.
- `.github/workflows/github-coverage-gates.yml`: fast gates for precheck, safety, previous tests, audit/provenance/metric/report gates, P13/P14 audit, small-real parity audit.
- `codex/loop_engineering/README.md`: persistent loop-control artifact requirements.
- `codex/loop_engineering/START_MAIN_LOOP.md`: mandates sync check, reread, stage loop, subagents, validation, commit, and push.
- `codex/loop_engineering/00_OPERATING_CONTRACT.md`: harness-first flow, multi-agent role outputs, fallback isolated contexts if real subagents unavailable.
- `codex/loop_engineering/01_STAGE_LOOP_PROTOCOL.md`: Phase A through H requirements.
- `codex/loop_engineering/02_AGENT_PROTOCOL.md`: required JSON structure and roles.
- `codex/loop_engineering/03_HARNESS_POLICY.md`: previous harness baseline and artifact-first/real-Valkey requirements.
- `codex/loop_engineering/04_STAGE_MANIFEST.md`: `L07_30_50_100_CLUSTER_BUILD_METRICS` target and acceptance criteria.
- `codex/loop_engineering/05_VALIDATION_COMMANDS.md`: baseline commands, loop validation, audit, metric coverage, report validation, and scale preflight/gate commands.
- `codex/loop_engineering/06_STATE_AND_ARTIFACT_CONTRACT.md`: stage artifact layout and schemas.
- `artifacts/loop_engineering/global_loop_state.json`: L00 through L06 are PASS and pushed; current stage is `L07_30_50_100_CLUSTER_BUILD_METRICS`.
- `artifacts/loop_engineering/stages/*/stage_result.json`: prior stage results establish the pattern of evidence commit followed by result bookkeeping.
- Scale-related source and artifact references via `rg`: P12/P13 phase artifacts, `scripts/build_metric_coverage_matrix.py`, `scripts/build_provenance_graph.py`, `scripts/audit_p13_p14_scale.py`, `scripts/p13_optimization_gate.py`, `src/valkey_scale_lab/runtime/docker_runtime.py`, and related tests.

## Stage Summary

L07 must strengthen the 30/50/100 real-cluster scale build metrics and audit surface. The harness must cover resource preflight, process/container startup timing, cluster meet/create timing, slot assignment, role and membership convergence, SET/GET data-path proof, cleanup timing/residual scan, and consistency of 30/50/100 scale reporting.

## Constraints

- Do not run or mark P14 as real coverage. `P14_SCALE_1000_OPTIN_DRYRUN` remains forbidden without explicit current-session user opt-in and the required environment variable.
- Do not mutate host network configuration, firewall, routing, interfaces, or unrelated processes.
- Resource insufficiency for real scale runs must become `BLOCKED`, not `PASS`.
- Report files are views. L07 evidence must be machine-readable and schema-validated.
- Any missing scale build metric must be encoded as `MISSING`, `SKIPPED_WITH_REASON`, or `NO_BASELINE_YET`; values must not be invented.
- Real 30/50/100 evidence must trace to committed wrapper-produced artifacts or approved wrapper runs.

## Risks

- Historical P12/P13 artifacts may have partial timing fields; L07 must distinguish measured metrics from explicit gaps.
- 30/50/100 real gate reruns can be resource-heavy; preflight failures must be recorded as blockers.
- Existing P13 optimization artifacts may be related but must not be treated as canonical evidence unless provenance is explicit.
- It is easy to accidentally count P14 dry-run artifacts as real scale evidence; the harness must block that.
