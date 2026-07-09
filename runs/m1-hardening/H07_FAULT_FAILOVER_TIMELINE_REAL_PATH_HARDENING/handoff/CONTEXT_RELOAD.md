# H07 Context Reload

stage_id: H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING
source_commit_before: 3c2579c123bf498b2a8d1ea16a6eb8e31647a720

## Documents Reloaded

- `codex_goal_loop_m1_hardening_v2/START_HERE.md`: stage completion requires executable fail-closed gates, not Markdown completion notes.
- `codex_goal_loop_m1_hardening_v2/AGENTS_M1H_V2.md`: H07 must launch real design, worker, and review subagents and may complete only after gates, artifacts, review PASS, commit, and push.
- `codex_goal_loop_m1_hardening_v2/docs/00_INDEX.md`: confirms the hardening docs, contracts, and stage order.
- `docs/02_NON_NEGOTIABLE_CONTRACT.md`: exact-scale missing evidence must be `BLOCKED_WITH_REASON`; fixtures, legacy-only evidence, skipped core metrics, fake/PARTIAL artifacts, and non-empty checks cannot satisfy PASS.
- `docs/03_EVIDENCE_TAXONOMY.md`: only hardening-accepted real exact-scale evidence can promote a claim; fixture, dry-run, legacy, and small-smoke evidence cannot satisfy milestone exact-scale claims.
- `docs/04_HARD_GATE_ARCHITECTURE.md`: H07 must use `scripts/m1h/assert_fault_timeline_real.py` and write gate JSON under `runs/m1-hardening/H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING/artifacts/gates/`.
- `docs/09_NO_SHORTCUT_RULES.md`: H07 must not rely on fixture fallback, old real evidence, non-empty files, or shortcut status checks.
- `docs/10_ACCEPTANCE_MATRIX.md`: fault/failover timeline requires exact-scale 50, 100, and 200-node claims plus small-smoke coverage outside the exact-scale milestone claims.
- `docs/11_REAL_SCALE_MATRIX.md`: exact scale remains bounded at 30/50/100/200; if the current environment cannot produce a real fault timeline, the claim must be blocked with rerun guidance.
- `docs/13_BLOCKED_STATUS_POLICY.md`: blocked fault claims need precise reasons, missing artifacts, missing fields, and rerun command hints.
- `docs/15_REVIEW_RUBRIC.md`: review must inspect diff, gate scripts, gate artifacts, evidence manifest, fake/PARTIAL protection, and handoff sufficiency.
- `docs/17_COMMANDS_AND_GATES.md`: H07 must run common gates plus the stage-specific fault timeline gate.
- `docs/18_STAGE_EXIT_CONTRACT.md`: `assert_stage_exit.py` must verify H07 gate result JSON, review PASS, and shortcut scan before commit.
- `codex_goal_loop_m1_hardening_v2/stages/H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING.md`: H07 requires real, non-fake, non-PARTIAL fault/failover timeline claims and executable gates.

## Contracts Reloaded

- `C08_WORKLOAD_BENCHMARK_CONTRACT.md`: H07 workload-impact refs should not treat weak workload windows as benchmark proof; H06 now blocks incomplete workload evidence.
- `C09_FAULT_TIMELINE_CONTRACT.md`: real fault timeline PASS requires required lifecycle events, numeric latency/window metrics, `real_valkey: true`, execution mode not fake, status PASS not PARTIAL, workload and cleanup source refs, and clean cluster evidence.
- `C12_NO_SIMULATED_SUBAGENT_CONTRACT.md`: H07 agent and handoff artifacts must avoid forbidden shortcut phrases.

## Previous Stage Reload

- H06 completion: workload exact-scale claims now fail closed and current repository workload claims remain blocked because C08 evidence is incomplete.
- H06 review: `Decision: PASS`.
- H06 gate artifact: `assert_workload_benchmark_strength.json` reports PASS for the H06 gate while workload claims remain `BLOCKED_WITH_REASON`.
- H06 next-stage input: H07 must enforce coherent exact-scale fault/failover bundles with real event timelines, latency samples, workload refs, cleanup refs, and Valkey 9.1.x evidence.

## Current Repository State

- Current branch is `codex/valkey-scale-lab-loop` at `3c2579c123bf498b2a8d1ea16a6eb8e31647a720`.
- `scripts/m1h/assert_fault_timeline_real.py` is currently only the generic capability wrapper.
- `scripts/m1h/manifest.py` currently gives fault timeline weak checks: `exact_scale_observed`, any fault-named file, a JSONL row or sequence, and a path-based fake/PARTIAL check.
- Existing exact-scale fault phase dirs currently include fault command logs but do not provide a complete C09 `fault_timeline_report.json`, `fault_timeline_events.jsonl`, and `failover_latency_samples.jsonl` bundle for 50/100/200.
- P20 has failover latency samples for 30/50/100, but it is not a complete C09 exact-scale timeline bundle and is not sufficient for H07 PASS.

## H07 Starting Risk

The unacceptable state is a fault/failover claim promoting because a fault file exists, because a fake/PARTIAL timeline is non-empty, or because legacy latency samples exist without required event, workload, cleanup, clean-cluster, and exact-scale Valkey evidence. H07 must make those paths impossible through manifest semantics, a dedicated gate, tests, real subagent artifacts, and `assert_stage_exit`.
