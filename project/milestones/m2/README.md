# M2 - Local Cluster Formation and Failover Performance

M2 optimizes the two weak parts of the proven M1 local lifecycle: forming an
exact cluster and recovering from an unplanned primary failure. It tunes the
`valkey-scale-lab` orchestration path and evidence-backed Valkey parameters; it
does not fork Valkey, trade correctness for speed, or treat a smaller or
simulated run as real performance evidence.

The authoritative completion conditions are in `milestone.json`. This README
fixes the experiment protocol and explains why those conditions were chosen.

## Current Evidence

The retained exact-real captures show that correctness is established but the
critical paths are not yet fast:

| Metric | Exact 50 | Exact 200 |
| --- | ---: | ---: |
| lifecycle `cluster_form` | 68.520 s | 71.564 s |
| `primary_cluster_create` | 24.263 s | 66.894 s |
| `replica_meet` | 9.103 s | 2.260 s |
| complete `fault_matrix` | 221.876 s | 216.493 s |
| `network_partition` | 56.058 s | 44.693 s |
| `minority_majority` | 81.406 s | 83.792 s |
| `split_brain_detection` | 81.480 s | 82.870 s |

The sources are the `lifecycle_timeline.json`,
`runtime_timing_breakdown_local_full_flow.json`, and
`admission_v2/fault_results.json` files under the retained
`artifacts/captures/real_local_full_flow/exact_50_20260714` and
`exact_200_20260714` product captures.

Those captures also report 74 ms and 301 ms promotion latency. That path first
uses `CLUSTER FAILOVER TAKEOVER` for a controlled handoff before restarting an
owned process. It bypasses failure detection and is not an automatic-failover
RTO baseline. M2 therefore requires a new hard-failure baseline.

## Lessons From The Valkey 1B Experiment

