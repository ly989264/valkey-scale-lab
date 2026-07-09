role: worker
agent_invocation: real_subagent
stage_id: H04_COMMAND_AUDIT_REAL_PATH_HARDENING
source_commit_before: d5969a67ace6af2b0d085839db3e8b318c956973
source_commit_after: d5969a67ace6af2b0d085839db3e8b318c956973

## Scope

I operated as the H04 worker subagent with write ownership limited to:

- `runs/m1-hardening/H04_COMMAND_AUDIT_REAL_PATH_HARDENING/agents/worker.md`
- `runs/m1-hardening/H04_COMMAND_AUDIT_REAL_PATH_HARDENING/handoff/WORKER_SUMMARY.md`

I did not edit production code, tests, schemas, manifests, or gate artifacts. The main agent had active edits in `scripts/m1h/manifest.py`, `scripts/m1h/assert_command_audit_real.py`, `scripts/m1h/assert_stage_exit.py`, and `tests/m1h/test_gate_framework.py`; I read those edits and did not revert or overwrite them.

## Documents Read

- `codex_goal_loop_m1_hardening_v2/prompts/WORKER_SUBAGENT_PROMPT.md`
- `codex_goal_loop_m1_hardening_v2/AGENTS_M1H_V2.md`
- `codex_goal_loop_m1_hardening_v2/stages/H04_COMMAND_AUDIT_REAL_PATH_HARDENING.md`
- `codex_goal_loop_m1_hardening_v2/contracts/C07_COMMAND_AUDIT_CONTRACT.md`
- `runs/m1-hardening/H04_COMMAND_AUDIT_REAL_PATH_HARDENING/handoff/CONTEXT_RELOAD.md`
- `runs/m1-hardening/H04_COMMAND_AUDIT_REAL_PATH_HARDENING/handoff/DESIGN_BRIEF.md`
- Core hardening docs `00_INDEX`, `01`, `02`, `03`, `04`, `05`, `06`, `07`, `08`, `09`, `10`, `11`, `12`, `13`, `14`, `15`, `16`, `17`, `18`, and `19`
- Relevant contracts `C04_EXACT_SCALE_REQUIREMENTS.md` and `C12_NO_SIMULATED_SUBAGENT_CONTRACT.md`

Note: the user-specified path `contracts/C07_COMMAND_AUDIT_CONTRACT.md` was absent at repository root. The matching contract exists at `codex_goal_loop_m1_hardening_v2/contracts/C07_COMMAND_AUDIT_CONTRACT.md` and was read.

## Local Checks Run

- `PYTHONPYCACHEPREFIX=/private/tmp/valkey-scale-lab-pycache-h04-worker python3 -m compileall -q scripts src tests` -> PASS
- `PYTHONPYCACHEPREFIX=/private/tmp/valkey-scale-lab-pycache-h04-worker python3 -m pytest -q tests/m1h/test_gate_framework.py` -> PASS, 31 tests
- `PYTHONPYCACHEPREFIX=/private/tmp/valkey-scale-lab-pycache-h04-worker python3 -m pytest -q tests/m1h/test_gate_framework.py -k command_audit` -> PASS, 7 tests selected
- Direct read-only call to `evaluate_command_audit_real(runs/m1-hardening/evidence_manifest.json)` -> 0 violations, 3 blocked command audit claims, no passed command audit claims
- Direct read-only call to `validate_stage_exit(..., H04_COMMAND_AUDIT_REAL_PATH_HARDENING)` -> 0 violations, 7 blocked missing stage artifacts or gate results at the time checked
- Direct read-only scans for fixture fallback and H04 subagent artifacts -> 0 fixture fallback violations, 0 H04 subagent artifact violations at the time checked

## Observed H04 State

The current evidence manifest classifies all H04 command audit exact-scale claims as `BLOCKED_WITH_REASON`:

- `command_audit.real_exact.50` -> `LEGACY_EVIDENCE_ONLY`, blocked
- `command_audit.real_exact.100` -> `LEGACY_EVIDENCE_ONLY`, blocked
- `command_audit.real_exact.200` -> `LEGACY_EVIDENCE_ONLY`, blocked

The recorded C07 reasons include missing non-fixture `command_audit_summary.json`, missing required command kinds `cleanup`, `cluster_addslots`, `cluster_meet`, `cluster_probe`, `cluster_replicate`, and legacy fault command rows missing M1 command-log fields such as `argv`, `artifact_type`, `client_port`, `duration_ms`, `error_type`, `exit_code`, `global_firewall_mutated`, and `host_id`.

## C07 Risk Notes

The current main-agent implementation appears to prevent the most important false PASS class for existing repository evidence: legacy/fault command rows do not promote the 50/100/200 command audit claims to PASS.

Remaining C07 gaps were found with temporary `/private/tmp` probes that did not modify repository code:

- A command audit claim can PASS while cleanup rows contain required-field placeholders such as `node_logical_id: MISSING` and structured `client_port: MISSING`.
- A command audit claim can PASS even when an empty `management_command_log.jsonl` is present beside an otherwise valid `command_log.jsonl`.
- A command audit claim can PASS with non-empty `missing_or_skipped` in `command_audit_summary.json`.
- A command audit claim can PASS when command kind and argv disagree, such as `command_kind: cluster_meet` with `CLUSTER INFO`.
- A command audit claim can PASS when a failed command is not covered by `failed_commands`.
- A command audit claim can PASS when stdout/stderr files do not exist; the current check accepts path/hash presence and hash shape, not file resolution or hash matching.

These are worker-observed risks for the main agent and review agent to consider before H04 is accepted.
