# 02_PHASES.md — Phase Plan and Gates

The authoritative machine-readable phase list is `codex/phase_manifest.json`. This document explains intent and judgment criteria. A phase is complete only when `scripts/codex_gate.py postcheck --phase <PHASE_ID>` passes.

## P00_REPO_CONTRACT — Repository contract and immutable harness bootstrap

Purpose: create the implementation skeleton without claiming runtime usability.

Must implement:

- Python package skeleton under `src/valkey_scale_lab/`;
- CLI entry point `python3 -m valkey_scale_lab.cli` with help output and explicit unimplemented errors;
- initial test layout;
- artifact directory conventions;
- CI workflow preserving harness checks;
- cleanup and run-state design document in code/docs.

Allowed: fake-only tests.

Not allowed: claiming Valkey clusters can run.

Pass criteria:

- harness lock passes;
- safety scan passes;
- unit tests run;
- required P00 artifacts exist and validate;
- fresh-context audit says `Decision: PASS` and cites gate result plus artifacts.

## P01_CONFIG_SCHEMA — Configuration schema and validation

Purpose: lock the user-facing configuration model.

Must implement:

- physical host config: host ID, OS, architecture/chip, memory, disk, IP, Docker endpoint, labels;
- virtual AZ config: single-AZ and multi-AZ modes, AZ count, host-to-AZ availability;
- Valkey cluster config: shards, replicas per shard, image/version, ports, directories, resource limits;
- workload config: read/write ratio, uniform and hotspot QPS, pipeline, keyspace, timing relative to fault;
- fault scenario config: node, AZ, network delay/loss/partition/flap, process stop/restart;
- safety config: max nodes default 100, 1000 opt-in, cleanup behavior, sandbox mode;
- config normalization output artifact.

Allowed: fake-only validation.

Pass criteria:

- positive and negative config tests pass;
- schema report and validation report artifacts exist;
- invalid configs fail for the right reasons;
- default config cannot exceed 100 nodes;
- 1000-node config requires explicit opt-in and dry-run mode.

## P02_PLANNER — Cluster planner and placement model

Purpose: turn config into an executable plan while enforcing placement and safety constraints.

Must implement:

- deterministic placement of primaries/replicas across AZs;
- host capacity checks;
- port allocation with collision detection;
- directory/PID/container naming plan;
- virtual AZ balancing;
- 1000-node dry-run planning without execution;
- machine-readable `cluster_plan.json`.

Allowed: fake-only planner tests.

Pass criteria:

- plan constraints script passes;
- 1-primary/1-replica shards never place both nodes in same AZ;
- single-AZ mode only allowed for no-replica or explicitly marked non-HA tests;
- 1000-node dry-run never starts processes or containers.

## P03_LOCAL_DOCKER_VALKEY — Local Docker runtime and real Valkey small cluster

Purpose: introduce real Valkey 9.1.x and prove the runtime can create and cleanup a small cluster.

Must implement:

- Docker runtime abstraction;
- one Valkey node per container with independent network identity;
- Valkey config generation;
- deterministic container labels and cleanup;
- cluster create/meet/add-slots baseline;
- state file consumed by pre-authored e2e wrapper;
- independent live endpoint probing through `scripts/valkey_e2e_gate.py`.

Allowed: fakes only as supplemental tests.

Pass criteria:

- real Valkey 9.1.x e2e evidence exists;
- independent probe observes live Valkey endpoints;
- cluster state is OK;
- cleanup report has no owned resources remaining;
- fake tests are not counted as real evidence.

## P04_CLUSTER_MANAGEMENT_OPS — Management operation matrix

Purpose: measure management-plane behavior under real Valkey small-cluster conditions.

Must implement:

- operation runner for create, meet, add replica, remove node, reshard, rebalance, rolling restart where supported;
- per-operation timing and status;
- convergence detection;
- operation matrix artifact;
- error taxonomy for unsupported, skipped, failed, and passed operations.

Pass criteria:

- at least one real Valkey e2e management scenario runs;
- operation report validates against schema;
- unsupported operations are `SKIPPED_WITH_REASON`, not PASS;
- cluster returns to a safe state before cleanup.

## P05_WORKLOAD_ENGINE — Workload model and data-path proof

Purpose: introduce workload generation and quantify behavior before/after control-plane operations.

Must implement:

- read/write workload model;
- uniform key distribution;
- hotspot model;
- pipeline size;
- requested versus achieved QPS;
- latency percentiles;
- workload timing windows: before fault, during fault, after recovery, all-run;
- data-path error classification.

Pass criteria:

- real Valkey e2e workload scenario runs;
- workload report includes requested QPS, achieved QPS, p50/p95/p99, errors, timeout counts;
- missing percentiles are marked missing with reason;
- independent probe verifies basic SET/GET path.

## P06_OBSERVABILITY_METRICS — Metrics, logs, events, and schema-first artifacts

Purpose: collect enough telemetry to make failures and management performance analyzable.

Must implement:

