# Connection cost of observation, measured at 200 and projected to 2000

Written after exact-200 failed three different ways for weeks and all three
turned out to be downstream of one thing: how many TCP connections the control
plane opens to observe the cluster. The two fixes that followed (`49b2e3ab`,
`eac9b545`) are recorded in CLAUDE.md; this document keeps the measurements and
the 2000-node reasoning so neither has to be re-derived.

## How the numbers were taken

`socket.create_connection` was wrapped by a `sitecustomize.py` on `PYTHONPATH`,
outside the repository, counting calls by the nearest product frame; probe
rounds were counted by wrapping `LightClusterProbe.collect`, because each probe
runs its per-node work in a thread pool where the worker stack shows only the
transport. Socket state came from `netstat` sampled every 2s by a script that
opens no connections of its own. One complete exact-200 run, before either fix.

## What one exact-200 run cost

**165,095 host TCP connections**, of which **485 whole-fleet 200-node probes**
(97,000). By caller:

| Whole-fleet probes | Caller |
| --- | --- |
| 82 | `_management_live_topology` ← rolling restart, 2 per batch |
| ~93 | `_management_cluster_health` ← `_management_wait_clean_cluster`, 1 Hz |
| 88 | `_management_topology_snapshot`, four callers |
| 71 | `FullClusterValidator.run` convergence retry, 0.5 Hz |

Unperturbed socket profile: TIME_WAIT sits at ~2,800 through formation,
stabilize and the load lane, then ramps to **16,349** within ~90s of the
management lane starting, against 16,384 ephemeral ports. The run dies with
`[Errno 49]`. A run that instead died at cluster convergence peaked at 3,354 -
that failure is a different problem and not this one.

A controlled result fell out of the instrumentation: the counting wrapper slowed
connection creation enough that TIME_WAIT stayed ~1,200, and that run passed all
twelve lifecycle steps. The only variable was the rate of connection creation.

## What the design budgets

| Lane | Design | Product before the fixes |
| --- | --- | --- |
| Layer 1 light probe | one whole-fleet round / 60s, rolled evenly (§4.1, §4.4) | one connection per node per round, and see the loops |
| Layer 2 topology | 3-5 observer nodes, not growing with N (§6.1) | matches |
| Sentinel | O(N) **persistent** connections, 33 GET/s (§7.5, §7.7) | matches - `sentinel.py` caches per endpoint |
| Fault window | O(1), two canaries at 100ms (§7.6) | matches |
| Resources | distributed local samplers, no Valkey commands (§11.1) | matches |
| Management control plane | *not specified* | whole-fleet probes on 1 Hz and 0.5 Hz loops |

§14 budgets O(N) *persistent* connections for Sentinel and memtier and names FD
pressure as the 2000-node preflight risk. It budgets no connection *churn* at
all, and §16 item 3 forbids O(N²) normal collection steps.

## Projection to 2000 nodes

Under §15 the ECS adapter replaces inventory and endpoint discovery, process
lifecycle, the actuator, local sampler deployment and evidence upload; the
three-layer validation logic explicitly stays where it is. `NodeBackend` matches
that - process lifecycle and inventory, no probe operation. So under M3 every
layer-1 connection to all 2000 nodes across 50-100 ECS instances still
originates from **one controller process**. The only distributed observation in
the design is the resource sampler.

- **O(N²) terms**: the rolling restart's per-batch whole-fleet probes were
  `2 × N × N/8`. At 200 nodes that is ~16k connections; at 2000 it is ~1M.
  Removed by `49b2e3ab`.
- **O(N) per second terms**: `_management_wait_clean_cluster` at 1 Hz and
  `FullClusterValidator` at 0.5 Hz become **2,000 and 1,000 queries per second**
  at 2000 nodes. `eac9b545` removed the socket cost of those queries, not the
  queries. This is the open item.
- **Timing is not the constraint**: 2000 nodes at concurrency 32-64 with ~3ms
  per node cross-AZ is ~125ms per whole-fleet round, so a 1 Hz poll is
  temporally feasible. Only its cost is not.

### What binds on Linux/ECS rather than macOS

The 16,384-port global ceiling is a macOS property; the allocator there ignores
destination diversity, which is why 200 distinct destinations still exhausted
it. On Linux the default range is 32768-60999 and `connect()` conflict checks
are per 4-tuple, so destination diversity raises the aggregate ceiling and the
per-destination limit (~470 new connections/s to any one node) is far above
anything here. What binds instead, and what a 2000-node preflight must actually
verify - §14 already says so:

- total sockets in TIME_WAIT on the controller: 2,000/s × 60s = **120,000**,
  against a `tcp_max_tw_buckets` default typically between 32k and 262k;
- stateful middleboxes - per-ENI security-group connection tracking, NAT and
  load-balancer flow tables - which count flows globally and have no equivalent
  on a loopback Docker host.

## The conclusion that matters

The architecture is viable at 2000 nodes **at the cadences the design
specifies**, even with observation centralized. What is not viable is a control
plane that treats "observe every node" as a cheap primitive on a one-second
loop. That habit lives in code §15 forbids the ECS adapter from replacing, so it
has to be fixed where it is, and it will resurface on ECS as query volume even
though the socket cost is now gone.
