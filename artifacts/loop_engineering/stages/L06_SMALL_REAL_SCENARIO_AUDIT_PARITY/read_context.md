# L06_SMALL_REAL_SCENARIO_AUDIT_PARITY Read Context

## Files Read

- `README.md`: repository is a Codex bootstrap for `valkey-scale-lab`; automatic loop stops after P13 and P14 is not automatic.
- `AGENTS.md`: controlling repository instruction; requires `CODEX_START_HERE.md` before edits, real Valkey evidence from wrapper scripts from P03 onward, no host network mutation, no fake-only real claims, deterministic cleanup, and explicit missing metrics.
- `CODEX_START_HERE.md`: automatic phase loop completes at P13; P14 requires explicit opt-in environment and must not be automatic.
- `codex/phase_manifest.json`: P03-P11 define the small-real six-node surfaces used by L06: cluster smoke, management ops, workload smoke, observability smoke, fault sandbox, failover primary stop, reporting source, orchestration, stability, and cleanup. P12/P13 are scale gates; P14 is optional dry-run only.
- `.github/workflows/codex-gates.yml`: CI compiles harness scripts, runs `precheck --all`, safety scan, and unit tests.
- `.github/workflows/github-coverage-gates.yml`: CI runs all prior loop audit, provenance, metric coverage, P13/P14 audit, and loop report rendering gates.
- `codex/loop_engineering/README.md`: loop engineering overlays strict state, artifact, multi-agent, and commit/push controls on top of existing harness.
- `codex/loop_engineering/START_MAIN_LOOP.md`: requires startup sync checks, fresh read at each stage, previous harness baseline, subagents, validation, commit, push, then immediate continuation.
- `codex/loop_engineering/00_OPERATING_CONTRACT.md`: requires harness-first order, separate subagent outputs, artifact-first evidence, no harness weakening, no missing-metric fabrication.
- `codex/loop_engineering/01_STAGE_LOOP_PROTOCOL.md`: Phase A through H sequence; L06 must run previous harness before designing current harness.
- `codex/loop_engineering/02_AGENT_PROTOCOL.md`: required subagent roles and JSON schema contract.
- `codex/loop_engineering/03_HARNESS_POLICY.md`: previous harness baseline commands; real Valkey evidence must verify Valkey 9.1.x, node count, cluster state, data path, cleanup, schema validation.
- `codex/loop_engineering/04_STAGE_MANIFEST.md`: L06 goal is audit/metric/report parity for the six-node real scenario before large-cluster expansion.
- `codex/loop_engineering/05_VALIDATION_COMMANDS.md`: baseline, loop-engineering, audit, metric coverage, reporting, and small-real Valkey validation command inventory.
- `codex/loop_engineering/06_STATE_AND_ARTIFACT_CONTRACT.md`: required stage artifacts and JSONL command log shape.
- `artifacts/loop_engineering/global_loop_state.json`: L00-L05 are PASS; current stage is L06.
- `artifacts/loop_engineering/stages/*/stage_result.json`: L00-L05 passed and were pushed. L03 records known missing split-brain metrics, L04/L05 deliberately did not rerun P14 or real wrappers.
- `artifacts/loop_engineering/reports/coverage_matrix.{json,csv}`: existing small-real surfaces are marked covered from committed artifacts, but L06 must audit parity rather than rely on report views.
- `artifacts/phases/P03_LOCAL_DOCKER_VALKEY` through `artifacts/phases/P11_STABILITY_SOAK`: committed small-real evidence and cleanup artifacts exist for the L06 surfaces.

## Current Stage Definition

L06 requires parity for the six-node real scenario across:

1. cluster smoke
2. management ops
3. workload smoke
4. observability smoke
5. fault sandbox
6. failover primary stop
7. stability soak
8. cleanup

Acceptance requires fake tests and real Valkey six-node gate coverage, unified metric extraction for every real scenario, explicit `MISSING` for failover split-brain if unmeasured, and reports that distinguish measured, missing, and skipped values.

## Constraints

- Do not run `P14_SCALE_1000_OPTIN_DRYRUN`; only audit P14 dry-run/opt-in boundaries unless the user explicitly opts in during this Codex App session.
- Do not mutate host network configuration, host firewall, routing, interfaces, or unrelated processes.
- Fault work must remain scoped to owned Docker/container namespaces or sandbox proxy artifacts.
- Do not present report-rendered data as source-of-truth; L06 artifacts must be derived from machine-readable source artifacts.
- Do not mark L06 PASS if fresh real Valkey validation is required but resources are unavailable. Record a blocker instead.
- Missing values must be encoded as `MISSING`, `SKIPPED_WITH_REASON`, or `NO_BASELINE_YET`; do not invent metrics.

## Risks

- Existing coverage reports already show small-real coverage; L06 must not merely re-render those views. It needs an artifact-level parity audit with schema and tests.
- P07/P08 evidence includes fault/failover-specific behavior where data-path or split-brain signals may be skipped or missing; L06 must preserve those semantics.
- Running fresh real gates may require Docker/Valkey resources. If unavailable, the stage cannot pass on static artifacts alone unless the designed L06 scope explicitly audits committed real evidence and the real-gate freshness requirement is satisfied by existing committed evidence.
- Baseline compile/test commands can create bytecode under tracked paths if not run with bytecode controls; use `PYTHONDONTWRITEBYTECODE=1` and/or `PYTHONPYCACHEPREFIX=/private/tmp/...`.
