# 01_GOAL_CONTRACT.md — User Goal and Completion Contract

## Goal statement

Extend `valkey-scale-lab` so the project can run a strong-harness Codex App Goal-mode loop that completes the cluster-management operation matrix, the fault/failover matrix, and full quantitative collection.

The goal is not a planning-only change. Each stage must leave runnable code, schema-validated artifacts, passing gates, and a fresh-context review decision.

## Required capability coverage

### Management operation matrix

The project must implement and quantify these operations:

```text
create / meet / add replica / remove node / reshard / rebalance / rolling restart
```

The existing project already names the management phase, but this goal loop requires explicit coverage for:

- remove replica;
- remove primary through slot drain or controlled failover path;
- remove failed node after fault;
- reshard by explicit slot ranges;
- reshard with data-path verification;
- rebalance after uneven slot placement or node addition;
- rolling restart with health checks between nodes;
- workload impact during management operations.

### Fault and failover matrix

The project must implement and quantify:

- primary stop and promotion at 30, 50, 100, and 200 nodes;
- replica stop with no promotion expected;
- node-host stop;
- virtual AZ stop;
- network delay;
- network packet loss;
- network partition;
- network flap;
- minority partition;
- majority partition;
- split-brain indicator window;
- workload QPS, latency, and error changes during baseline, fault, recovery, and post-recovery windows.

### Quantitative evidence

Every management and fault stage must collect:

- operation/fault event timeline;
- real Valkey version and endpoint proof;
- node/slot topology before, during, and after;
- workload requested QPS, achieved QPS, latency percentiles, error counts, and timeout counts;
- management/failover timing metrics;
- cleanup results;
- machine-readable summary artifacts;
- report-ready tables/series derived only from artifacts.

## Completion definition

The loop is complete only when:

1. `codex/phase_manifest.json` contains stages P15-P26 with `automatic_stop_after` set to `P26_FINAL_REPORT_REGRESSION`.
2. All automatic stages through P26 pass precheck, run, postcheck, and mark-complete.
3. Each stage has design, worker, review, and completion Markdown artifacts under `artifacts/goal_loop/<STAGE_ID>/`.
4. Each stage has required JSON/JSONL artifacts under `artifacts/phases/<STAGE_ID>/` and all artifacts validate against schemas.
5. Fresh-context review says `Decision: PASS` for each stage.
6. Each stage is committed and pushed before the next stage starts.
7. P14 remains non-automatic and 1000-node execution remains disabled by default.

## Blocking conditions

A stage is blocked, not complete, when any of the following occurs:

- Docker is unavailable for a real-Valkey stage.
- Resource preflight fails for required scale gates.
- Required 200-node failover gate cannot run.
- A management operation is only simulated.
- A fault injection uses host-level network mutation.
- A metric is fabricated or silently omitted.
- Review returns `Decision: FAIL`.
- Cleanup leaves owned resources without failing the stage.

Blocked stages must write `artifacts/goal_loop/<STAGE_ID>/BLOCKED.md` using the blocked-stage template. Do not mark complete, commit, or push a blocked stage as passed.
