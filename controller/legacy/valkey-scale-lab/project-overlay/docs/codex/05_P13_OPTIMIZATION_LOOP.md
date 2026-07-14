# P13 Optimization Loop

This document defines the post-P13 optimization loop. It is separate from the automatic P00-P13 build loop and must not advance `P14_SCALE_1000_OPTIN_DRYRUN`.

## Scope

The loop optimizes and explains P13 50/100-node real scale startup. It does not replace real Valkey evidence, topology evidence, data-path proof, role-count validation, full membership validation, or cleanup proof.

## Execution Rules

Only the next incomplete P13O phase may run. Each phase must:

1. read `codex/p13_optimization_manifest.json` and `codex/status/p13_optimization_state.json`;
2. implement only that phase;
3. run focused fast tests;
4. run the required P13 50/100 real Valkey gates when the phase requires real evidence;
5. write machine-readable artifacts;
6. write an audit under `audit/<PHASE_ID>/`;
7. pass `python3 scripts/p13_optimization_gate.py postcheck --phase <PHASE_ID>`;
8. run `python3 scripts/p13_optimization_gate.py mark-complete --phase <PHASE_ID>`;
9. commit and push before any later P13O phase starts.

If a protected harness file must be changed, write `artifacts/harness_exception/<PHASE_ID>.md` first and keep the patch limited to preserving or strengthening the harness requirement.

## Phases

### P13O-00_TIMING_ACCOUNTING

Strengthen P13 timing semantics without changing cluster startup. The P13 50/100 timing artifacts must include total gate wall time, setup command wall time, setup log write time, state load time, artifact write time, cleanup command wall time, unattributed seconds, and a split between final and diagnostic full probes.

Required artifacts:

- `artifacts/phases/P13_SCALE_LADDER_50_100/p13_timing_breakdown_scale_50.json`
- `artifacts/phases/P13_SCALE_LADDER_50_100/p13_timing_breakdown_scale_100.json`
- `artifacts/phases/P13O_TIMING_ACCOUNTING/phase_summary.json`

Pass criteria:

- P13 `scale_50` and `scale_100` real gates pass;
- `unattributed_seconds <= 10`, unless explicitly explained in the artifact;
- the timing artifact explains the real gate wall time;
- `runtime_final_full_probe` is not marked FAIL when the final proof passes;
- cluster startup algorithm is unchanged.

### P13O-01_CLUSTER_CREATE_AB

Compare safe cluster-create strategies while preserving topology evidence. The current `valkey_cli_cluster_create_primaries` strategy remains the default unless a new strategy is strictly proven safe.

### P13O-02_REPLICA_REPLICATE_BREAKDOWN

Break down replica replication timing, add bounded parallelism configuration, and emit slowest replica diagnostics while preserving role counts, full membership, data-path proof, and cleanup proof.

### P13O-03_CLEANUP_OPTIMIZATION

Reduce cleanup wall time while preserving cleanup evidence for owned containers, owned networks, and observable Valkey processes.

### P13O-04_FAST_TEST_SPLIT

Separate slow/perf tests from default P13 fast tests. Real Docker/Valkey proof continues to come from the wrapper gates.

### P13O-05_PERF_REGRESSION_BUDGET

Emit startup optimization comparisons and soft performance budgets, with optional strict failure through `VSLAB_STRICT_PERF_BUDGET=1`.

### P13O-06_PROCESS_RUNTIME_BOOTSTRAP_BATCHING

Batch process runtime bootstrap by nodehost while preserving P13 real evidence. Configs are generated locally per logical node, installed remotely once per nodehost as a bundle, data directories are created by the nodehost install script, Valkey processes may be started by a nodehost `start_all.sh`, and pidfiles are collected in bulk.

Required artifact:

- `artifacts/phases/P13O_PROCESS_BOOTSTRAP_BATCHING/p13_process_bootstrap_batching.json`

Pass criteria:

- P13 `scale_50` and `scale_100` real gates still pass with `--require-data-path`;
- role counts remain 25/25 and 50/50;
- final full-node proof remains present;
- cleanup reports for both rungs have `resources_remaining=[]`;
- artifact records config local generation, remote install, process start command, pidfile collection, docker exec before/after, and docker cp before/after;
- unit tests cover bundle generation and path safety;
- integration tests cover 10/30-node bootstrap without per-node docker cp/mkdir/start regression.

### P13O-07_SETUP_EXHAUSTIVE_TIMELINE

Emit an exhaustive setup subprocess timeline for P13 `scale_50` and `scale_100`. The timeline is a sequential leaf-segment list with explicit `gap` segments, and parent phases such as `process_config_prepare`, `process_start`, and `cluster_formation` are represented only as hierarchy aggregates with `inclusive_duration_seconds`, `exclusive_duration_seconds`, and `children`.

Required artifacts:

- `artifacts/phases/P13_SCALE_LADDER_50_100/setup_timeline_scale_50.json`
- `artifacts/phases/P13_SCALE_LADDER_50_100/setup_timeline_scale_100.json`
- `artifacts/phases/P13O_SETUP_EXHAUSTIVE_TIMELINE/p13_setup_exhaustive_timeline.json`
- `artifacts/phases/P13O_SETUP_EXHAUSTIVE_TIMELINE/phase_summary.json`

Pass criteria:

- P13 `scale_50` and `scale_100` real gates still pass with `--require-data-path`;
- each setup timeline has non-overlapping segments and no silent gap larger than validator tolerance;
- required setup stages are present, including config parse, port preflight, cleanup, network create, nodehost start, config bundle generation/copy/install, process start, readiness wait, cluster formation, state writes, runtime timing write, scale ladder write, and setup return;
- parent hierarchy durations do not double-count children;
- `setup_timeline_unexplained_seconds <= 2.0` for both 50-node and 100-node gates;
- cleanup reports for both rungs pass with no owned resources remaining;
- postcheck fails if the P13O aggregate artifact or source setup timeline artifacts are missing or stale.
