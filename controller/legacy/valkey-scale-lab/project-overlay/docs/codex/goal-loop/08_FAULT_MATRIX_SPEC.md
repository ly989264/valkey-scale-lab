# 08_FAULT_MATRIX_SPEC.md — Fault, Failover, Partition, and Workload Matrix

## Purpose

This document defines the missing fault/failover matrix. Existing primary-stop promotion on a small cluster is not sufficient.

## Final fault matrix rows

| Fault row | Required stage | Node counts | Core measurement |
|---|---|---:|---|
| primary_stop_failover | P20/P21 | 30, 50, 100, 200 | promotion latency, cluster recovery, read/write unavailability |
| replica_stop | P22 | 6/10 and summary at scale when available | workload impact with no promotion expected |
| node_host_stop | P22 | up to 100 | impact of stopping all nodes assigned to one logical host |
| az_stop | P22 | up to 100 | impact of stopping one virtual AZ |
| network_delay | P23 | up to 100 | QPS/latency/error delta under delay |
| network_loss | P23 | up to 100 | QPS/latency/error delta under packet loss |
| network_partition | P24 | up to 100 | minority/majority availability and recovery |
| network_flap | P23 | up to 100 | repeated degradation/recovery behavior |
| minority_partition | P24 | up to 100 | write/read availability and safety in minority side |
| majority_partition | P24 | up to 100 | availability and promotion behavior in majority side |
| split_brain_window | P24 | up to 100 | duration of any conflicting primary/slot/write indicators |
| fault_workload_impact | P25 | all above | windowed QPS, latency, and error comparison |

## Failover latency curve requirements

P20 must produce a curve for 30, 50, and 100 nodes. P21 must extend the curve with 200 nodes.

Minimum sample policy:

```text
P20: min 3 samples per rung for 30, 50, 100
P21: min 3 samples for 200
```

Each sample must be a real Valkey run or an isolated real-Valkey sub-run. Reusing a single generated value for multiple samples is forbidden.

Each sample must record:

- selected target primary;
- replica candidates;
- fault injection method;
- promotion detection method;
- slot coverage recovery detection method;
- workload impact reference;
- cleanup result.

The curve artifact must contain raw samples and derived series. Derived series must include p50/p95/max for promotion latency and cluster recovery latency when sample count supports it. With exactly three samples, p95 may be computed by the declared percentile method; the method must be recorded.

## Replica stop requirements

Replica stop passes only when:

- the target is a replica before stop;
- the fault is applied through owned runtime or project fault API;
- no unintended primary promotion is counted as success;
- reads/writes continue or failures are quantified;
- recovery after replica restart is measured;
- cleanup verifies the target is restored or removed intentionally.

## Node-host stop requirements

Logical host stop is a project-level abstraction. It may map to local Docker container groups in a single-machine environment.

Pass criteria:

- host-to-node mapping exists in the cluster plan;
- all nodes assigned to the target logical host are stopped through owned controls;
- operation impact is measured by AZ, role, and slot ownership;
- workload impact is measured;
- recovery is measured after host restore;
- cleanup is verified.

## AZ stop requirements

Virtual AZ stop passes only when:

- AZ placement exists in the plan;
- all nodes in the target AZ are faulted through owned controls;
- minority/majority implications are recorded;
- workload impact is measured;
- recovery and split-brain indicators are measured;
- cleanup is verified.

## Network delay/loss/flap requirements

Network faults must not mutate host networking. Acceptable implementation paths:

```text
container_netns_tc: tc/netem inside owned container namespace only
sandbox_proxy: project-owned proxy layer that delays/drops/flaps traffic
unsupported_skipped_with_reason: allowed only when a stage explicitly permits an unsupported row and still covers another implementation path
```

Delay row must record delay, jitter, affected direction, target set, and duration.

Loss row must record loss percentage, correlation if used, affected direction, target set, and duration.

Flap row must record up/down cadence, iterations, target set, and observed transitions.

## Partition requirements

Partition faults must record partition groups explicitly:

```text
groups:
  majority: [logical_node_ids]
  minority: [logical_node_ids]
  isolated: [logical_node_ids]
traffic_policy:
  block_between_groups: true
  allow_within_group: true
```

A partition report passes only when probes are taken from both sides where feasible and topology views are compared.

## Split-brain-window requirements

A split-brain indicator exists when any detector observes one of the following:

- two or more nodes claim primary ownership of overlapping slots;
- partition-side cluster views disagree about primary ownership for a slot;
- writes to the same logical key range succeed on conflicting sides when they should not;
- an old primary accepts writes after a new primary has been promoted for the same slot range.

The split-brain report must record:

```text
detectors_run
indicator_observed
indicator_start_ms
indicator_end_ms
split_brain_window_ms
conflicting_slots
conflicting_nodes
conflicting_write_keys
missing_detectors_with_reason
```

`split_brain_window_ms=0` means detectors ran and no indicator was observed. It does not mean “not implemented.”

## Fault-period workload impact

Every fault row must attach a workload impact reference with windowed metrics. P25 consolidates the per-stage references into a cross-fault table.

Required comparisons:

```text
fault_window.achieved_qps / baseline.achieved_qps
fault_window.p99_ms - baseline.p99_ms
fault_window.error_rate - baseline.error_rate
recovery_window.duration_ms
post_recovery.achieved_qps / baseline.achieved_qps
```

When a workload window is intentionally absent, the row must be `FAIL` unless the stage document explicitly permits a skip.
