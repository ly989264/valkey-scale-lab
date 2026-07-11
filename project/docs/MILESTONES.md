# Valkey Scale Lab Milestones

This document defines the product-level delivery milestones for
`valkey-scale-lab`. The existing phase and goal-loop stage IDs are implementation
steps beneath these milestones; completion of an internal stage does not by
itself mean that a milestone has passed.

## Guiding Principle

The three milestones separate three different kinds of risk:

1. prove the full experiment lifecycle and diagnostic value on one local host;
2. change the execution topology to multiple ECS instances without changing the
   experiment contract;
3. scale the proven multi-ECS system while preserving evidence quality and
   operational safety.

The core lifecycle is the same in every milestone:

```text
preflight -> provision/start -> form cluster -> stabilize -> baseline workload
-> management/fault action -> observe failover/recovery -> cleanup
-> validate artifacts -> analyze -> render report
```

Every lifecycle step must have timestamps, status, error context, resource and
Valkey metrics, and enough sub-step detail to locate a bottleneck. A single
top-level duration is not sufficient evidence.

## Milestone 1: Complete Local Cluster Lifecycle (up to 200 real nodes)

### Objective

Deliver a reliable local Mac/Linux execution path for real Valkey clusters up
to 200 nodes. Complete the functional and observability foundations before
introducing distributed-host complexity.

### Scope

- deterministic cluster startup, topology formation, readiness, stabilization,
  workload execution, and cleanup;
- management operations such as add/remove node, reshard, rebalance, and rolling
  restart;
- stability and bounded soak execution with explicit convergence and health
  criteria;
- sandboxed fault injection for process, node-host, AZ placement, network delay,
  loss, partition, flap, and minority/majority scenarios where the local runtime
  can safely model them;
- failover and recovery measurement, including client-visible availability,
  workload impact, cluster convergence, and split-brain windows;
- an exact-node trigger interface for any requested scale from 30 through 2000,
  with resource preflight allowed to block but never silently downscale a run;
- required real acceptance gates at 50 and a resource-preflight-gated 200 nodes;
- retained but non-required execution support at 30 and 100 nodes;
- non-automatic real execution above 200 only after explicit operator opt-in,
  resource preflight, and cost acknowledgement;
- offline analysis and clear visual reports generated only from validated,
  versioned artifacts.

### Diagnostic telemetry requirement

Instrumentation must cover both lifecycle stages and their meaningful
sub-stages. At minimum, reports must be able to separate:

- resource preflight and allocation;
- image/binary readiness and runtime creation;
- process/container start;
- node reachability and Valkey readiness;
- cluster meet/topology propagation;
- slot assignment and replica attachment;
- convergence and stabilization;
- workload warm-up, steady state, fault/operation window, recovery, and cooldown;
- fault apply, detection, election/promotion, routing recovery, data-path
  recovery, and fault clear;
- artifact flush, collection, validation, analysis, report rendering, and
  cleanup.

Each sub-stage must carry stable identifiers and monotonic timing. Relevant
CPU, memory, disk, network, process, Valkey, workload, command, retry, timeout,
and error telemetry must be correlated by run, host, node, scenario, and time
window. Missing data must be explicit rather than silently omitted or inferred.

### Exit criteria

Milestone 1 is complete only when:

- the full lifecycle passes the exact 50-node and exact 200-node real gates,
  with 200 guarded by resource preflight; 30 and 100 remain supported but are
  not milestone completion gates;
- required management, stability, fault, and failover scenarios have real
  evidence; an unresolved platform limitation keeps the milestone blocked unless
  the product scope is explicitly revised;
- repeated runs have deterministic ownership and cleanup with no residual owned
  processes, containers, networks, ports, or state;
- a slow or failed run can be localized to a lifecycle sub-stage from recorded
  evidence, not by manually reconstructing logs;
- schema and provenance validation reject incomplete, fixture-derived, stale, or
  fabricated real evidence;
- the final offline report clearly shows topology, stage timing, bottlenecks,
  resource saturation, workload impact, failover/recovery timing, errors,
  missing evidence, and comparisons across scale rungs.

## Milestone 2: Native Multi-ECS Execution (up to 200 real nodes)

### Objective

Move the complete Milestone 1 lifecycle to multiple ECS instances while running
Valkey as directly managed host processes rather than Docker containers. The
topology changes; scenario semantics, artifacts, analysis, and reports remain
compatible.

### Scope

- inventory and placement across multiple owned ECS instances and virtual AZs;
- remote distribution of Valkey binaries, configuration, run directories, and
  process ownership metadata;
- direct start, stop, health check, log collection, and cleanup of Valkey
  processes on each ECS instance;
- multi-host orchestration for every Milestone 1 lifecycle stage, management
  operation, stability run, fault scenario, failover measurement, and metric
  collector;
