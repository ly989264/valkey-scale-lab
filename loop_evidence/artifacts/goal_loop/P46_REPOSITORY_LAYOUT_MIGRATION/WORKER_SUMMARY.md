# WORKER_SUMMARY — P46_REPOSITORY_LAYOUT_MIGRATION

## Scope implemented

Physically migrated the runnable repository to `project/` and immutable loop evidence to `loop_evidence/`. Added fail-closed evidence/layout validation, schemas, tests, exact relative compatibility links, root navigation files, and CI project working directories. Historical evidence was not intentionally rewritten; the final validator again matches every baseline record.

## Changed files

| Path | Summary |
|---|---|
| `project/` | Canonical runnable project, active harness, code, config, schemas, docs, scripts, tests, and templates. |
| `loop_evidence/` | Canonical physical storage for artifacts, audits, runs, and retired loop packages. |
| `project/{artifacts,audit,runs,.github}` | Four exact relative compatibility links. |
| `AGENTS.md`, `README.md` | Thin repository-root navigation entry points. |
| `.github/workflows/*.yml` | Shell steps now run with `working-directory: project`; step coverage was retained. |
| `project/scripts/validate_repository_layout.py` | Baseline capture plus fail-closed layout/link/classification/integrity verification. |
| `project/scripts/validate_repository_layout_report.py` | Independent PASS semantic checks, including cross-field baseline/observed equality. |
| `project/schemas/artifact/{evidence_integrity,repository_layout_report}.schema.json` | P46 machine-readable contracts. |
| `project/tests/ci/test_repository_layout.py` | Deterministic digest, baseline rejection, link, and exclusion tests. |
| `project/schemas/historical/*`, `project/codex/historical_schema_compat_registry.json` | Read-only historical schema snapshots and exact artifact/schema/gate-manifest bindings. |
| `project/scripts/historical_schema_compat.py` | Shared current-first, exact-binding historical validation. |
| `project/tests/ci/test_historical_schema_compat.py` | Positive and fail-closed mutation/unregistered compatibility tests. |
| `project/scripts/*` path helpers | Preserve lexical `artifacts/...` identity when traversing compatibility symlinks. |
| `project/codex/{phase_manifest,gate_lock}.json` | P46 gate contract finalized and active controls re-locked. |
| `project/artifacts/harness_exception/P46_REPOSITORY_LAYOUT_MIGRATION.md` | Documents P46 strengthening and ten pre-existing stale schema lock digests. |

## Commands run

| Command | Result | Log/artifact path |
|---|---|---|
| baseline capture before migration | PASS: 17,555 files, 678,927,090 bytes | `artifacts/phases/P46_REPOSITORY_LAYOUT_MIGRATION/evidence_integrity.json` |
| `python3 scripts/validate_repository_layout.py ...` | PASS after migration and after testing | `artifacts/phases/P46_REPOSITORY_LAYOUT_MIGRATION/repository_layout_report.json` |
| `python3 scripts/codex_gate.py precheck --all` | PASS | console |
| compile + CLI help | PASS | `/tmp/p46_cli_help.txt` |
| focused migration/path regression selection | PASS: 12 tests | console |
| full non-real pytest, first run | FAIL: 15 failed, 609 passed, 2 skipped | superseded diagnostic run |
| exact historical-compatibility/audit/provenance selection | PASS: 30 tests | console |
| review-fix layout/schema negative tests | PASS: 9 tests | console |
| final review-fix `codex_gate.py run --phase P46_REPOSITORY_LAYOUT_MIGRATION` | PASS: 9/9 gates; 637 passed, 2 skipped; post-test integrity and semantics PASS | P46 gate result/log |

## Gates and assertions

| Gate/assertion | Result | Evidence path |
|---|---:|---|
| Root allowlist, classifications, and four link targets | PASS | `repository_layout_report.json` |
| Per-file historical evidence hash/size/type | PASS | `evidence_integrity.json`, `repository_layout_report.json` |
| Evidence and layout schemas | PASS | validator output |
| Harness lock/manifest precheck | PASS | console |
| Compile/import/CLI and migration-focused tests | PASS | console |
| P46 harness run | PASS | `artifacts/gates/P46_REPOSITORY_LAYOUT_MIGRATION/gate_result.json` |
| Post-test immutable evidence validation | PASS | final `repository_layout_post_test` gate |

## Artifacts produced

| Artifact | Schema/check | Result |
|---|---|---:|
| `evidence_integrity.json` | `evidence_integrity.schema.json` | PASS |
| `repository_layout_report.json` | `repository_layout_report.schema.json` | PASS |
| `phase_summary.json` | `phase_summary.schema.json` | PASS |

## Quantitative evidence summary

- Immutable historical baseline: `17,555` regular tracked files, `678,927,090` bytes.
- Aggregate tree SHA-256: `6f4232a19be65c1e0d5da0d0c8521e36e26e3facf4429d132f7dee1f7461b31f`.
- Final comparison: zero missing, zero changed, zero unexpected historical files.

## Cleanup summary

Removed only untracked `.DS_Store`, `.pycache`, and `.pytest_cache` metadata required by the root allowlist. A full-test invocation rewrote three tracked loop-engineering report views; they were immediately restored from their staged pre-migration blobs, and the complete immutable validator returned PASS afterward. No Docker, Valkey, network, or host resources were started.

## Deviations from design

The initial design did not anticipate clean-HEAD artifact/schema version drift. It was resolved without modifying current schemas or evidence: historical schema snapshots are locked, and compatibility requires current-schema failure plus exact artifact SHA-256, historical-schema SHA-256, and producing gate-manifest SHA-256 matches. P46/P40 manifest provenance and the immutable historical report/provenance pair use separate exact hash bindings. No wildcard compatibility exists.

## Remaining risks or `待验证`

No known failing test remains. Review should closely inspect registry exactness, negative mutation tests, and the post-test evidence gate. Any future artifact, historical schema, gate manifest, manifest extension, provenance report, or HTML mutation must fail closed rather than inherit compatibility.

Review FAIL findings P46-R1 and P46-R2 were addressed: PASS reports now require empty error/integrity lists, valid links, true classifications, and equal aggregate integrity fields through schema plus semantic validation; baseline loading recomputes all three per-root summaries. End-to-end temporary-tree tests cover missing/broken/absolute/escaping links, root/classification drift, missing/mutated/extra evidence, malformed aggregate/per-root data, and baseline immutability.

## Review handoff notes

Review the migration, exact compatibility registry, negative tests, PASS gate result, and final layout/evidence report independently. The main agent may proceed to fresh review; worker did not mark complete, commit, or push.
