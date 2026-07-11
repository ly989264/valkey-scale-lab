# L10_FULL_CHAIN_FINAL_AUDIT_AND_VISUALIZATION_GATE Read Context

## Files Read

- `README.md`: Project bootstrap, automatic loop stops before P14.
- `AGENTS.md`: Controlling safety rules, artifact-first evidence, real Valkey boundary, and P14 opt-in prohibition.
- `CODEX_START_HERE.md`: Automatic phases complete through P13; P14 requires explicit opt-in and `VSLAB_ALLOW_1000_DRYRUN`.
- `codex/phase_manifest.json`: Automatic Valkey phases cap default development at 100 nodes and require Valkey 9.1.x evidence for real gates.
- `.github/workflows/*.yml`: CI requires precheck, safety scan, committed artifact audit, provenance, metric coverage, report rendering, scale, stability, and fault/failover gates.
- `codex/loop_engineering/README.md`: Loop state and stage artifacts are persistent audit evidence.
- `codex/loop_engineering/00_OPERATING_CONTRACT.md`: Must run previous harness, design harness first, use subagents, then validate, commit, and push.
- `codex/loop_engineering/01_STAGE_LOOP_PROTOCOL.md`: Stage phases A-H and required artifact layout.
- `codex/loop_engineering/02_AGENT_PROTOCOL.md`: Required subagent roles and JSON output contract.
- `codex/loop_engineering/03_HARNESS_POLICY.md`: Previous harness baseline and anti-regression rules.
- `codex/loop_engineering/04_STAGE_MANIFEST.md`: L10 requires a final audit gate and full-chain report/coverage/provenance validation.
- `codex/loop_engineering/05_VALIDATION_COMMANDS.md`: Baseline, audit, metric coverage, report, real-gate, dry-run, and git validation command list.
- `codex/loop_engineering/06_STATE_AND_ARTIFACT_CONTRACT.md`: Stage state, commands log, result, and global loop state contracts.
- `artifacts/loop_engineering/global_loop_state.json`: L00-L09 are PASS and pushed; L10 is the next incomplete stage.
- `artifacts/loop_engineering/stages/*/stage_result.json`: Prior stage result shape and completion evidence.

## Current Stage

`L10_FULL_CHAIN_FINAL_AUDIT_AND_VISUALIZATION_GATE`

## Relevant Constraints

- Do not run `P14_SCALE_1000_OPTIN_DRYRUN` or set `VSLAB_ALLOW_1000_DRYRUN`.
- Final audit must cover fake, small-real, 30/50/100-real, and 1000-dry-run boundaries without counting dry-run as real.
- Reports and visualizations must be generated from machine-readable artifacts, not used as source truth.
- Missing metrics require explicit `MISSING`, `SKIPPED_WITH_REASON`, or `NO_BASELINE_YET` semantics with reasons and impact.
- Any final gate must preserve previous harness behavior and cannot weaken schemas/tests/scripts to pass.

## Risks

- Final audit could accidentally treat P14 dry-run/planner artifacts as real Valkey coverage.
- Regenerating reports can create unrelated timestamp churn; L10 must keep final artifacts deterministic or document source hashes.
- Broad CI commands may create local cache pollution unless run with `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPYCACHEPREFIX=/private/tmp/valkey-scale-lab-pycache`, and `pytest -p no:cacheprovider`.
