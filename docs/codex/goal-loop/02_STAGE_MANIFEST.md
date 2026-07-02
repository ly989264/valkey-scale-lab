# 02_STAGE_MANIFEST.md — Goal Loop Stages P15-P26

The existing repository uses phases P00-P14. This goal loop adds stages P15-P26. These stages must be appended to `codex/phase_manifest.json`. `P14_SCALE_1000_OPTIN_DRYRUN` remains non-automatic.

## Stage list

| Stage ID | Title | Real Valkey required | Max nodes | Purpose |
|---|---:|---:|---:|---|
| P15_GOAL_REBASE_HARNESS_EXTENSION | Goal-loop harness extension | No | 0 | Add stages, schemas, gate assertions, and docs without claiming runtime behavior. |
| P16_QUANT_TELEMETRY_UNIFICATION | Unified quantitative telemetry | Yes | 6 | Implement canonical events, metrics, workload windows, and missing-data policy. |
| P17_MANAGEMENT_REMOVE_NODE | Management matrix: remove node | Yes | 10 | Implement remove replica, remove primary via drain/failover path, failed-node removal, and metrics. |
| P18_MANAGEMENT_RESHARD_REBALANCE | Management matrix: reshard and rebalance | Yes | 10 | Implement slot movement, data verification, rebalance, convergence timing, and workload impact. |
| P19_MANAGEMENT_ROLLING_RESTART | Management matrix: rolling restart | Yes | 10 | Restart nodes sequentially with health gates, workload measurement, and cleanup. |
| P20_FAILOVER_LATENCY_CURVE_30_50_100 | Failover latency curve: 30/50/100 | Yes | 100 | Run primary-stop promotion samples and produce a curve for 30, 50, and 100 nodes. |
| P21_FAILOVER_LATENCY_CURVE_200 | Failover latency curve: 200 | Yes | 200 | Run resource-gated 200-node primary-stop promotion samples. |
| P22_FAULT_REPLICA_HOST_AZ_STOP | Replica, node-host, and AZ stop faults | Yes | 100 | Implement replica stop, logical host stop, and virtual AZ stop faults with metrics. |
| P23_FAULT_NETWORK_DELAY_LOSS_FLAP | Network delay, loss, and flap faults | Yes | 100 | Implement sandboxed delay/loss/flap faults and workload impact measurement. |
| P24_PARTITION_SPLIT_BRAIN_MATRIX | Partition and split-brain matrix | Yes | 100 | Implement minority/majority partitions and split-brain-window measurement. |
| P25_FAULT_WORKLOAD_IMPACT_ANALYSIS | Fault-period workload impact analysis | Yes | 100 | Consolidate QPS/latency/error deltas across management and fault stages. |
| P26_FINAL_REPORT_REGRESSION | Final report and regression hardening | Yes | 100 | Generate final tables, curves, reports, regression baselines, and CI checks. |

## Required manifest changes

P15 must update `codex/phase_manifest.json` as follows:

```text
version: keep existing version unless a migration is needed
automatic_stop_after: P26_FINAL_REPORT_REGRESSION
P14_SCALE_1000_OPTIN_DRYRUN: automatic=false, unchanged opt-in guard
append P15-P26 entries in the order listed above
```

Each new phase entry must include:

- `id`, `title`, `automatic`, `fake_only_allowed`, `real_valkey_required`, `max_nodes`, `objectives`;
- gates for `harness_precheck`, `safety_static_scan`, unit/integration tests, schema validation, real Valkey e2e where required, goal-loop coverage assertions, cleanup assertion;
- required artifacts with schema paths;
- audit paths under `audit/<STAGE_ID>/`.

## Common gates required for every new stage

Every P15-P26 stage must have these gates or stricter equivalents:

```text
python3 scripts/codex_gate.py precheck --phase <STAGE_ID>
python3 scripts/safety_scan.py
python3 -m compileall -q scripts src
python3 -m pytest -q tests/unit tests/integration
python3 scripts/assert_goal_loop_stage.py --phase <STAGE_ID>
python3 scripts/codex_gate.py run --phase <STAGE_ID>
python3 scripts/codex_gate.py postcheck --phase <STAGE_ID>
```

Stages requiring real Valkey must include a real wrapper gate with independent probing.

## Required common artifacts

Every new stage must produce:

```text
artifacts/phases/<STAGE_ID>/phase_summary.json
artifacts/phases/<STAGE_ID>/valkey_e2e_evidence.json          # real stages only
artifacts/phases/<STAGE_ID>/cleanup_report.json              # real stages only
artifacts/phases/<STAGE_ID>/events.jsonl                     # real stages only
artifacts/phases/<STAGE_ID>/metrics_timeseries.jsonl          # real stages only
artifacts/phases/<STAGE_ID>/quant_summary.json
artifacts/goal_loop/<STAGE_ID>/CONTEXT_RELOAD.md
artifacts/goal_loop/<STAGE_ID>/DESIGN_BRIEF.md
artifacts/goal_loop/<STAGE_ID>/WORKER_SUMMARY.md
artifacts/goal_loop/<STAGE_ID>/REVIEW.md
artifacts/goal_loop/<STAGE_ID>/COMPLETION.md
```

P15 may use fake-only tests because it is harness/scaffolding. P16-P26 must include real Valkey evidence unless blocked by a failing gate, in which case they must not be marked complete.

## Stage dependency chain

```text
P15 harness extension
  -> P16 quant telemetry foundation
    -> P17 remove node
      -> P18 reshard/rebalance
        -> P19 rolling restart
          -> P20 failover curve 30/50/100
            -> P21 failover curve 200
              -> P22 replica/host/AZ stop
                -> P23 delay/loss/flap
                  -> P24 partition/split-brain
                    -> P25 workload impact analysis
                      -> P26 final report/regression
```

Do not reorder the stages unless a stage document explicitly states a stronger prerequisite.
