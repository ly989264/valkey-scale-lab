# H00 Context Reload

stage_id: H00_BOOTSTRAP_HARD_GATES
agent_invocation: main_agent
source_commit_before: 5faa7e1a5b0aaa8c98111d3334613f04733e7387

## Reloaded Documents

- `codex_goal_loop_m1_hardening_v2/START_HERE.md`: H00 must not be skipped; executable fail-closed gates are required before later hardening.
- `codex_goal_loop_m1_hardening_v2/AGENTS_M1H_V2.md`: every stage requires real design, worker, and review subagents plus gate artifacts, commit, and push.
- `codex_goal_loop_m1_hardening_v2/docs/00_INDEX.md`: enumerates core docs, contracts, and H00-H10 stage order.
- `docs/01_PROBLEM_STATEMENT.md`: previous M1 PASS is suspect because fixtures, legacy-only evidence, weak non-empty checks, skipped telemetry, empty command logs, shallow benchmark rows, fake/PARTIAL timelines, and weak report input checks could pass.
- `docs/02_NON_NEGOTIABLE_CONTRACT.md`: stage completion is by executable gates, not prose; exact-scale gaps must become `BLOCKED_WITH_REASON`.
- `docs/03_EVIDENCE_TAXONOMY.md`: claims must classify as REAL_EXACT_SCALE, REAL_SMALL_SMOKE, reconstructed, legacy, fixture, dry-run, blocked, or invalid.
- `docs/04_HARD_GATE_ARCHITECTURE.md`: H00 must create the `scripts/m1h/` gate family and JSON gate-result artifacts.
- `docs/05_EVIDENCE_MANIFEST_AND_CLAIM_LEDGER.md`: `runs/m1-hardening/evidence_manifest.json` is generated and contains claim ledger entries.
- `docs/06_STAGE_PROTOCOL.md`: each stage reloads docs, writes context, launches real subagents, runs gates, and exits through `assert_stage_exit.py`.
- `docs/07_MULTI_AGENT_PROTOCOL.md`: agent artifacts must identify `agent_invocation: real_subagent`; simulated role artifacts are forbidden.
- `docs/08_CONTEXT_TRANSFER_PROTOCOL.md`: required handoff files are context persistence; gates are proof.
- `docs/09_NO_SHORTCUT_RULES.md`: static gates must reject fixture fallback, legacy promotion, weak count checks, fake timelines, and simulated subagents.
- `docs/10_ACCEPTANCE_MATRIX.md`: exact-scale M1 PASS requires setup 30/50/100/200, command audit 50/100/200 plus setup 30, management 50/100/200, workload 30/50/100/200, fault 50/100/200, system metrics 30/50/100/200, reports, and cleanup.
- `docs/11_REAL_SCALE_MATRIX.md`: no larger than 200 nodes is required; blocked exact-scale evidence must record reasons and rerun commands.
- `docs/12_REPORT_QUALITY_CONTRACT.md`: report rendering is not proof of source quality.
- `docs/13_BLOCKED_STATUS_POLICY.md`: blocked is acceptable only when explicit and cannot be promoted to PASS by fixtures, small runs, or legacy artifacts.
- `docs/14_GIT_PROTOCOL.md`: stage commits must start with stage id and push before the next stage.
- `docs/15_REVIEW_RUBRIC.md`: review must inspect diff, gates, gate artifacts, manifest, acceptance matrix, and shortcut scan.
- `docs/16_FAILURE_MODES.md`: known shortcuts include fixture-only work, schema-only additions, non-empty checks, small run promotion, and legacy evidence promotion.
- `docs/17_COMMANDS_AND_GATES.md`: common commands include compileall, unit/integration pytest, no-fixture, no-legacy, no-simulated, and stage-exit gates.
- `docs/18_STAGE_EXIT_CONTRACT.md`: stage exit must validate gate artifacts, review decision, forbidden shortcuts, completion references, evidence manifest, and commit/push records.
- `docs/19_FINAL_HANDOFF_CONTRACT.md`: H10 must distinguish hardening-loop status from milestone1 status.
- `contracts/C00-C12`: H00 gate family, manifest schemas, exact-scale claim ids, forbidden patterns, setup/command/workload/fault/system/report contracts, and no-simulated-subagent contract are mandatory.
- `stages/H00_BOOTSTRAP_HARD_GATES.md`: create gate framework, static scans, stage-exit checker, evidence manifest generation, tests, and H00 gate artifacts.

## Current Repository Evidence Notes

- `scripts/assert_milestone1_acceptance.py` currently falls back to `tests/fixtures` for management and workload checks and uses non-empty checks for several categories.
- `runs/m1-s09-local/artifacts/goal_loop/M1-S09/milestone1_acceptance_report.json` exists and must be treated as suspect until the new gates classify evidence.
- Existing real/legacy artifacts exist under `artifacts/phases/`, including P30-P36 exact-scale-looking directories, but H00 must not promote them without the new M1-format semantic gates.

## H00 Direction

Bootstrap `scripts/m1h/` with generated gate result JSON, generated evidence manifest, static shortcut scans, no simulated subagent scan, and stage-exit enforcement. The honest default for missing M1-format exact-scale claims is `BLOCKED_WITH_REASON`, not PASS.
