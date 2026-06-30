# L01_EXISTING_ARTIFACT_AUDIT_HARD_GATE Stage Design

## Stage Scope

L01 builds a committed artifact audit hard gate. It audits committed machine-readable evidence for P00-P13 and records P14 as an opt-in dry-run boundary. It must not run P14, mutate historical gate results, or count dry-run planner/resource artifacts as real Valkey evidence.

## Required Harness

1. `schemas/artifact/audit_report.schema.json`
2. `scripts/audit_committed_artifacts.py`
3. `tests/audit/test_committed_artifact_audit.py`
4. `tests/ci/test_committed_artifact_audit_gate.py`

L01 also includes a narrow L00 validator repair documented in `harness_change_request.md`: active in-progress stages must validate before `current_harness_plan.json` exists, while completed PASS stage validation remains strict.

## Audit CLI Behavior

The CLI must:

- read `codex/phase_manifest.json`;
- include every automatic phase P00 through P13;
- include P14 only as an optional dry-run boundary record;
- validate manifest-declared required artifacts for existence, non-empty content, parseability, schema validity, metadata, status, and SHA256;
- validate JSONL artifacts line-by-line through existing schema validation semantics;
- validate gate results for schema, gate status, exit code, log paths, log hashes, and command drift;
- classify the P13 `scale_tests` command mismatch as an explicit historical finding when real evidence, required artifacts, logs, and statuses otherwise validate;
- classify stale gate-result manifest hashes as historical only through the exact legacy SHA allowlist recorded in `scripts/audit_committed_artifacts.py`; any non-allowlisted manifest hash mismatch is blocking;
- validate real evidence for `real_valkey_required` phases and record observed node counts/version/data-path status;
- validate structured audit decision files for P00-P13;
- emit a schema-valid report to `artifacts/loop_engineering/reports/audit_report.json`;
- return nonzero if blocking findings exist.

## Finding Semantics

Findings must include:

- `id`
- `severity`
- `category`
- `classification`
- `blocking`
- `phase_id`
- `path`
- `description`
- `evidence`

Historical findings are allowed only for explicitly classified drift that does not invalidate current required evidence. The legacy gate manifest SHA allowlist is narrow: it matches the committed gate-result SHA that predates later manifest revisions and records a rationale in every finding. Missing required artifacts, empty artifacts, invalid JSON/JSONL, schema failures, missing required metadata, failed gates, missing logs, checksum mismatches, unallowlisted manifest hash mismatches, invalid real evidence, and P14 automatic/real-evidence claims are blocking.

## P13 Requirement

P13 must remain in the audit scope. The committed P13 gate result has historical drift:

- stale `manifest_sha256`;
- `scale_tests` command differs from the current manifest selector.

The audit report must include P13, record those drift items as nonblocking historical findings, and still validate the 50-node and 100-node real Valkey evidence artifacts. The stale manifest hash is nonblocking only when it matches the same exact legacy SHA allowlist used for the other committed historical gate results.

## P14 Requirement

P14 must not run. The report must show:

- `automatic=false`
- `opt_in_required=true`
- `dry_run_only=true`
- `not_required_for_automatic_completion=true`
- `real_valkey_coverage=false`
- `real_evidence_count=0`

Existing 1000-node dry-run planner artifacts, such as the P02 planner dry-run plan, must not count as P14 completion or real Valkey evidence.

## Tests

L01 tests must cover:

- committed repo report generation and schema validation;
- P00-P13 phase coverage;
- P13 inclusion and historical mismatch classification;
- P14 dry-run boundary classification;
- empty JSON, empty JSONL, invalid JSON, missing schema, missing producer, missing run_id, missing status, missing required artifact, unallowlisted stale manifest hash, missing observed Valkey version data, and invalid real evidence fixture failures;
- CI coverage and no P14/real-gate execution from the audit gate;
- no weakening of `tests/ci/test_postcheck_compatibility.py`.

## Acceptance Criteria

- Previous harness remains PASS.
- L01 audit CLI, schema, and tests exist and pass.
- `python3 scripts/audit_committed_artifacts.py --out artifacts/loop_engineering/reports/audit_report.json` passes for the current repository with no blocking findings.
- The audit report validates against `schemas/artifact/audit_report.schema.json`.
- P13 is included and has nonblocking historical mismatch findings.
- P14 is represented only as opt-in dry-run/not-run boundary.
- No P14 execution occurs.
- Historical artifacts are not edited to hide findings.
