# DESIGN_BRIEF — P46_REPOSITORY_LAYOUT_MIGRATION

## Objective

Physically separate the runnable repository into `project/` and the immutable historical evidence into `loop_evidence/`, while preserving the existing project-root-relative interface through fail-closed compatibility links. The migration must retain every historical evidence byte, keep GitHub discovery at the repository root, and leave P46 auditable through the normal gate/review/postcheck flow without starting Valkey resources.

## Repository findings

- The worktree started P46 with 17,555 tracked files under `artifacts/`, `audit/`, and `runs/`, totaling 678,927,090 bytes: `artifacts/` 16,157 files/348,468,164 bytes, `audit/` 144 files/363,367 bytes, and `runs/` 1,254 files/330,095,559 bytes. These are the pre-migration historical baseline figures; P46's own new files must be excluded from that immutable set.
- Historical evidence is not disposable output. `AGENTS.md` declares machine-readable artifacts to be the product, and manifests, provenance checks, reports, tests, and scripts contain many project-root-relative `artifacts/`, `audit/`, and `runs/` references. Rewriting those historical references would invalidate content hashes and is forbidden.
- The runtime package and most harness/test code derive their root from the location of `scripts/` or `tests/`. Moving the complete runnable tree together under `project/` preserves that convention. Commands must thereafter run with `project/` as the current directory.
- `scripts/codex_gate.py` executes gates with its own parent directory as `ROOT`, so `project/scripts/codex_gate.py` will naturally use `project/` as its root. Its artifact and audit paths therefore require links inside `project/`.
- GitHub requires workflows to remain at repository-root `.github/workflows/`. Existing tests and `codex/gate_lock.json` also resolve `.github` relative to the project root, so `project/.github -> ../.github` is required in addition to setting CI's run working directory.
- The locked control set includes `.github/workflows/codex-gates.yml`, `AGENTS.md`, all active start documents, `codex/phase_manifest.json`, `docs/codex/**`, schemas, scripts, and templates. They belong in `project/`, not in historical evidence.
- The two old packaged instruction trees are self-contained and all their stages are complete. They are candidates for `loop_evidence/retired_loop_packages/`; no external runtime dependency was found in the initial scan, but the full test gate must confirm this claim.
- `P46_REPOSITORY_LAYOUT_MIGRATION` is non-automatic, so `codex_gate.py next` continues to print `COMPLETE_AUTOMATIC_PHASES`. P46 must be addressed explicitly with `--phase P46_REPOSITORY_LAYOUT_MIGRATION` and must not be mistaken for an automatic next stage.
- The current P46 harness exception says only the manifest digest will be refreshed. That is insufficient if the new validator, schemas, stage document, or changed workflow remain outside the lock. The exception and final lock update must describe and protect every new/changed P46 control rather than weakening lock coverage.

## Files expected to change

