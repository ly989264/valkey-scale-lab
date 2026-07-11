# 09_SCALE_AND_RESOURCE_POLICY.md — Scale, Resource, and Safety Policy

## Default scale policy

Normal development defaults remain capped at 100 nodes. The existing 1000-node dry-run remains opt-in and non-automatic.

The user explicitly requires a 200-node failover latency curve. That stage is a bounded exception with strict preflight. It must not change the default max for unrelated operations.

## Resource preflight

Before any 30+ node stage, run or implement resource preflight that records:

```text
host OS and architecture
Docker availability and version
available memory
available disk
available CPU count
port range availability
container runtime limits
estimated nodes per host
estimated memory per node
estimated disk per node
estimated workload client overhead
```

A stage must fail or block when required resources are insufficient. It must not pass with fake curves.

## 30/50/100 node policy

P20 must run 30, 50, and 100 node failover samples through real Valkey. If any rung fails due to resource insufficiency, P20 is blocked and must not be marked complete.

## 200 node policy

P21 must run 200-node failover samples through real Valkey when preflight passes.

Rules:

- P21 is automatic because the user explicitly requested 200-node failover data.
- P21 may reduce workload QPS to a documented low but non-zero probe workload if needed for resource safety.
- P21 must not use fake Valkey.
- P21 must not silently downshift to 100 nodes.
- P21 must not pass with only dry-run evidence.
- If preflight fails, write `BLOCKED.md`, leave the stage incomplete, and do not commit a passing stage.

## 1000-node policy

P14 remains non-automatic and dry-run only unless the user explicitly opts in with the existing environment variable. Do not let P21 or any other goal-loop stage start 1000 nodes.

## Local single-host and multi-host behavior

The implementation should prefer a single-host local Docker path when resources allow. If multi-host support exists by the time P20/P21 run, stages may distribute nodes across configured hosts, but the same artifact schemas and cleanup checks apply.

## Safe degradation

Safe degradation is allowed only when a stage document explicitly permits it. Examples:

- lower workload QPS for large scale after recording the reason;
- longer timeouts for 100/200 node convergence after recording the reason;
- sandbox proxy fallback when container `tc` support is unavailable.

Safe degradation is not allowed for:

- replacing real Valkey with fakes;
- replacing 200 nodes with 100 nodes;
- omitting workload impact metrics;
- omitting cleanup;
- using host-level network mutation.
