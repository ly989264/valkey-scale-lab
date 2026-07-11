# 05_FAIL_CLOSED_HARNESS_CONTRACT.md — Strict Fail-Closed Harness Contract

## Purpose

The harness must prevent false completion. A stage cannot pass because code compiles, because a JSON file exists, or because a subagent says it passed. It passes only when independent checks verify exact stage coverage, artifact validity, real execution where required, cleanup, and review.

## P27 harness responsibilities

P27 must update or add harness support for P27-P40:

```text
manifest entries and automatic_stop_after=P40_STRICT_FINAL_AUDIT_CLOSEOUT
strict stage discovery after P26 completion
review checks for artifacts/goal_loop_strict/<STAGE_ID>/REVIEW.md
common Markdown handoff checks
strict audit checks
coverage registry validation
exact-scale node-count assertion
real Valkey provenance assertion
no-runtime-created assertion for >200 dry-run
visual report quality assertion
anti-bypass assertion
```

If changing a locked harness file is necessary, P27 must document why, update the lock transparently, and prove the lock still detects unauthorized changes.

## Required assertion script families

P27-P40 must create or strengthen scripts equivalent to:

```text
scripts/assert_strict_stage_contract.py
scripts/assert_no_bypass.py
scripts/assert_coverage_registry.py
scripts/assert_exact_scale_real_evidence.py
scripts/assert_quant_completeness.py
scripts/assert_management_matrix_strict.py
scripts/assert_fault_matrix_strict.py
scripts/assert_full_flow_e2e.py
scripts/assert_200_plus_dry_run.py
scripts/assert_analysis_provenance.py
scripts/assert_report_quality.py
scripts/assert_final_strict_closeout.py
```

A script may be named differently only if manifest, docs, tests, and review agree. Every assertion must fail closed.

## Fail-closed behavior

These conditions must return non-zero:

```text
missing file
malformed JSON or JSONL
empty required JSONL
missing required field
null used for missing data
zero used as missing data
node_count different from required exact scale
real_valkey=false for real stage
probe_result not PASS for real stage
sample set smaller than required
coverage row absent
coverage row PASS without source evidence
required row SKIPPED_WITH_REASON in real scale
cleanup not PASS
review missing or not Decision: PASS
report asset missing
report contains NaN, undefined, Traceback, placeholder, or broken chart
```

## Anti-bypass scan

`assert_no_bypass.py` must detect and fail on:

```text
manual PASS writes into gate_result.json
manual edits to codex/status/phase_state.json outside mark-complete behavior
commands that echo/printf PASS as a substitute for checks
new fake-only gates for real stages
host-level firewall/routing/interface mutation
sudo network commands
real execution above 200 nodes
node-count downshift for 200-node stages
placeholder reports that look successful
```

Allow test fixtures only through explicit allowlists maintained in test files, not by weakening the production scan.

## Exact-scale real-evidence gate

For real 50/100/200 stages, exact-scale evidence must verify:

```text
nodes_requested == required_node_count
nodes_observed == required_node_count
cluster_state reached expected target
live endpoints responded
Valkey versions start with 9.1.
workload performed real operations
source state file exists
cleanup report PASS
```

## Coverage registry gate

Every required coverage row must have:

```text
coverage_id
stage_id
scale
category
scenario_or_operation
required=true
execution_mode=real or dry_run
status
source_artifacts[]
validation_artifacts[]
metrics_refs[]
cleanup_ref
review_ref
```

For real 50/100/200 rows, `status=PASS` requires at least one real source artifact and an assertion result. For >200 rows, `status=PASS` requires `execution_mode=dry_run` and a no-runtime-created proof.

## Postcheck extension

`codex_gate.py postcheck` or equivalent strict postcheck must verify:

```text
gate_result status PASS
all manifest gates match gate_result commands
all required artifacts validate
strict review cites gate_result path and sha256
strict review cites every required artifact
strict audit_decision has fresh_context=true
strict stage journal was updated
```

Do not let any stage close based on partial or stale gate results.