- Valkey `INFO` sampling;
- `CLUSTER INFO` and `CLUSTER NODES` sampling;
- Docker/process CPU and memory sampling where available;
- log capture;
- event timeline;
- artifact writer with JSON and JSONL schema validation;
- run metadata and effective config artifact.

Pass criteria:

- real Valkey e2e metrics scenario runs;
- `metrics_timeseries.jsonl` validates line-by-line;
- `events.jsonl` validates line-by-line;
- artifact writer never silently drops missing fields.

## P07_FAULT_INJECTION_SANDBOX — Sandboxed fault engine

Purpose: add fault injection without host network side effects.

Must implement:

- process/container stop fault;
- container-scoped network delay/loss/partition/flap when supported;
- sandbox proxy fallback for unsupported namespace features;
- virtual AZ fault targeting;
- fault apply/clear lifecycle;
- fault evidence artifact;
- static and runtime safety checks that reject host-level mutation.

Pass criteria:

- pre-authored `scripts/fault_safety_gate.py` validates sandbox behavior;
- no host-level network command appears in source without explicit sandbox allow marker;
- fault report records scope, target, start/end, expected impact, observed impact;
- cleanup clears all fault state.

## P08_FAILOVER_SPLIT_BRAIN — Failover, partition, and split-brain analysis

Purpose: quantify Valkey cluster recovery behavior under node and AZ faults.

Must implement:

- primary stop failover scenario;
- replica promotion detection;
- slot coverage recovery detection;
- write/read unavailability windows;
- minority/majority partition scenarios;
- split-brain indicators and duration metrics;
- failover report schema.

Pass criteria:

- `scripts/fault_failover_gate.py` independently stops a selected primary through the project fault API;
- a former replica becomes primary or the scenario is explicitly failed;
- failover report contains measured durations or `MISSING` with reason;
- split-brain metrics are not fabricated.

## P09_ANALYSIS_REPORTING — Quantitative analysis and presentation layer

Purpose: transform artifacts into stable quantitative outputs and visual reports.

Must implement:

- analysis summary artifact;
- baseline comparison artifact;
- report index artifact;
- CSV/table exports;
- charts from artifact data only;
- static HTML or markdown report;
- missing metric rendering.

Pass criteria:

- report generation consumes real artifacts from prior e2e phases;
- report index validates;
- charts are regenerated deterministically enough for regression checks;
- analysis never invents metrics.

## P10_MULTI_HOST_ORCHESTRATION — Multi-Mac/Linux orchestration

Purpose: extend from single controller/single Docker host to multiple configured hosts.

Must implement:

- host inventory validation;
- SSH/remote-agent abstraction;
- remote prepare/start/stop/collect operations;
- host-aware placement;
- local loopback multi-host fake integration;
- at least one real Valkey local-orchestrated e2e scenario through the same orchestration layer.

Pass criteria:

- orchestrator can run the same lifecycle contract locally;
- remote cleanup is idempotent;
- artifact collection preserves host identity;
- no root/sudo requirement is introduced.

## P11_STABILITY_SOAK — Stability and soak profile

Purpose: prove that the system can run a bounded steady-state experiment and summarize stability signals.

Must implement:

- bounded soak profile;
- periodic metrics collection;
- workload under steady state;
- restart/leak/error summary;
- artifact regression baseline support.

Pass criteria:

- real Valkey e2e soak scenario runs within configured bounds;
- stability report validates;
- cleanup is verified;
- baseline comparison exists even when no previous baseline is available.

## P12_SCALE_LADDER_10_30 — Real scale ladder: 10 and 30 nodes

Purpose: prove that scaling behavior is real, not hypothetical, up to 30 nodes.

Must implement:

- resource preflight;
- real 10-node cluster gate;
- real 30-node cluster gate;
- metrics and management summaries for each rung;
- rung comparison artifact.

Pass criteria:

- 10-node real Valkey gate passes;
- 30-node real Valkey gate passes;
- each rung has independent e2e evidence;
- failures due to resource insufficiency are FAIL for this phase, not PASS.

## P13_SCALE_LADDER_50_100 — Real scale ladder: 50 and 100 nodes

Purpose: complete the default scale ceiling.

Must implement:

- real 50-node gate;
- real 100-node gate;
- resource and cleanup protections;
- scale comparison analysis;
- artifact baseline snapshots.

Pass criteria:

- 50-node real Valkey gate passes;
- 100-node real Valkey gate passes;
- no default path exceeds 100 nodes;
- owned resources are cleaned or explicitly reported as remaining, causing failure.

## P14_SCALE_1000_OPTIN_DRYRUN — Optional 1000-node dry-run and resource check

Purpose: provide opt-in planning for 1000 nodes without making it part of the normal Codex loop.

Must implement:

- 1000-node planner dry-run;
- resource requirement estimate;
- scheduling plan across hosts;
- refusal to execute unless explicitly enabled;
- controlled execution hooks that default to disabled.

Pass criteria:

- this phase is not automatic;
- dry-run artifacts validate;
- no containers/processes are started by default;
- opt-in environment variable is required.