| Path | Change type | Reason |
|---|---|---|
| `project/` | New primary directory via tracked moves | Canonical runnable project root. |
| `project/{codex,config,docs,schemas,scripts,src,templates,tests,tools}` | Move, contents preserved except P46 additions | Active implementation and harness control surface. |
| `project/{AGENTS.md,CODEX_GOAL_LOOP_START.md,CODEX_START_HERE.md,CODEX_STRICT_MATRIX_LOOP_START.md,README.md,pyproject.toml,requirements-dev.txt}` | Move/update only where paths or usage text require it | Active entry points and build metadata. The full `AGENTS.md` must remain here unchanged except required P46 path guidance. |
| `project/artifacts` | New relative symlink to `../loop_evidence/artifacts` | Preserve all legacy artifact paths and new gate writes from project cwd. |
| `project/audit` | New relative symlink to `../loop_evidence/audit` | Preserve audit/postcheck paths. |
| `project/runs` | New relative symlink to `../loop_evidence/runs` | Preserve run-scoped paths. |
| `project/.github` | New relative symlink to `../.github` | Let locks/tests inspect the root-discovered workflows without duplicating them. |
| `loop_evidence/{artifacts,audit,runs}` | Move, byte-for-byte | Canonical physical location for historical and future evidence. |
| `loop_evidence/retired_loop_packages/` | New directory via moves | Hold `codex_goal_loop_m1/`, `codex_goal_loop_m1_hardening_v2/`, `GOAL_LOOP_PACKAGE_README.md`, `MILESTONE1_GOAL_LOOP_PACKAGE_README.md`, `MILESTONE1_HARDENING_V2_README.md`, and `PACKAGE_FILE_MANIFEST.md`. |
| `.github/workflows/codex-gates.yml` | Update | Keep root discovery; apply `working-directory: project` to shell steps and retain all gates. |
| `.github/workflows/github-coverage-gates.yml` | Update | Apply `working-directory: project` to shell steps while retaining coverage/audit behavior. |
| `AGENTS.md` | Replace with thin root entry point | Direct agents to `project/AGENTS.md` and require work from `project/`; do not duplicate the full contract. |
| `README.md` | Replace with thin root entry point | Explain the two-directory layout and direct users to `project/README.md`. |
| `.gitignore` | Update if necessary | Ensure caches below `project/` remain ignored; do not ignore `loop_evidence/`. |
| `project/scripts/validate_repository_layout.py` | Add | Capture/verify the evidence inventory and validate allowlist, classifications, and links fail closed. |
| `project/schemas/artifact/evidence_integrity.schema.json` | Add | Validate the immutable evidence baseline. |
| `project/schemas/artifact/repository_layout_report.schema.json` | Add | Validate the layout/link/integrity result. |
| `project/tests/ci/test_repository_layout.py` | Add | Cover valid layout and failure cases in temporary trees. |
| `project/codex/phase_manifest.json` | Finalize P46 contract | Ensure commands are correct from project cwd and required artifacts/gates are complete. |
| `project/codex/gate_lock.json` | Refresh and strengthen | Lock the finalized manifest, changed workflows, P46 stage contract, validator, and schemas. |
| `project/docs/codex/goal-loop/stages/P46_REPOSITORY_LAYOUT_MIGRATION.md` | Move as active document; amend only if contract correction is needed | Preserve authoritative stage scope. |
| `loop_evidence/artifacts/harness_exception/P46_REPOSITORY_LAYOUT_MIGRATION.md` | Amend through compatibility path | Cite all necessary protected-control changes and before/after behavior accurately. |
| `loop_evidence/artifacts/phases/P46_REPOSITORY_LAYOUT_MIGRATION/*` | Add | Required machine-readable P46 outputs. |
| `loop_evidence/artifacts/goal_loop/P46_REPOSITORY_LAYOUT_MIGRATION/*` | Continue/add | Structured stage handoffs, review, and completion through `project/artifacts` link. |
| `loop_evidence/audit/P46_REPOSITORY_LAYOUT_MIGRATION/*` | Add during review | Fresh audit decision through `project/audit` link. |

The root allowlist must be exact: `.git`, `.github`, `.gitignore`, `AGENTS.md`, `README.md`, `project`, and `loop_evidence`. Ignored `.DS_Store`, `.pycache`, and `.pytest_cache` entries must be removed before layout validation, not archived. No root `artifacts`, `audit`, or `runs` alias is needed.

## Implementation plan

1. Add the two schemas, the layout validator, and isolated validator tests before moving directories. The validator must support a separate baseline-capture operation and a verification operation; verification must never rewrite its baseline.
2. Capture the pre-migration baseline over the 17,555 currently tracked legacy evidence files only. Store for each logical legacy path its byte count and SHA-256, plus aggregate file count, byte count, and a deterministic tree digest. Exclude all P46-created paths (`artifacts/phases/P46_*`, `artifacts/gates/P46_*`, `artifacts/goal_loop/P46_*`, `artifacts/harness_exception/P46_*`, and `audit/P46_*`) to avoid self-reference. Preserve logical paths such as `artifacts/phases/P45_...` in the baseline even though physical paths later gain `loop_evidence/`.
3. Create `project/` and `loop_evidence/`; use tracked moves for the exact classifications above. Do not edit files while moving the immutable baseline set. Move retired packages as complete directory trees so their internal relative references remain meaningful.
4. Add the four exact relative compatibility links: `project/artifacts -> ../loop_evidence/artifacts`, `project/audit -> ../loop_evidence/audit`, `project/runs -> ../loop_evidence/runs`, and `project/.github -> ../.github`. Reject absolute links, broken links, alternate targets, and canonical targets escaping their allowed locations.
5. Leave root `.github` canonical. Update both workflows using job-level `defaults.run.working-directory: project` or equivalent explicit step settings. Do not apply `working-directory` to `uses:` steps. Verify that all shell steps execute from `project/` and that tests can read workflows through `project/.github`.
6. Replace root `AGENTS.md` and `README.md` with minimal navigation documents. Keep the complete governing `AGENTS.md` and full project README under `project/`. Remove ignored cache/OS metadata from the root so the allowlist is genuinely clean.
7. Run the validator in verification mode. It must compare each baseline logical path against `loop_evidence/<logical path>`, check all three evidence trees and retired-package classification, validate links and root allowlist, and emit `repository_layout_report.json` plus a P46 `phase_summary.json`. It must not rewrite historical JSON/JSONL, embedded paths, reports, or checksums.
8. Finalize manifest commands and the harness exception, then refresh `gate_lock.json` only after all P46 control files and workflow changes are final. The lock must continue to resolve from `project/`; `project/.github` supplies the locked workflow path.
9. Run gates, obtain fresh review, then postcheck and mark complete from `project/`. Commit/push remain main-agent actions after PASS.