- centralized run control with per-host execution journals and restart-safe,
  idempotent commands;
- host and clock identity in every event, with clock-offset measurement so that
  cross-host failover timelines remain defensible;
- collection, validation, analysis, and reporting over distributed artifacts;
- real multi-ECS scale rungs up to 200 Valkey nodes.

### Runtime and safety boundary

Removing Docker must not remove isolation or cleanup guarantees. The runtime
must manage only processes, files, ports, and ECS instances explicitly owned by
the run. Network faults must use an approved run-scoped mechanism such as a
userspace proxy or isolated namespace; host-global firewall, route, or interface
mutation is not an acceptable default. ECS stop/reboot faults must target only
tagged experiment instances and require explicit authorization.

### Exit criteria

Milestone 2 is complete only when:

- a runtime-agnostic scenario definition can execute locally or on ECS without
  duplicating scenario logic;
- direct-process lifecycle and cleanup are idempotent across partial controller,
  SSH/session, host, and process failures;
- the Milestone 1 acceptance matrix passes on representative multi-ECS layouts,
  including cross-host and cross-AZ placement, through 200 real nodes;
- distributed telemetry is complete enough to distinguish controller delay,
  remote-command delay, host resource pressure, network effects, Valkey work,
  and artifact-transfer time;
- the same artifact schemas and report model compare local and multi-ECS runs,
  while exposing host/AZ placement and cross-host clock uncertainty;
- cost, quota, credentials, ownership tags, preflight, and deterministic teardown
  are enforced and auditable.

## Milestone 3: Multi-ECS Scale-out (500, 1000, and 2000 real nodes)

### Objective

Scale the proven native multi-ECS runtime from 200 to 500, 1000, and 2000 real
Valkey nodes without weakening lifecycle coverage, measurement semantics,
diagnostic depth, or cleanup guarantees.

### Scope

- explicit 500, 1000, and 2000 node execution profiles;
- quota, capacity, port, file-descriptor, memory, CPU, network, storage, and cost
  preflight for every scale rung;
- bounded orchestration concurrency, batching, backpressure, retries, and
  resumable execution so the controller is not the scale bottleneck;
- scalable metric ingestion and artifact transfer with cardinality, retention,
  and sampling policies that preserve critical event and tail-latency evidence;
- hierarchical health, convergence, fault-target, and cleanup verification;
- scale-comparison analysis for startup, stabilization, management operations,
  fault detection, failover, recovery, workload impact, resource efficiency, and
  total experiment cost.

### Scale ladder and exit criteria

Each rung is a promotion gate: 500 must pass before 1000, and 1000 before 2000.
Dry-run plans or partial node counts never count as real-rung evidence.

For each rung, completion requires:

- exact requested and observed real node counts with topology and host placement
  proof;
- successful lifecycle, stability, representative management, and representative
  fault/failover scenarios using the Milestone 2 contracts;
- bounded control-plane and collection overhead, with any sampling change
  recorded and justified;
- no unexplained metric gaps, silent scenario reduction, fixture fallback, or
  cleanup residue;
- a validated visual report that identifies how latency, failures, workload
  impact, resource use, and cost change relative to 200 nodes and earlier rungs.

Milestone 3 is complete only after all three real scale rungs pass. Every real
run is explicit and resource-approved; none of these sizes becomes a normal
development default.

## Cross-Milestone Contracts

The following contracts must remain stable across all milestones:

- **Scenario contract:** lifecycle, management, workload, stability, fault, and
  recovery semantics are defined independently of the runtime backend.
- **Artifact contract:** versioned schemas, provenance, run identity, timestamps,
  missing-value semantics, and real-versus-dry-run evidence classification.
- **Observability contract:** the same lifecycle/sub-stage taxonomy, augmented
  with host, AZ, transport, and controller dimensions when distributed.
- **Analysis contract:** analysis consumes artifacts rather than live runtime
  state and can compare runs across runtime, topology, scenario, and scale.
- **Report contract:** reports expose evidence quality and missing data alongside
  performance results; they never turn absent evidence into a pass.
- **Safety contract:** explicit ownership, resource preflight, bounded defaults,
  run-scoped fault mechanisms, and deterministic cleanup.

## Delivery Dependencies

```text
Milestone 1: functional completeness + diagnostic completeness
      |
      v
Milestone 2: runtime abstraction + distributed control + native ECS processes
      |
      v
Milestone 3: control-plane scale + telemetry scale + staged real-node promotion
```

Milestone 2 must not begin by reimplementing scenarios for ECS; it should extend
the runtime, transport, placement, and collection boundaries established in
Milestone 1. Milestone 3 must not compensate for orchestration or telemetry
limits by silently reducing coverage. Any intentional scale-specific reduction
must be explicit, justified, and visible in the acceptance report.
