# 00_MISSION.md — Project Mission and Product Contract

## 1. What must be built

Build `valkey-scale-lab`, a local-first Valkey 9.1.x ultra-scale cluster experiment harness. It must begin on a single Mac and scale to multiple Mac/Linux hosts. The default automatic development ceiling is 100 Valkey nodes; 1000-node behavior is an opt-in scale profile limited to planning, resource checks, dry-run, and controlled execution.

The project must be able to:

1. create Valkey clusters from declarative configuration;
2. place nodes across physical hosts and virtual AZs;
3. validate shard primary/replica AZ separation;
4. run management operation matrices;
5. run workload models before, during, and after failures;
6. inject sandboxed faults;
7. collect metrics, events, logs, and resource data;
8. analyze quantitative outcomes;
9. produce schema-validated machine-readable artifacts;
10. render tables, charts, and reports from artifacts only.

## 2. What must not be built

Do not build a host-level network chaos tool. Fault injection is scoped to Valkey-owned containers, namespaces, or owned sandbox proxy processes.

Do not build a benchmark whose correctness depends on charts or screenshots. Charts are presentation. Artifacts are the contract.

Do not build a fake-only simulator and call it complete. Fakes are allowed only in P00-P02 for design and planner development.

## 3. Output contract

A successful experiment run must produce at least:

```text
artifacts/runs/<run_id>/run_metadata.json
artifacts/runs/<run_id>/config_effective.json
artifacts/runs/<run_id>/cluster_plan.json
artifacts/runs/<run_id>/events.jsonl
artifacts/runs/<run_id>/metrics_timeseries.jsonl
artifacts/runs/<run_id>/management_ops_report.json
artifacts/runs/<run_id>/fault_report.json
artifacts/runs/<run_id>/workload_report.json
artifacts/runs/<run_id>/analysis_summary.json
artifacts/runs/<run_id>/report_index.json
```

If a field is not measurable in a run, the artifact must contain `MISSING` or `SKIPPED_WITH_REASON` with a reason and impact note.

## 4. Primary metric families

Cluster management metrics:

- cluster creation latency;
- node join/meet latency;
- slot assignment latency;
- slot convergence latency;
- rebalance/reshard duration;
- cluster config epoch changes;
- gossip convergence time;
- command latency for cluster management commands;
- failure rates and retry counts;
- control-plane CPU/memory overhead.

Management operation matrix:

- create cluster;
- add primary;
- add replica;
- remove replica;
- remove primary after migration;
- reshard fixed slot count;
- rebalance;
- failover manual/forced when available;
- rolling restart;
- config rewrite;
- scale out and scale in;
- AZ placement changes through planned recreation or migration.

Failover metrics:

- detection latency;
- promotion latency;
- write unavailability window;
- read unavailability window;
- slot coverage loss duration;
- cluster-state recovery duration;
- data-path error rate during fault;
- stale primary acceptance window where measurable;
- split-brain duration and affected slots;
- minority/majority availability behavior.

Stability metrics:

- steady-state latency percentiles;
- throughput achieved versus requested QPS;
- connection churn;
- memory growth and fragmentation indicators;
- event-loop latency indicators if available;
- slot-map drift;
- replica lag;
- unexpected restarts;
- cleanup completeness.

## 5. Artifact-first reporting

Reports must be generated from schemas under `schemas/`. A chart renderer may never fill in a missing metric. The renderer must display missing data as missing.