## Harness, schema, and gate plan

`evidence_integrity.schema.json` should require: schema/artifact version, hash algorithm (`sha256`), canonical record format, explicitly listed excluded P46 prefixes, source logical roots, per-root and aggregate file/byte counts, deterministic tree digest, and per-file records containing logical path, type, byte count, and SHA-256. Timestamps may be recorded but must not participate in the tree digest.

`repository_layout_report.schema.json` should require: `PASS`/`FAIL`, repo/project/evidence roots, expected and observed root entries, unexpected entries, per-category classification results, all required link strings and resolved targets, baseline versus observed counts/bytes/tree digests, missing/changed/unexpected evidence lists, and errors. Empty error lists and exact equality are required for PASS. Missing data must use the repository's explicit missing/reason vocabulary rather than invented values.

The validator must fail closed for: absent or extra root entries; a required directory in the wrong bucket; missing/broken/absolute links; link targets outside the exact allowed target; any baseline file missing, changed, non-regular, or at the wrong mapped path; count/byte/digest mismatch; duplicate logical paths; malformed baseline; retired package left in `project/`; or generated evidence left outside `loop_evidence/`. It should report errors before returning nonzero and use atomic writes for reports.

The existing P46 manifest command assumes the gate runs from `project/`, which is correct after the move. Baseline capture is a worker preparation step, not part of the verification gate. The verification gate must treat `evidence_integrity.json` as read-only input and write only the layout report/phase summary.

The harness lock must include the P46 validator, both new schemas, the P46 stage document, finalized manifest, active workflows, and any changed active control document. Existing locked files must retain their content hashes when only moved. The harness exception must be updated to state this strengthening; retaining its current “update only manifest digest” wording would make the stage review fail.

No real-Valkey gate is required. P46 is storage-only (`max_nodes: 0`, `real_valkey_required: false`) and must not create containers or mutate networking.

## Test plan

- Validator unit/CI tests in temporary directories: exact valid layout; each missing link; broken link; absolute link; traversal/out-of-tree target; swapped evidence target; unexpected root entry; project file misclassified; retired package left in project; missing baseline file; same-size content mutation; extra historical evidence; byte/count/tree digest mismatch; malformed and duplicate baseline entries; P46 exclusions; verification does not rewrite baseline.
- Schema-positive and schema-negative fixtures for both new schemas, including a report that claims PASS while containing errors or mismatched digests.
- From repository root, verify only thin entry points and the two primary storage directories remain by running the layout validator.
- From `project/`: `python3 scripts/codex_gate.py precheck --all`; `PYTHONPYCACHEPREFIX=/tmp/vslab_pyc python3 -m compileall -q scripts src`; `python3 -m valkey_scale_lab.cli --help`; schema validation for both P46 artifacts; and `PYTHONPYCACHEPREFIX=/tmp/vslab_pyc python3 -m pytest -q --ignore=tests/real_valkey`.
- Explicitly test both root workflows' path-sensitive CI tests through `project/.github`, and inspect that every `run:` step uses project cwd without reducing the pre-existing step set.
- Run `python3 scripts/codex_gate.py run --phase P46_REPOSITORY_LAYOUT_MIGRATION`, inspect gate stdout/stderr, then have the main agent run postcheck only after fresh review.
- Compare the final evidence report to the pre-migration fixed baseline: 17,555 files and 678,927,090 bytes plus exact per-file and tree SHA-256 equality. P46's own mutable artifacts are checked by schemas/postcheck, not folded into the historical baseline.

