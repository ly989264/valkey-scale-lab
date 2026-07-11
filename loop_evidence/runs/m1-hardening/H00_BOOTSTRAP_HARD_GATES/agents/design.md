# H00 Design Subagent Artifact

role: design
agent_invocation: real_subagent
stage_id: H00_BOOTSTRAP_HARD_GATES
source_commit_before: 5faa7e1a5b0aaa8c98111d3334613f04733e7387

## Documents Read

- `codex_goal_loop_m1_hardening_v2/AGENTS_M1H_V2.md`
- `codex_goal_loop_m1_hardening_v2/docs/00_INDEX.md`
- `codex_goal_loop_m1_hardening_v2/docs/02_NON_NEGOTIABLE_CONTRACT.md`
- `codex_goal_loop_m1_hardening_v2/docs/03_EVIDENCE_TAXONOMY.md`
- `codex_goal_loop_m1_hardening_v2/docs/04_HARD_GATE_ARCHITECTURE.md`
- `codex_goal_loop_m1_hardening_v2/docs/09_NO_SHORTCUT_RULES.md`
- `codex_goal_loop_m1_hardening_v2/docs/10_ACCEPTANCE_MATRIX.md`
- `codex_goal_loop_m1_hardening_v2/contracts/C00_GATE_SCRIPT_MANIFEST.md`
- `codex_goal_loop_m1_hardening_v2/contracts/C01_EVIDENCE_MANIFEST_SCHEMA.md`
- `codex_goal_loop_m1_hardening_v2/contracts/C12_NO_SIMULATED_SUBAGENT_CONTRACT.md`
- `codex_goal_loop_m1_hardening_v2/stages/H00_BOOTSTRAP_HARD_GATES.md`
- Inspected current acceptance implementation and output: `scripts/assert_milestone1_acceptance.py`, `tests/ci/test_milestone1_acceptance_gate.py`, and `runs/m1-s09-local/artifacts/goal_loop/M1-S09/milestone1_acceptance_report.json`.

## Current Acceptance Assessment

The existing M1 acceptance gate is useful as a historical report producer but is too permissive for the hardening loop. It promotes several categories using shallow checks rather than the evidence taxonomy required by H00.

- `scripts/assert_milestone1_acceptance.py:77-86` accepts management data when matrix and command rows are present, and reads fixture paths when run artifacts are missing.
- `scripts/assert_milestone1_acceptance.py:89-95` accepts fault/failover data by event/report/sample presence only.
- `scripts/assert_milestone1_acceptance.py:98-106` accepts workload data by windows plus metrics presence and reads fixture paths when run artifacts are missing.
- `scripts/assert_milestone1_acceptance.py:144-161` reports cross-scenario fixture coverage as a PASS category.
- `scripts/assert_milestone1_acceptance.py:247-252` treats full-flow metric/report inputs as present when JSON/JSONL files parse, without source-quality checks.
- `runs/m1-s09-local/artifacts/goal_loop/M1-S09/milestone1_acceptance_report.json:20-52` records PASS reasons based on fixture coverage, row counts, and file presence. Lines 253-298 list fixture artifacts with status PASS.

The existing exact-scale artifacts under `artifacts/phases/P30_*`, `P33_*`, and `P36_*` contain promising real-run fields such as `real_valkey: true`, `nodes_observed`, Valkey 9.1.x versions, operation rows, and fault rows. H00 should not grant milestone PASS from them directly. It should first classify each source claim, validate required M1 semantic fields, and encode gaps as `BLOCKED_WITH_REASON` or `FAIL`.

## Design Direction

Create `scripts/m1h/` as a small fail-closed gate framework. Prefer a shared helper module for JSON/JSONL reads, gate-result writing, source commit lookup, artifact path normalization, and consistent status-to-exit-code mapping.

Every gate must write:

`runs/m1-hardening/<stage_id>/artifacts/gates/<gate_name>.json`

with the C00 fields: `schema_version`, `artifact_type`, `stage_id`, `gate_name`, `status`, `checked_at`, `inputs`, `violations`, `blocked_reasons`, and `source_commit`.

Implement all script names required by `C00_GATE_SCRIPT_MANIFEST.md` in H00, even if later capability gates initially return fail-closed status until their stage strengthens the semantics. H00 stage exit should require the H00 bootstrap gates to pass and should require the later gate scripts to exist, have tests, and produce C00-shaped results when invoked against controlled fixtures.

## Required Gate Behavior

1. `build_evidence_manifest.py`
   - Generate `runs/m1-hardening/evidence_manifest.json`.
   - Emit C01 top-level fields and claim rows.
   - Classify evidence as `REAL_EXACT_SCALE`, `REAL_SMALL_SMOKE`, `M1_FORMAT_RECONSTRUCTED_FROM_REAL_RAW`, `LEGACY_EVIDENCE_ONLY`, `FIXTURE_ONLY`, `DRY_RUN_ONLY`, `BLOCKED_WITH_REASON`, or `INVALID`.
   - Never hand-author claim results. Read candidate artifacts from known M1 run directories, `artifacts/phases`, and fixtures, then classify from path and content.
   - For required exact-scale claims, mark PASS only when the evidence kind is allowed by the taxonomy and semantic checks are explicitly true.

2. `assert_evidence_taxonomy.py`
   - Validate manifest shape against C01.
   - Require all claim statuses and evidence kinds to be recognized.
   - Reject missing source paths, empty source lists for non-blocked claims, and required claims that PASS with disallowed evidence kinds.
   - Require `semantic_checks` to include capability-specific booleans instead of generic file-presence booleans.

