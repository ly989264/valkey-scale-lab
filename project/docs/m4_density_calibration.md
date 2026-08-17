# M4 density calibration: can 1280 nodes run honestly on eight hosts?

Not a roadmap item and not a rung of any ladder. Taken 2026-08-15 because Google
Cloud refused the quota increase this project's M4 plan assumed - CPUs, disks and
GCE instance counts, on a new project - so the eight `c4a-standard-2` hosts of
`gce-m3b` cannot grow and cannot be resized. **No baseline was frozen and no
product code changed.**

## §1 The question, and why it is not the obvious one

M4's target is 256 shards × 4 replicas = **1280 nodes**. At the shipped density
knob that is 52 nodehosts, and a native run places exactly one nodehost per host,
so the plan of record needed 52 hosts. That number was never a requirement - it
is what falls out of leaving `max_logical_nodes_per_nodehost` at 25.

Compiled at HEAD against a manifest of this fleet's shape, through
`validate_semantics`, `build_cluster_plan` *and* the run path (`_node_specs` +
`_process_nodehosts`), 1280 nodes plan cleanly at every even host count tried:

| hosts | nodes/host | mem/host @32 MiB | colliding shards | shard AZ split | fleet |
|---|---|---|---|---|---|
| **8 (the fleet)** | 160 | 5120 MiB of 7900 | **0/256** | 3/2 | 640/640 |
| 16 | 80 | 2560 MiB | 0/256 | 3/2 | 640/640 |
| 26 | 50 | 1600 MiB | 0/256 | 3/2 | 640/640 |
| 52 (default knob) | 25 | 800 MiB | 0/256 | 3/2 | 640/640 |

Fault domains and the §7.1 AZ policy hold at every one. Two constraints found
while compiling: host counts must be **even** (13 refuses - `nodehosts_per_az: 7`
cannot be met by the 6 hosts in the other AZ), and at 8 hosts the node memory
limit must drop from 64 MiB to 32, because 160 × 64 MiB is 10240 MiB against
7900 of RAM.

So the question is not whether 1280 nodes *plan* on eight hosts. It is whether a
run that dense still measures the cluster rather than the CPU it is contending
for. **Every number this project has taken on real hosts was at 25 nodes per
host - 12.5 valkey-servers per vCPU. The eight-host M4 plan is 80 per vCPU.**

That is the M3-A-2 trap in a new place. That spike assumed simulated-host
transport numbers were lower bounds; they were the opposite, because those hosts
were containers contending for one laptop's CPU. An unmeasured 6.4× density
change is the same assumption again, and this time it would sit underneath M4's
headline results.

## §2 The experiment

`templates/configs/real_ecs_200_2host.yaml` is `real_ecs_200.yaml` with two
lines changed - `nodehosts_per_az` 2 → 1 and `max_logical_nodes_per_nodehost`
25 → 100. Same 200 nodes, same 100×1 shape, same ports, same workload, same
commit. **Only the host count moves, 8 → 2**, which is the one variable the
experiment is about. It uses two of the eight hosts and leaves six idle.

That gives **100 nodes per host = 50 per vCPU, four times the measured density**.
It is not M4's 80 per vCPU and cannot be: reaching that needs 160 nodes on one
host, and one host cannot serve two AZs. 200 nodes on 2 hosts is the densest
shape the 200-node cap admits, so **4× is the largest lever available and the
result is a trend, not a proof at M4's own density.**

Memory was checked before running rather than after: 100 × 64 MiB = 6400 MiB
against 7636 MiB available, so the node memory limit stays at its default and
the experiment keeps its single variable. In flight the real cost was far lower -
100 live servers held 958 MiB total, because `maxmemory` is a cap and not an
allocation.

Three runs, all at `52033375`, all on the same fleet the same afternoon:

| run | shape | result |
|---|---|---|
| `gate-20260815T124718Z-66c690cb` | dense-1, 2 hosts | **PASS 2055.87 s** |
| `gate-20260815T134602Z-c60b66d7` | dense-2, 2 hosts | **PASS 2086.26 s** |
| `gate-20260815T132300Z-67c89cbe` | control, 8 hosts | **PASS 1302.90 s** |

## §3 The result

| | dense-1 | dense-2 | control 8 hosts |
|---|---|---|---|
| nodes per vCPU | 50 | 50 | 12.5 |
| `run_verdict` | **12/12 OK** | **12/12 OK** | **12/12 OK** |
| fault lane | **9/12/15** | **9/12/15** | **9/12/15** |
| `ERROR` in any artifact | 0 | 0 | 0 |
| residual scans | all `found: 0` | all `found: 0` | all `found: 0` |
| node journals | 200/200 | 200/200 | 200/200 |
| probe cadence median / overruns | 100.09 ms / **0** | 100.08 ms / **0** | 100.09 ms / **0** |
| process gone → PFAIL | 42.55 s | 43.55 s | 43.04 s |
| **PFAIL → promotion** | 4.00 s | 3.00 s | 1.00 s |
| **RTO** | 46.66 s | 46.27 s | 43.76 s |
| **formation dwell** | **85.88 s** | **46.95 s** | **10.93 s** |
| management matrix | 1549.26 s | 1565.85 s | 905.87 s |