The Valkey team's
[1 billion RPS experiment](https://valkey.io/blog/1-billion-rps/) used 2,000
nodes arranged as 1,000 primary/replica shards. It drove 512-byte `SET`
traffic from 750 client hosts and sustained roughly 1 billion aggregate RPS.
That throughput is not a target for a local laptop lab; the transferable value
is the method:

1. Separate client throughput from cluster-bus control-plane behavior.
2. Treat service readiness as membership, slots, replicas, and a usable data
   path, not merely successful process launch.
3. Inject real primary loss with `SIGKILL`, not a coordinated handoff.
4. Measure recovery from the first observed `PFAIL` until `cluster_state:ok`
   and all slots are covered.
5. Sweep simultaneous primary-failure rates instead of extrapolating from one
   failed shard.

The published recovery chart reports 9, 11, 14, 24, and 52 seconds from first
`PFAIL` to full recovery at 0.1, 10, 25, 33, and 50 percent primary failure.
M2 retains that interval for comparison but also measures from `SIGKILL`, so a
large failure-detection delay cannot disappear from the user-visible RTO.
The official
[large-cluster tracker](https://github.com/valkey-io/valkey/issues/2281) uses a
15-second node timeout and requires resilience to 33 percent of overall node
failures. Separately, the 1B recovery matrix sweeps failed primaries; M2 takes
its largest mandatory 33-percent-primary cell from that matrix, not from the
tracker's overall-node criterion.

The 1B article reports throughput and recovery, but not a repeated cluster
initialization latency distribution. M2 therefore does not invent an official
startup baseline. It transfers the MEET/gossip convergence model and the
tracker's cluster-initialization concerns, then derives formation budgets from
this repository's retained local evidence. The AWS host tuning and its
availability-relaxed `cluster-require-full-coverage no` and
`cluster-allow-reads-when-down yes` settings are not adopted; M1's full-slot and
health gates remain authoritative.

The related large-cluster work also shapes the resource checks. Valkey
[PR 2009](https://github.com/valkey-io/valkey/pull/2009) found that bounding
new cluster-link accepts reduced best-case peak memory by 46 percent and time
to serve traffic by 57 percent. Valkey
[PR 1018](https://github.com/valkey-io/valkey/pull/1018) serialized competing
multi-primary elections by failed-shard rank. Valkey
[PR 2154](https://github.com/valkey-io/valkey/pull/2154) throttled reconnect
storms, and
[PR 2277](https://github.com/valkey-io/valkey/pull/2277) reduced heavy-failure
CPU pressure from redundant failure-report processing. The lesson is not
"maximize parallelism"; it is to bound work and measure readiness, CPU, memory,
connections, and convergence together.

## Cluster Formation Protocol

The experiment ladder is exact 50, 100, and 200 nodes. Exact 100 is included
because it exposes the transition between the M1 endpoints and prevents an
optimization from hiding a middle-scale knee.

An exact-50 discovery screen compares the current
`valkey_cli_cluster_create_primaries` baseline with bounded alternatives. The
existing `manual_tree_meet_parallel_slots` path remains a diagnostic control,
not an assumed winner: the archived exact-50 A/B capture measured 45.382
seconds for that path, including 44.367 seconds in batched `CLUSTER ADDSLOTS`,
versus 25.312 seconds for the default path. The prioritized alternative is
tree-MEET plus Valkey's native
[`CLUSTER ADDSLOTSRANGE`](https://valkey.io/commands/cluster-addslotsrange/),
reusing already-observed primary IDs and screening bounded orchestration
parallelism of 4, 8, and 16. Candidates may not synthesize `nodes.conf`, skip
normal MEET/slot/replica convergence, or use unbounded fanout.

Only candidates that beat the baseline and pass correctness in the discovery
screen advance. Each promoted candidate then runs a paired baseline/candidate
matrix at exact 50, 100, and 200 with at least seven independent trials per arm
and scale.

Run order alternates `AB` and `BA`. A pair must use the same Valkey binary and
product digest, configuration, nodehost placement, topology, machine, resource
preflight, and probe workload. Cleanup must finish and zero residual ownership
must be proven before the next trial.

The primary formation timer starts when the last owned Valkey process answers
`PING` and ends only when every node has a clean topology snapshot and the
cluster-aware `SET`/`GET` probe succeeds. Every run records monotonic timestamps
for process ready, first membership command, all primaries known, all slots
assigned, all replicas attached and
synchronized, every-node clean convergence, and first successful cluster-aware
`SET`/`GET`. It also records command counts and time, retries and sleeps, CPU
time, peak RSS, file descriptors, cluster-link counts and errors, and
cluster-bus messages and bytes.

The promotion budget is deliberately both relative and absolute:

- exact-50 median formation time improves by at least 20 percent, and exact 100
  and 200 median formation time improves by at least 30 percent, over the paired
  baseline;
- observed p95 is at most 60 seconds at 50, 100, and 200 nodes;
- bootstrap-window peak RSS, CPU time, file descriptors, connection count, and
  cluster-bus bytes regress by no more than 10 percent, with zero cluster-link
  errors or buffer-limit overflows;
- every admitted run has exact membership, 16,384 covered slots, no handshake,
  `PFAIL`, or `FAIL` residue, synchronized replicas, and a working data path.

All experiment percentiles use the nearest-rank estimator. With seven formation
trials, the reported p95 is therefore the worst observed trial rather than an
interpolated value.

## Automatic Failover Protocol

Timeout candidates `5000`, `10000`, and `15000` ms are first screened with a
single failure at exact 50. The current `30000` ms setting is the paired
baseline in every cell. Surviving candidates run the complete matrix at exact
50 and 200, alternating baseline/candidate order while holding build, topology,
targets, placement, host, workload, and observation cadence constant:

| Failed primaries | Purpose | Trials per scale |
| ---: | --- | ---: |
| 1 | detection and election floor | at least 10 |
| 10% | concurrent election behavior | at least 10 |
| 33% | bounded large-failure recovery | at least 10 |

Targets are deterministic shards whose replicas live on different owned
nodehosts and failure domains. The harness sends `SIGKILL` to the owned Valkey
primary processes at one recorded barrier, verifies each target PID is gone,
and records multi-process injection skew, which must not exceed 500 ms.
`CLUSTER FAILOVER`, `FORCE`, and
`TAKEOVER` are forbidden in this experiment. Each matrix cell is a new physical
fault with its own command log and provenance. Every trial starts from a fresh
exact cluster after the preceding cluster proves zero residual ownership, so a
prior promotion, epoch, or topology change cannot contaminate the next sample.

Percentage cells round to the nearest primary with halves rounded up: exact 50
therefore kills 3 of 25 primaries for the 10-percent cell and 8 of 25 for the
33-percent cell. The mandatory matrix stops at 33 percent to preserve a primary
quorum at both scales. A 50-percent storm is exploratory only and cannot replace
any required cell.

A persistent cluster-aware client continuously exercises both affected and
unaffected slots with 512-byte values. It records redirects, error classes,
timeouts, read/write availability, and latency without launching a new
`docker exec` or CLI process for every operation. Every affected shard receives
at least one read and one write attempt per 100 ms. Client recovery is the later
of the per-shard recovery endpoints across all affected shards. A shard endpoint
is the end of its earliest one-second window containing at least ten consecutive
write/read pairs in which the write succeeds and the following read returns the
expected value, with no error or timeout; a single lucky request cannot end RTO.

Each trial records these intervals independently:

- `SIGKILL -> first PFAIL`;
- `first PFAIL -> quorum FAIL`;
- `quorum FAIL -> replica promotion`;
- `promotion -> all slots covered and cluster_state:ok`;
- `SIGKILL -> first successful affected-slot read`;
- `SIGKILL -> first successful affected-slot write`;
- `cluster_state:ok with all slots -> stable all-affected-shard client recovery`;
- recovery -> every-node topology convergence.

At least ten trials are required for every arm and cell. Percentiles use the
nearest-rank estimator, so ten-trial p95 is the worst observed trial. Candidate
median and p95 end-to-end recovery must each improve by at least 20 percent over
the paired `30000` ms baseline. The candidate absolute p95 budgets are:

| Failed primaries | SIGKILL to client read/write recovery | First PFAIL to cluster OK and all slots |
| ---: | ---: | ---: |
| 1 | <= 35 s | <= 10 s |
| 10% | <= 45 s | <= 15 s |
| 33% | <= 55 s | <= 25 s |

Across the full matrix, process-gone-to-first-`PFAIL` p95 is at most 25 seconds,
and cluster-OK-with-all-slots to stable client recovery is at most two seconds.
These two budgets prevent a faster election from hiding slow detection or a
topology that is nominally healthy but still unusable.

The selected timeout must also complete a 30-minute exact-200 steady-state soak
with zero unexpected `PFAIL`, `FAIL`, promotion, split brain, slot loss,
cluster-link error, or buffer overflow. In every fault-to-convergence window and
the soak, candidate peak RSS, CPU time, file descriptors, connection count, and
cluster-bus bytes may not exceed the paired baseline by more than 10 percent.
Resource comparisons use equal-duration fixed observation windows, not windows
truncated when the faster arm recovers. During paired steady-state workload
windows, 512-byte `SET` throughput may regress by no more than 5 percent, p99
latency by no more than 10 percent, and the error rate must remain zero. A faster
but unstable timeout does not pass.

## Promotion Rule

No strategy or timeout becomes the default from one fast sample or from the
Valkey 1B result alone. Promotion requires validated product-owned comparison
artifacts with complete build, configuration, environment, workload, topology,
command, timing, resource, and cleanup provenance. The promoted defaults must
then pass the full M1 exact-50 and exact-200 acceptance unchanged.

M2 is currently `DEFINED`. The Catalog has no executable Test that proves this
paired repeated-run performance contract, so the Criteria intentionally omit
`check` rather than attaching a correctness Test that cannot establish the
performance claim.