3. `assert_no_fixture_fallback.py`
   - Scan `scripts/assert_milestone1_acceptance.py` and `scripts/m1h/`.
   - Report file, line, and reason for PASS-path reads from `tests/fixtures` for required milestone claims.
   - Also inspect `runs/m1-hardening/evidence_manifest.json` and fail if a required claim has fixture evidence with PASS status.

4. `assert_no_legacy_m1_pass.py`
   - Read the evidence manifest and the current M1 acceptance report.
   - Fail if a required exact-scale claim is PASS while classified as legacy-only, dry-run-only, fixture-only, small-smoke, invalid, or blocked.
   - Fail if legacy artifacts are not clearly recorded with `required_for_milestone_pass: false`, unless an explicit reconstruction claim has complete semantic checks.

5. `assert_no_simulated_subagents.py`
   - Scan `runs/m1-hardening/<stage_id>/agents/` and `runs/m1-hardening/<stage_id>/handoff/`.
   - Require design, worker, and review artifacts when checking final stage exit; for the design step itself, allow only `design.md` to exist.
   - Require each present agent artifact to declare `role`, `agent_invocation: real_subagent`, `stage_id`, and `source_commit_before`.
   - Reject the forbidden C12 phrases with exact file and line reporting.

6. `assert_stage_exit.py`
   - Validate that all required H00 gate-result JSON files exist and match C00.
   - Require H00 common gates, `build_evidence_manifest.py`, no-fixture, no-legacy, no non-real-agent-artifact, and stage-exit checks to pass before H00 completion.
   - Require `runs/m1-hardening/H00_BOOTSTRAP_HARD_GATES/agents/{design,worker,review}.md`.
   - Require `runs/m1-hardening/H00_BOOTSTRAP_HARD_GATES/handoff/DESIGN_BRIEF.md`, `WORKER_SUMMARY.md`, and final review with `Decision: PASS`.
   - Do not require commit/push inside the script unless the repository already records stage completion metadata after review; instead, emit a clear violation if commit/push proof is missing when a completion artifact claims done.

7. Capability gates
   - `assert_setup_core_metrics.py`, `assert_command_audit_real.py`, `assert_management_exact_scale.py`, `assert_workload_benchmark_strength.py`, `assert_fault_timeline_real.py`, `assert_system_metrics_real_windows.py`, `assert_report_input_quality.py`, and `assert_final_milestone1_hardened.py` should all exist in H00.
   - Each should read the generated manifest plus capability artifacts and return PASS only for its own semantic contract. If required sources are unavailable or not yet hardened, return `BLOCKED_WITH_REASON` or `FAIL`, not PASS.

## Test Recommendations

Add focused tests under a new `tests/m1h/` area:

- Gate-result schema: every gate writes C00 JSON with source commit and consistent status/exit code.
- Evidence manifest schema: generated claims include required fields and reject malformed evidence kinds.
- Fixture rejection: a temp repo with fixture-backed required claims exits nonzero and reports line/path.
- Legacy rejection: a manifest with required legacy-only PASS exits nonzero.
- Agent artifact gate: valid real-subagent metadata passes; C12 forbidden phrases fail with file/line.
- Stage exit: fails when any H00 gate artifact, evidence manifest, worker summary, or review PASS is missing; passes in a temp stage directory with all required artifacts and PASS gate results.
- Existing acceptance regression: prove the current `scripts/assert_milestone1_acceptance.py` weaknesses are detected by the new H00 gates.

## Precise Executable Gate Sequence

Worker should implement and then run, in order:

```text
python3 -m compileall -q scripts src tests
python3 -m pytest -q tests/unit tests/integration tests/ci/test_milestone1_acceptance_gate.py tests/m1h
python3 scripts/m1h/build_evidence_manifest.py --out runs/m1-hardening/evidence_manifest.json
python3 scripts/m1h/assert_evidence_taxonomy.py --stage H00_BOOTSTRAP_HARD_GATES
python3 scripts/m1h/assert_no_fixture_fallback.py --stage H00_BOOTSTRAP_HARD_GATES
python3 scripts/m1h/assert_no_legacy_m1_pass.py --stage H00_BOOTSTRAP_HARD_GATES
python3 scripts/m1h/assert_no_simulated_subagents.py --stage H00_BOOTSTRAP_HARD_GATES
python3 scripts/m1h/assert_stage_exit.py --stage H00_BOOTSTRAP_HARD_GATES
```

Stage exit should be attempted only after the worker and review artifacts exist. Before that, it should fail closed with actionable violations.

## Risks

- The current acceptance report says PASS while recording fixture-backed and weakly checked categories. H00 must preserve that report as input evidence, not truth.
- Static scans can overmatch prose or tests. Scope scans to production gates by default, while still scanning stage artifacts for the C12 contract.
- Some existing real-looking artifacts were generated before this hardening package existed. They may be real operational evidence, but not automatically M1-format exact-scale evidence until semantic checks prove every required field.
- H00 can accidentally become a paper framework if later capability gates are empty wrappers. Require unit tests that exercise both passing and failing sample manifests for every new gate.
- Stage-exit checks that require review PASS too early can block worker iteration. Provide a mode or clear violation behavior that makes final exit strict without preventing intermediate gate development.

## Handoff

The worker should build the gate framework first, then make the current weak acceptance paths visibly fail under the new guard gates. Do not change milestone status in H00. The product of this stage is the hard gate scaffolding, generated evidence manifest, gate-result artifacts, and tests that prevent fixture, legacy, shallow-count, or non-real-agent shortcuts from being mistaken for milestone evidence.