## Required artifacts

- `artifacts/phases/P46_REPOSITORY_LAYOUT_MIGRATION/phase_summary.json`
- `artifacts/phases/P46_REPOSITORY_LAYOUT_MIGRATION/evidence_integrity.json`
- `artifacts/phases/P46_REPOSITORY_LAYOUT_MIGRATION/repository_layout_report.json`
- `artifacts/goal_loop/P46_REPOSITORY_LAYOUT_MIGRATION/CONTEXT_RELOAD.md`
- `artifacts/goal_loop/P46_REPOSITORY_LAYOUT_MIGRATION/DESIGN_BRIEF.md`
- `artifacts/goal_loop/P46_REPOSITORY_LAYOUT_MIGRATION/WORKER_SUMMARY.md`
- `artifacts/goal_loop/P46_REPOSITORY_LAYOUT_MIGRATION/REVIEW.md`
- `audit/P46_REPOSITORY_LAYOUT_MIGRATION/AUDIT.md`
- `audit/P46_REPOSITORY_LAYOUT_MIGRATION/audit_decision.json`
- Normal harness-generated `artifacts/gates/P46_REPOSITORY_LAYOUT_MIGRATION/gate_result.json` and stdout/stderr logs.

All paths above are logical project-root paths and, after migration, physically resolve beneath `loop_evidence/` through the required links.

## Safety considerations

- Never delete, regenerate, normalize, reformat, or line-ending-convert historical evidence. Use moves and verify content before and after.
- Do not treat `artifacts/` as cache: it contains product evidence and provenance chains. P46 exclusions apply only to the new stage's mutable outputs.
- Do not preserve compatibility with permanent duplicate copies. Canonical evidence exists once under `loop_evidence/`; links expose it from `project/`.
- Fail before mark-complete on any missing/changed evidence, broken link, unexpected root entry, schema failure, or reduced CI/harness coverage.
- No Docker, Valkey, host network, firewall, routing, `sudo`, or physical-host service operation belongs in this stage.
- Avoid destructive cleanup commands. Remove only ignored `.DS_Store`/cache directories that are demonstrably untracked; never remove a tracked path as “cleanup.”

## Resource considerations

- The dominant cost is moving and hashing about 679 MB across 17,555 tracked evidence files, plus Git index/rename processing. It requires disk headroom for Git operations and temporary digest/report files but no node runtime resources.
- Prefer same-filesystem moves so data is renamed rather than copied. Do not create a second 679 MB evidence copy.
- Hash deterministically in a streaming manner and process files in bytewise sorted logical-path order. Avoid loading file contents into memory; only the inventory records need memory or a streamed aggregate.
- Full non-real pytest may take substantial time but should remain within the manifest's 3,600-second limit. Compilation caches must go to `/tmp` and must not pollute the root allowlist.

## `待验证`

- Whether all tests in `--ignore=tests/real_valkey` are truly free of Docker/runtime prerequisites; collect and run them before changing the manifest command. If a non-real test legitimately needs Docker, document the exact reason rather than silently excluding broad test groups.
- Whether `codex_goal_loop_m1/` and `codex_goal_loop_m1_hardening_v2/` have any external consumer not visible in repository references. Repository tests are the acceptance check; do not leave duplicate compatibility links unless a concrete consumer requires one.
- Whether ignored cache directories can be removed within the current sandbox without approval; if not, report the root allowlist as blocked rather than allowing them.
- Whether the existing phase-summary schema accepts a storage-only stage with no cleanup/Valkey metrics. Use its existing explicit status/reason fields; do not weaken it.
- Whether `git` recognizes all content-preserving moves as renames is not an integrity criterion. Content baseline equality, not rename heuristics, is authoritative.

## Worker instructions

- Implement only this stage.
- Do not commit.
- Do not weaken harness or safety rules.
- Capture the immutable baseline before moving evidence, and never update that baseline merely to make verification pass.
- Preserve historical file contents and embedded logical paths exactly.
- Work from the repository root only for the physical migration; after moving, execute project commands from `project/`.
- Stop and report a blocker on any evidence hash mismatch instead of regenerating evidence or accepting a skip.
