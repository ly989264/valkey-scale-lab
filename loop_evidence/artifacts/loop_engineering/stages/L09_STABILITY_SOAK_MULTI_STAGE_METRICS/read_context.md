# L09_STABILITY_SOAK_MULTI_STAGE_METRICS Read Context

Created: 2026-07-01T02:30:53.822971Z

## Files Read

- `README.md`: bootstrap repository entry; automatic loop excludes P14.
- `AGENTS.md`: controlling safety contract; no default 1000 nodes, no host network/firewall/routing mutation, real Valkey evidence must come from wrapper scripts, missing metrics explicit.
- `CODEX_START_HERE.md`: automatic completion through P13 only; P14 requires explicit opt-in and environment variable.
- `codex/phase_manifest.json`: default max nodes 100; automatic stop after P13; P14 non-automatic.
- `.github/workflows/codex-gates.yml`: baseline harness precheck, safety scan, unit tests.
- `.github/workflows/github-coverage-gates.yml`: stricter fast gates include loop validation, artifact audits, provenance, coverage, report, L08 fault/failover tests.
- `codex/loop_engineering/README.md`: loop artifacts must be committed under `artifacts/loop_engineering`.
- `codex/loop_engineering/00_OPERATING_CONTRACT.md`: harness-first flow, no weakening, all stage state must be persisted.
- `codex/loop_engineering/01_STAGE_LOOP_PROTOCOL.md`: Phase A-H stage loop; previous harness before current harness design.
- `codex/loop_engineering/02_AGENT_PROTOCOL.md`: required subagent roles and JSON outputs.
- `codex/loop_engineering/03_HARNESS_POLICY.md`: baseline commands, artifact-first constraints, real Valkey evidence requirements.
- `codex/loop_engineering/04_STAGE_MANIFEST.md`: selected next stage is L09; scope is multi-stage stability/soak metrics.
- `codex/loop_engineering/05_VALIDATION_COMMANDS.md`: required baseline, loop, audit, coverage, report, and real-gate validation command families.
- `codex/loop_engineering/06_STATE_AND_ARTIFACT_CONTRACT.md`: required stage directory files and JSON contracts.
- `artifacts/loop_engineering/global_loop_state.json`: L00-L08 PASS; current stage is L09.
- `artifacts/loop_engineering/stages/*/stage_result.json`: prior stages through L08 are PASS and pushed.

## L09 Requirements

L09 must extend stability/soak from short smoke into a multi-stage metric model: `baseline`, `steady`, `fault`, `recovery`, and `post-recovery`. Required harness coverage includes fake soak timeline tests, a small real soak gate, 30/50/100 bounded soak gates or explicitly gated resource-aware profiles, latency percentiles, memory growth/leak summaries, restart delta, error taxonomy, and baseline comparison.

## Constraints

- Do not run or count P14/1000 as real evidence.
- Do not mutate host networking, firewall, routing, interfaces, or unrelated processes.
- Any 30/50/100 soak profile must be bounded and resource-aware; short windows cannot claim long-run stability.
- Every soak profile must emit JSONL time series, and reports must read machine-readable artifacts only.
- Missing memory/restart/baseline metrics must be `MISSING` or `SKIPPED_WITH_REASON`, never invented.
- Previous harness must pass before designing L09 harness changes.

## Risks

- Real 30/50/100 soak gates may be resource/time expensive; L09 must use bounded profiles or record a genuine resource blocker.
- Existing P11 stability artifacts are small-real and may not have enough fields for all L09 metrics.
- Report additions must remain views over JSON/JSONL source artifacts.
- Running pytest/compileall can recreate local caches; use `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPYCACHEPREFIX=/private/tmp/valkey-scale-lab-pycache`, and pytest cache disablement where appropriate.
