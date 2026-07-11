# Audit - P13O-04_FAST_TEST_SPLIT

Decision: PASS
Fresh Context: YES
Auditor: fresh-context-codex-reviewer
Audit Time: 2026-06-29T12:25:57Z

Gate Result: artifacts/gates/P13O-04_FAST_TEST_SPLIT/gate_result.json
Observed Gate Result SHA256: 27adfe0da878fca48574d25338920888a8c849f59960d2273e13dedd40910020

## Scope inspected

- `AGENTS.md`
- `CODEX_START_HERE.md`
- `docs/codex/02_PHASES.md`
- `docs/codex/04_AUDITOR.md`
- `docs/codex/05_P13_OPTIMIZATION_LOOP.md`
- `templates/audit/FRESH_CONTEXT_AUDIT_PROMPT.md`
- `templates/audit/AUDIT_TEMPLATE.md`
- `templates/audit/audit_decision.template.json`
- `codex/phase_manifest.json`
- `codex/p13_optimization_manifest.json`
- `codex/status/p13_optimization_state.json`
- `artifacts/harness_exception/P13O-04_FAST_TEST_SPLIT.md`
- gate result and stdout/stderr logs under `artifacts/gates/P13O-04_FAST_TEST_SPLIT/`
- required phase artifacts and schemas for P13O-04
- historical P13 gate result under `artifacts/gates/P13_SCALE_LADDER_50_100/`
- parent P13 real Valkey evidence summaries for scale_50 and scale_100
- relevant diffs in `codex/phase_manifest.json`, `codex/p13_optimization_manifest.json`, `pyproject.toml`, `scripts/p13_optimization_gate.py`, and `tests/unit/test_valkey_probe_lib.py`

## Gate findings

| Gate | Expected | Observed | Evidence |
|---|---:|---:|---|
| p13o_fast_test_lane | PASS | PASS | 57 passed, 3 deselected; stdout/stderr SHA256 matched gate_result.json |
| p13o_explicit_slow_perf_lane | PASS | PASS | 3 passed, 57 deselected; stdout/stderr SHA256 matched gate_result.json |
| p13o_fast_test_split_artifact_check | PASS | PASS | artifact validator reported PASS; stdout/stderr SHA256 matched gate_result.json |

The manifest SHA256 in `gate_result.json` matches the current `codex/p13_optimization_manifest.json` (`481ec15d7c1fc8f0155d43bbfde966f57005c56fe5f56fba757eb47fafc5e0c0`). All three P13O-04 manifest gates are present, required, passed with exit code 0, and have command text matching the manifest.

## Artifact findings

| Artifact | Schema | Observed | Evidence |
|---|---|---:|---|
| `artifacts/phases/P13O_FAST_TEST_SPLIT/p13_fast_test_split.json` | `schemas/artifact/p13_fast_test_split.schema.json` | valid | repository schema validator returned success |
| `artifacts/phases/P13O_FAST_TEST_SPLIT/phase_summary.json` | `schemas/artifact/p13_optimization_phase_summary.schema.json` | valid | repository schema validator returned success |
| `artifacts/gates/P13O-04_FAST_TEST_SPLIT/gate_result.json` | `schemas/artifact/p13_optimization_gate_result.schema.json` | valid | repository schema validator returned success |

The split artifact reports `status: PASS`, the historical P13 `scale_tests` source as `artifacts/gates/P13_SCALE_LADDER_50_100/gate_result.json`, and a historical duration of 90.232059 seconds. The new default P13 `scale_tests` command excludes `slow` and `perf`, while the explicit slow/perf lane collected and passed three marked tests.

## Safety findings

- Host network mutation: absent
- Global firewall mutation: absent
- Sudo default path: absent
- Cleanup logic: N/A for this no-runtime test-split phase
- Default node cap <= 100: verified

The inspected diffs add pytest marker definitions, mark existing probe-wait tests as `slow`, add the P13O-04 manifest gates/artifact validation, and update only the parent P13 `scale_tests` unit gate to exclude `slow` and `perf`. No deleted test files or deleted test cases were found in the git diff, and `git diff --diff-filter=D --name-only -- tests` returned no paths. The P13O manifest keeps `default_max_nodes: 100`, `p14_opt_in_only: true`, and P13O-04 `max_nodes: 0`.

## Real Valkey findings

Required for this phase: NO
Evidence file: N/A for P13O-04; parent P13 evidence checked for preservation
Valkey version observed: 9.1.0 in parent P13 scale_50 and scale_100 evidence
Independent live probe: N/A for P13O-04

P13O-04 does not require a real Valkey gate. The parent `P13_SCALE_LADDER_50_100` real gate commands in `codex/phase_manifest.json` still use `scripts/valkey_e2e_gate.py` for scale_50 and scale_100, and the P13O-04 artifact records those same wrapper commands as preserved. The existing parent evidence files report `real_valkey: true`, `status: PASS`, `probe_result: PASS`, `data_path_result: PASS`, and `valkey_versions: ["9.1.0"]`.

## Risks and follow-ups

| Risk | Severity | Required before next phase? | Notes |
|---|---|---:|---|
| `docs/codex/02_PHASES.md` documents the parent P13/P14 phases but not the P13O subphase loop. | low | no | `docs/codex/05_P13_OPTIMIZATION_LOOP.md` documents P13O-04 and the P13O execution rules; the P13O manifest provides the authoritative gates for this audit. |

## Final rationale

PASS. The P13O-04 manifest gates all ran and passed, command text matches the manifest, and each stdout/stderr log hash matches `gate_result.json`. Required artifacts exist and validate against their schemas. Real Valkey evidence is not required for this phase, and the parent P13 50/100-node real gate commands remain `scripts/valkey_e2e_gate.py` wrapper gates. The diff preserves tests by moving timeout-sensitive checks into an explicit slow lane, with no deleted tests and no host network, firewall, sudo, P14, or default >100-node behavior introduced.