**Nothing that carries a verdict moved.** Both dense runs pass twelve of twelve
with the fault lane's three scale-fixed numbers intact, nine `REAL_PASS`, zero
residue on every host asked over ssh from outside the product, and the string
`ERROR` in no artifact. Detection - the term the failover work measured as flat
in node count - is flat in density too: 42.55, 43.55, 43.04 s. The Sentinel
probe's cadence is indistinguishable across a 4× density change, with **zero**
overruns in all three runs, which is the measurement most likely to have
degraded under CPU contention and did not.

**The host really was oversubscribed**, so this is not a null result from a lever
that failed to pull. Load average on the 2-vCPU dense host was sampled during the
run at **5.73, 4.21, 0.78, 0.43, 4.13** - bursting to nearly 3× the core count
during formation and management operations, idling between them.

### §3.1 What did move, and what it costs

- **Formation dwell is the density cost, and it reproduces.** 85.88 s and
  46.95 s against the control's 10.93 s. Read carefully, though: the control is
  the *fastest* 200-node formation ever recorded here, and the frozen real-fleet
  pair is 52.0 and 72.1 s, so **both dense values sit inside the historical
  range** and the striking ratio is partly the control being unusually quick.
  Formation is the most variable thing this product measures - the real-fleet
  range is now 10.9 to 85.9 s - and density pushes it up within that range
  rather than out of it. The 240 s no-progress window was never approached, and
  it bounds a *single* dwell rather than the total.
- **PFAIL → promotion is 3-4× the control** at 3.00 and 4.00 s against 1.00 s.
  But both dense values are far *below* the frozen r=1 exact-200 pair's 8.00 and
  19.03 s, so density's effect on this term is smaller than its ordinary
  run-to-run variance. RTO follows at 6 % apart, itself below the frozen pair.
- **The management matrix is 1.7× slower, and it is batch geometry rather than
  contention.** Restart parallelism is capped by nodehost count - one node per
  nodehost per batch - so two nodehosts give **100 batches at max concurrent 2**
  where eight give **26 at max 8**. Compiled through the real batcher in advance
  and measured at exactly those numbers. The per-batch cost actually *fell* with
  density, 7.75 s against the control's 17.4 s, because a batch of 2 restarts is
  cheaper than a batch of 8.

## §4 The answer, and what it does not say

**No evidence that density confounds this product's measurements at 4×.** Every
verdict-bearing invariant is identical, the observation machinery is unaffected,
and the two terms that move stay inside ranges the fleet already produces.
On that basis **M4's 1280 nodes on the existing eight hosts is defensible**, and
no quota increase is needed to attempt it.

Stated as narrowly as the evidence allows:

- Tested at **50 nodes per vCPU; M4 needs 80**. This is an extrapolation across
  a further 1.6×, not a measurement at the target. It is the most the 200-node
  cap permits.
- M4 raises node count *and* density together. Formation is the term that grows
  with both, and it is the one to watch first.
- Two runs a side. MR-3 §6.2 already showed two runs of one configuration
  differing by 1.75× in the control-plane term; the same caution applies here.

## §5 What M4 should plan for, compiled rather than guessed

> **Superseded 2026-08-17 in its numbers, not in its method.** The fleet was
> rebuilt from eight `c4a-standard-2` to **twelve**, using the 8 C4A vCPU the
> quota was already paying for, once a quota audit showed Hyperdisk at 500/500
> was the binding constraint and CPU was not. So M4 now plans **12 nodehosts at
> 106-107 nodes each = 53.5 valkey-servers per vCPU**, inside the 50 this
> calibration measured clean rather than the 80 that eight hosts forced, and
> **`node_memory_limit_mb` stays at 64** instead of dropping to 32. The
> rolling-restart geometry below is unchanged at 320 batches, because
> `CLUSTER_ORCHESTRATION_PARALLELISM` caps concurrency at 8. Everything this
> section says about *how* to reason still holds; the host count it assumed does
> not. See CLAUDE.md's M4-3 handoff.


**Rolling-restart geometry at the target**, through the real batcher: 1280 nodes
on 8 nodehosts gives **161 batches per operation, 322 in total, at max
concurrent 8**. Parallelism is capped by nodehost count, so eight hosts is the
ceiling however many nodes are added.

**Run duration.** At the control's measured 17.4 s per batch at concurrency 8,
322 batches is **≈93 minutes for the management matrix alone**. With formation,
the fault matrix (~290 s, flat across all three runs), evidence collection for
1280 journals and cleanup, an M4 run is on the order of **two hours** - inside
`real.ecs.full-flow`'s 14400 s timeout, but expensive enough that MR-3's "budget
several runs per rung" advice becomes a real scheduling constraint.

**Evidence volume.** 200 journals were 80 MB; 1280 nodes should be roughly 500 MB
of journals per run, on a controller whose disk had 89 GB free.

**Memory forces 32 MiB per node** at 160 nodes per host, against 64 in every run
to date. That is a second changed variable for M4 to declare in advance, not
discover in a diff.

**Two things this does not touch.** `REAL_EXECUTION_ABOVE_200_FORBIDDEN` still
refuses any real run above 200 nodes - a validation-contract change and the
operator's decision, unrelated to quota; compiling the table in §1 required a
sanctioned scale-projection profile precisely because of it. And the whole-fleet
probe cadence already on the open list (`_management_wait_clean_cluster` probes
every node at 1 Hz) becomes 1280 queries per second from a 4-vCPU controller at
M4's size. Neither was reached by this calibration, because a 200-node run does
not exercise either.
