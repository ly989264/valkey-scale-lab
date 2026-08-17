# M4-3: the first real 1280-node run

256 shards x 4 replicas on the twelve `c4a-standard-2` hosts of `gce-m3b`, through
the Gate, from the in-VPC controller. This is the first time this product has run
anything above 200 nodes for real, and the first time it has run a five-member
shard at fleet width.

**No 1280-node run has passed, and the reason is measured rather than guessed.**
Two attempts were taken and both failed on the same wall from opposite sides:
§5 is the first, §5.3 the second, and §7 the measurement that explains both and
turns them into a provisioning answer. **No baseline was frozen and none was
touched.**

**Read §2 before reading any result.** Everything it declares was compiled at
`17b2b798` against the real fleet manifest *before* a run was taken, which is the
rule MR-2 and MR-3 established: a quantity predicted after the fact is not a
prediction. §3 is a placement defect the compile found and no run had ever met;
it is not this item's to fix.

## §1 What stood between the exception and a Gate run, and why it was one entry

`9d797b80` admitted a real 1280-node run to the *library*:
`is_exact_1280_native_ecs_profile` is the fourth named bounded exception, and
`templates/configs/scale_1280_native_ecs_optin.yaml` is the configuration it
names. `real_execution_above_200_exception_memo.md` §5 records deliberately
*not* registering a catalog entry for it, because an entry nothing has ever
executed is the placeholder the milestone rules forbid. So the executable
boundary stayed where it was: `real.ecs.full-flow` declares `nodes` with
`"maximum": 200`, and no configuration could cross it.

`real.ecs.full-flow-1280` is that entry, and it declares `nodes` with
**`minimum` and `maximum` both 1280**. A range would be wider than the exception
it exists to exercise - the exception names a node count on purpose, and an entry
admitting 30..1280 would let a configuration the exception refuses reach the same
runner. `real.ecs.full-flow` keeps its `maximum: 200` untouched, so every
exact-200 acceptance entry is exactly what it was and M3's milestone is unmoved.

Everything else is `real.ecs.full-flow`'s own argv: `scripts/ecs_gate.py`, which
raises `RLIMIT_NOFILE` toward 65536 and `execv`s the CLI with
`--backend native_multi_ecs`. **No `--profile` flag**, because the run path
resolves `exact-1280` from the node count alone - and because `cli.py`'s
`gate execute --profile` carries a hardcoded `choices` list that does not contain
`exact-1280`, so an entry that passed the flag would be refused by argparse
before anything else ran. That is a latent inconsistency in the CLI, reported
here and not fixed: nothing needs the flag.

**The counts it moved, measured rather than predicted: catalog 99 -> 100, and
nothing else.** `repository.all` is still **92** and the M1 plan still **91**,
because a `real.ecs.*` entry is a `command` runner in neither the
`repository.all` suite nor M1's expansion - the same result `m3_acceptance_
registration_map.md` recorded when it registered three of them. A handover that
says otherwise is quoting the pytest-entry rule.

The entry was deliberately **not** added to the `real.ecs.full-suite` suite.
That suite is the operator-invoked set behind M3's acceptance; adding a
two-hour 1280-node run to it would make an M3 check cost an M4 run.

One regression test guards the boundary in both directions -
`real.ecs.full-flow` must still refuse 1280, and the new entry must refuse 1279
and 1281. It joins `verification/tests/test_contracts.py`, a module the catalog
already registers, so it moves no count. Mutation-checked twice: widening the new
entry's maximum, and widening `real.ecs.full-flow`'s to admit 1280, each make it
fail.

### §1.1 The entry has to assert the operator act, and the first attempt found out how

The entry as first written was `real.ecs.full-flow`'s argv with a wider node
bound, and it **failed in 0.21 s without touching the fleet**. The reason is
correct and is the whole point of the exception:
`local_full_flow_v1.json`'s `scale_policy` sets
`above_200_requires_operator_opt_in` and `above_200_requires_cost_acknowledgement`,
so `GateOrchestrator._execution_permission_failure` refuses any plan above 200
nodes whose request carries neither - and `real.ecs.full-flow`'s argv carries
neither, correctly, because exact-200 is not above 200.

So `scripts/ecs_gate.py` gained two pass-through flags, **off unless an entry
asks for them**, and the 1280 entry asks for them. That keeps
`real.ecs.full-flow`'s argv byte-identical to what every frozen real baseline was
taken under, which the boundary test now asserts in both directions and which is
mutation-checked both ways.

**Reported rather than slipped in, because this is the safety surface the memo
was written about.** `real_execution_above_200_exception_memo.md` §3.2 says
`operator_opt_in` and `cost_acknowledged` are threaded arguments "which no file
can assert about itself - that is what makes it an operator act rather than a
configuration", and a catalog entry is a file. The distinction that survives is
between the run's *configuration* asserting it and the *invocation* asserting it:
the entry is part of the invocation, exactly as `--backend native_multi_ecs`
already is, and a run reaches it only because an operator named the 1280-node
test. What still cannot be self-asserted is what matters - no configuration can
put itself past `is_exact_1280_native_ecs_profile`, and no node count but 1280
can reach this runner.

### §1.2 A Gate-plan refusal reports a traceback instead of a verdict

Found by the same attempt and **reported, not fixed**. When
`_execution_permission_failure` or `_contract_failure` refuses, every lifecycle
step is marked skipped and `GateService.execute` returns a `GateResult` carrying
the real reason - here `REQUEST_OPERATOR_OPT_IN_REQUIRED`, "explicit operator
opt-in is required for this Gate plan". `run_exact_gate` then calls
`adapter.execution_snapshot` unconditionally, which raises
`AdapterOwnershipError: run_id '...' has no adapter execution`, because no step
ever registered one. The `GateResult` is discarded on the way out and
`_write_run_verdict` - the next line - never runs.

So the operator is shown "has no adapter execution" for a run that was refused
for a stated reason, and the refused run leaves **no `run_verdict.json` at all**.
That is the same family as the admission defect closed in 2026-08-13's §12.2
work: a run whose outcome was decided somewhere the reader cannot see. It is not
this item's to close - it is on `run_exact_gate`'s path, which every real run
passes through, so it needs its own change and its own two consecutive real runs
behind it. It affects no passing run, which is why no acceptance to date has met
it.

### §1.3 The reclaim proof had to be told how dense to be

`real_execution_above_200_exception_memo.md` §4 asks for the ownership proof at
the new density *before* a full-flow run, so that a two-hour run failing at
ninety minutes does not leave 1280 processes across twelve hosts with no measured
reclaim behind it. `scripts/native_cleanup_proof.py` hardcoded
`NODES_PER_HOST = 2`, so run as it stood it would have proved reclaim at two
processes a host and said nothing about a hundred.

It now takes `--nodes-per-host`, defaulting to the 2 every prior proof was taken
at. The enumeration itself did not change and did not need to - it walks `/proc`
by working directory and does not care how many it finds - which is exactly why
the number has to be stated rather than assumed: "reclaim works" at two is not
evidence about a run that places a hundred and seven.

## §2 Declared in advance: every quantity, compiled at `17b2b798`

Compiled on the controller against the real `gce-m3b` manifest
(sha256 `e2ea81b2…`, twelve hosts), through `validate_semantics`,
`build_cluster_plan`, the run path's `_node_specs` and `_process_nodehosts`, and
the **real** rolling-restart batcher. Not read off a table.

| quantity | declared |
|---|---|
| semantic errors | **0** |
| nodes / shards / replicas | **1280** = 256 x (1 + 4) |
| nodehosts = hosts | **12**, one per host |
| nodes per nodehost | **107 x 8, 106 x 4** |
| fleet per AZ | **640 / 640** |
| shards sharing a nodehost | **0 of 256** |
| shard AZ split | **3/2, all 256** |
| client ports / bus ports | **7800-9079** / **17800-19079** |
| memory per host | 107 x 64 MiB = **6848 MiB** of 7911 |
| `runtime_fd_limit` `required_min` | **10,624** against `ecs_gate.py`'s 65536 |
| rolling-restart batches, **each** operation | **194**, max concurrent **8** |
| batch sizes, each operation | 8 x 147, 7, 5, 4, 3, 2 x 42, 1 |
| `cleanup_actions` rows | **60** = 5 x nodehosts, native, four kinds |
| Sentinel `canary_count` = shard count | **256** |
| node configs carrying the r>=2 topology pin | **1280 of 1280** |
| `management_command_log` rows, by the MR-2 law | **~21,900** |
| fault lane | **9 scenarios / 12 command rows / 15 windows**, invariant by design |

Two of these disagree with what M4-3 was handed, and the compile is what says so.

**The batch geometry is 194 per operation, not 160.** `m4_density_calibration.md`
§5 compiled 161 per operation for 1280 nodes on *eight* nodehosts, and the
twelve-host handoff carried 320 in total forward unchanged. On twelve it is
**194 and 194, 388 in total**, and the extra 68 are not a rounding difference -
they are 42 batches of **size 2** in each operation's primary pass, for the
reason §3 gives. Duration is roughly unmoved even so, because a batch of 2 is
cheaper than a batch of 8: the density calibration measured 7.75 s per 2-wide
batch against 17.4 s per 8-wide, which puts the management matrix at
**~100 minutes** rather than the 93 the eight-host arithmetic gave.

**`runtime_fd_limit` asks for 10,624, not 10,496.** The memo computed
`nodes*8 + nodehosts*32` at eight nodehosts; twelve adds 128. Still an order of
magnitude under the 65536 `ecs_gate.py` sets, so nothing about the controller
changes - but it is the number that will appear in `resource_preflight.json`.

**This is a new baseline class and is deliberately not diffable against the
frozen pairs.** `artifacts/baselines/real-exact-{50,200}-c58a762a/` are
one-replica runs at 4 and 8 nodehosts. Against them `nodehost_density_plan`,
`state`, every `nodehost_id`, the fault matrix's targets and `cleanup_report`
differ *structurally*, not by drift, and a view score comparing them would carry
no information. MR-3 §10 item 1 already establishes that a multi-replica run
cannot self-calibrate in `fault_matrix` (four candidates, and a different replica
has won every time) and that `management_matrix` cannot on this fleet either. So
the two runs are compared **to each other**, at field level and as a vocabulary
comparison, and not scored against a frozen pair.

## §3 The placement defect the compile found, which no run had ever met

Every declared constraint above holds, and primaries are still not evenly placed:

| | az-a | az-b |
|---|---|---|
| primaries per nodehost | **64, 0, 0, 64, 0, 0** | 22, 22, 21, 21, 21, 21 |

Four of az-a's six nodehosts hold **zero** primaries, and two hold 64 each -
a quarter of the cluster's primaries on one host.

**The cause, read at `nodehost_density.py:_assign_within_az` and confirmed by
compiling the shape.** At one replica per shard the positional round-robin
assignment is used and is even. At r>=2 a shard has several members in one AZ, the
positional assignment would put two of them on one nodehost, and the function
falls back to walking the AZ a shard at a time: each shard's same-AZ members take
consecutive nodehosts from a running cursor, and the cursor advances by the group
size. The majority AZ's group is **3** members at r=4, and a shard's group is
ordered primary-first, so **the primary always lands at `cursor % len`, and the
cursor only ever takes values ≡ 0 (mod gcd(3, nodehosts_in_AZ))**. Six nodehosts
per AZ makes that `{0, 3}`.

The function's own docstring says the walk "keeps the per-nodehost counts within
one of each other", and it does - of *nodes*. It says nothing about roles, and
that is the gap.

**It is general, not a property of 1280.** Compiled across `nodehosts_per_az`
2 through 6 at 256x4, 60x4 and 24x1:

- at **r = 1** it never fires - the positional assignment is used and is even;
- at **r >= 2** it fires whenever an AZ's nodehost count is **divisible by 3**;
- 4 and 5 nodehosts per AZ are even; 3 and 6 are not.

**It never fired before because every fleet this product has ever had was 4
nodehosts per AZ.** MR-2 and MR-3's multi-replica runs were all at 4/AZ, and
`m4_density_calibration.md`'s own 8-host 1280 plan is even at 32 primaries each.
The twelve-host rebuild - taken to remove the memory variable, and it did - moved
the fleet onto the one nodehost count where this shows.

**Two consequences, declared rather than discovered in a diff.**

1. **The primary rolling-restart pass serialises.** One node per nodehost per
   batch means at most 2 az-a primaries can restart together, so once az-b's 128
   are exhausted the remaining 84 az-a primaries go **2 at a time for 42
   batches**. That is the whole of the 160 -> 194 difference.
2. **The fault lane's blast radius is disproportionate.** Target selection takes
   `sorted(nodehost_ids)[0]`, which is `nodehost-az-a-00` - one of the two
   64-primary hosts. So `node_host_stop`, `network_partition`,
   `minority_majority` and `split_brain_detection` each remove **64 of 256
   primaries, 25%**, where the same selection at exact-200 removes 13 of 100.
   `az_stop` pauses all of az-a and so half the primaries, which it would at any
   placement.

**Not fixed here, deliberately.** Spreading the primaries means changing the
walk, and that moves `nodehost_density_plan`, every node's `nodehost_id`, the
fault matrix's targets and the cleanup row ordering on **every** future real run,
one-replica runs included if the fallback's trigger moves. It is a change on a
real run's path and needs its own evidence, which is its own item. The operator
was told before this item ran and chose to take the run as configured, so that
M4's first numbers are the shipped behaviour at shipped knobs on the fleet as
provisioned. What this section buys is that the numbers are read correctly rather
than mistaken for a property of scale.

## §4 The reclaim proof at M4's own density, and it passed

Taken before any full-flow run, which is the sequencing
`real_execution_above_200_exception_memo.md` §4 asks for, and taken at **107
nodes per host** rather than the 2 every prior proof used.

`python3 scripts/native_cleanup_proof.py {release,abort} --fleet-id gce-m3b
--nodes-per-host 107`, on the twelve real hosts:

| | release | abort |
|---|---|---|
| residue placed | **1323** | **1323** |
| after cleanup | **0** | **0** |
| `resources_remaining` / `errors` | `[]` / `[]` | - |
| open control channels | 12 -> **0** | 12 -> 12 |

1323 is 12 hosts x (107 `valkey-server` + 1 non-Valkey process rooted in the run
tree) + 24 run paths + 3 firewall rules. The **abort** run is the one that
matters: the controller was **SIGKILLed** with 1284 processes live across twelve
hosts and a nodehost isolated, and a *fresh* process reclaimed all of it.

**One number is worth reading rather than skipping**: `terminate` reported
`pid_count: 108` against `state_pid_count: 107` on every nodehost. The
enumeration found the process `state.json` never knew about, which is item 1.4's
whole design - it terminates what `/proc` says is running out of the run's tree
and never a pid it was told about - now shown at fifty times the density it was
built at.

The twelve control channels the abort leaves are the known open item
(`distributed_cleanup_slice_map.md` §8.2): daemonised ssh masters that survive
`SIGKILL`, bounded by `ControlPersist=600`, and reported by the proof rather than
counted in its verdict.

## §5 The first attempt, and the wall it found

`gate-20260817T063318Z-b1da53f1`, **FAIL at 661.73 s**. No baseline was frozen
and none was touched.

**How far it got.** The resource preflight passed. All twelve nodehosts claimed,
the pinned bundle installed on each, **all 1280 nodes started**, and
`wait_nodes_ready` passed - `state.json` records `observed_nodes: 1280` and 1280
node records over 12 nodehosts. Cluster formation then issued CLUSTER MEET and
**152 of them were refused with `ConnectionRefusedError` in 0-1 ms**.

**Why, from the hosts rather than from the artifacts.** `dmesg` on the fleet
carries **370 x `TCP: out of memory -- consider tuning tcp_mem`**, from 06:37:12
to 06:40:23 - beginning about four minutes into the run and minutes before the
failure, on the same host the refused MEETs were addressed to.

**The arithmetic, which nobody had done and which the run's own evidence cannot
show.** The Valkey cluster bus is a **full mesh**, so a host holds
`nodes_per_host x (fleet_nodes - 1) x 2` bus sockets. That is quadratic in the
fleet and only linear in the density, which is why every density experiment to
date missed it:

| shape | bus sockets per host | at the kernel's own 8 KiB minimum |
|---|---|---|
| exact-200 on twelve hosts | 6,766 | 53 MiB |
| **1280 on twelve hosts (M4)** | **273,706** | **>= 2.09 GiB** |
| 1280 on 26 hosts | 127,900 | >= 0.98 GiB |
| 1280 on 52 hosts (the shipped-knob plan) | 63,950 | >= 0.49 GiB |

Stock `net.ipv4.tcp_mem` on an 8 GB host is `93963 125285 187926` pages - a hard
ceiling of **734 MiB**. So this shape wants at least **2.9x** what the kernel
would allow, at the smallest per-socket buffers the kernel has. Nothing at 200
nodes was ever within an order of magnitude of it.

**This is a property of the fleet shape, not a product defect**, and it is the
first thing this project has met that the 200-node cap structurally could not
have exposed: the term is quadratic in fleet size, so a 4x jump in node count is
a **16x** jump in per-host socket memory at fixed host count. It is also the
answer to a question `m4_density_calibration.md` §4 correctly flagged as
extrapolation - it measured CPU, memory and observation cadence at 4x density and
found nothing, and socket memory is the term it did not measure.

**The fix, approved before it was made** (`80d147d7`). `ecs_host_prepare.sh`
already reasoned about the mesh - its sysctl block cites "~5,000 bus sockets per
host at exact-200" and tunes `fs.file-max`, `somaxconn`, the local port range and
conntrack - and `tcp_mem` is precisely the one it did not set. It is now
`393216 786432 1048576`, or **1.5/3/4 GiB**. A ceiling and not an allocation:
these hosts hold ~1.1 GiB of valkey RSS at this density, so ~3.9 GiB stays free.
The per-socket **minima are deliberately untouched**, so no other run's socket
behaviour moves.

### §5.1 A host did not survive it, and that is where this stopped

`vslab-host-b-1` (`10.148.0.42`, instance `vslab-host-b-3mp4`) answered the
pre-run check at 06:25 with zero residue, stopped answering ssh during the run -
its 120 s reclaim timeout is the error the Gate finally reported, having replaced
the real one - and now answers **neither ssh nor ICMP, on either its internal or
its external address**. The other eleven are up with 14,100 s of uptime, so none
of them rebooted, and all eleven carry the new `tcp_mem`.

**The likeliest reading is that this is one story and not two**: TCP memory
exhaustion merely refused connections on the hosts that survived and took b-1's
network stack down entirely. It is *not confirmed* - the host cannot be inspected
- and it is recorded as a reading rather than a finding.

It cannot be recovered from here: the controller's service account carries
**no compute scopes at all** (`devstorage.read_only`, `logging.write`,
`monitoring.write`, `service.management.readonly`, `servicecontrol`,
`trace.append`), so `gcloud compute instances describe` and any reset are refused.
Resetting it is a Console action.

**A 1280-node run needs all twelve** - the plan places exactly one nodehost per
host and a native run refuses otherwise - and so does `real_ecs_200.yaml`, whose
eight nodehosts include b-1's slot. So the fleet is unusable for any real run
until b-1 returns. When it does, it needs `ecs_host_prepare.sh` re-applied (it is
the only host without the new `tcp_mem`) and a reclaim, since the failed run may
have left processes on it.

### §5.2 The error that was reported was not the error that happened

The Gate reported `pre-run reclaim could not clear every host: vslab-host-b-1:
command timed out after 120s`. The failure that actually ended the run was
cluster formation's refused MEETs; the reclaim in the failure handler then timed
out against a host that had stopped answering, and **its exception replaced the
original**. `run_verdict.json` records `runtime_start: FAIL` with the reclaim
message and `stages_not_run` for the rest, so the real cause survives only in the
command audit (152 `ConnectionRefusedError` rows) and in the hosts' `dmesg`.

Reported, not fixed - it is the same shape as §1.2 and belongs with it. Worth
knowing for any later failure at this scale: **a teardown that fails on the way
out will hide what failed on the way in.**

### §5.3 The second attempt: the fix worked, and it revealed the real wall

`gate-20260817T074001Z-0f91160f`, terminated by hand at 861.84 s. The fleet was
whole again (operator restart), b-1 prepared, **82/82** on the bring-up smoke
across all twelve hosts, and zero residue confirmed from outside.

**The `tcp_mem` fix did exactly what it was sized to do.** Measured live on one
host during formation, from outside the product:

| | |
|---|---|
| sockets on one host, peak | **223,622** (predicted 273,706 with the mesh still forming) |
| kernel TCP memory, peak | **734,335 pages = 2.80 GiB** |
| against the *old* ceiling | **3.9x** 734 MiB - so §5's diagnosis is confirmed, not inferred |
| `TCP: out of memory` messages | **0** |

**And then the host OOM-killed Valkey.** 13 `Out of memory: Killed process
(valkey-server)` on one host, node count **107 -> 82**, and the killed processes
carried **`anon-rss: 110152 kB` and `52232 kB`**.

**That is the finding, and it invalidates the memory model every M4 plan has
used.** `node_memory_limit_mb: 64` is a `maxmemory` **dataset** cap; it does not
bound the process. A node holds per-peer cluster-bus link buffers, so its RSS
grows with **fleet size**, not with its own data. Per host at 107 nodes:

    ~2.8 GiB kernel TCP  +  107 x 50-110 MB of RSS  =  8-14 GiB  against 7911 MiB

Load average was **77-84 on 2 vCPU** as well, which is the same mesh in a third
resource: gossip is O(N) per node per second, so O(N^2) per fleet.

**So 1280 nodes does not fit twelve `c4a-standard-2`, and no tuning makes it
fit.** The first attempt failed because the kernel throttled TCP; the second
failed because it did not. Both are the same wall.

This is where `m4_density_calibration.md` §4's honest caveat comes due. It
measured CPU, memory and observation cadence at 4x *density* and found nothing,
and correctly said M4 raises node count and density together. What it could not
see is that **the terms that bite are quadratic in node count and only linear in
density**, so a 4x density experiment at fixed N=200 was blind to all three of
them. The twelve-host rebuild inherited the same premise - "node count and shard
shape are the only things that move" - and it is false in the one direction that
matters.

**A host does not merely fail, it wedges.** Eight of the twelve stopped answering
ssh *and* ICMP during this run (.37 .38 .40 .41 .43 .44 .45 .46) and did not
recover; the first attempt took one host the same way. That is what the OOM killer
under this pressure does to a 2 GB-per-vCPU host, and it means an over-committed
fleet costs an operator restart rather than a failed run. `cli gate cleanup` from
`state.json` then reported 60 rows with the unreachable hosts' rows **`FAIL` with
the ssh timeout as the stated reason and `pid_count: 0` against
`state_pid_count: 107`** - which is the ownership machinery behaving correctly:
it refused to claim it had cleaned what it could not see. Re-run after the restart:
**60/60 PASS, `resources_remaining: []`.**

### §5.4 The repo's copy of `ecs_host_prepare.sh` is not what the fleet boots

Found while re-checking the hosts after the restart, and it is an operational
hazard rather than a detail. `tcp_mem` was raised on eleven hosts, they were
restarted, and afterwards **only the one host prepared by hand after its own boot
still carried it**. The reason, checked three ways: the GCE **instance metadata**
startup script contains no `tcp_mem` but does contain `ip_local_port_range`, so it
is the pre-change script; it runs at every boot; and
`/etc/sysctl.d/90-valkey-scale-lab.conf`'s mtime is **boot + 9 seconds**.

`ecs_host_preparation_report.md` says delivery is a startup script rather than an
image so that "there is still one definition". That is true, and the one
definition lives in **instance metadata** - so editing the script in the
repository changes nothing on a running fleet, and any hand-applied tuning is
silently reverted by the next boot. Making a host-preparation change stick needs
the metadata updated, which is an operator action.

## §6 What the next session inherits

1. **The Gate entry exists and has been exercised twice.**
   `real.ecs.full-flow-1280`, catalog **100**, `repository.all` **92**, M1 plan
   **91**. §1.1's two opt-in flags are required and are on it.
2. **Reclaim is proven at M4's own density** (§4): release and abort, 1323 -> 0
   on twelve real hosts, the abort after a `SIGKILL` with 1284 processes live.
   Re-run with `--nodes-per-host 107 --fleet-id gce-m3b`.
3. **The one change to try before provisioning anything is
   `cluster-link-sendbuf-limit`** (§7.1, §7.3). It is `0` - unlimited - on the
   pinned build, `_process_config_text` never sets it, and it bounds exactly the
   memory that ended both attempts. Bounding the peak to ~25 MB per node would put
   1280 nodes inside twelve 8 GB hosts. It is a new directive in every node
   config, so it moves `generated_valkey_configs_manifest` and every
   `node_configs` comparison in `runtime_start`: operator approval and its own
   evidence.
4. **If hosts are bought instead, the table is §7.3**: 1280 nodes fits **52
   hosts** of this size, is marginal at 26, and needs **24-32 GB** per host at
   twelve. The 52-host figure is the shipped-knob plan the quota refusal killed.
5. **`tcp_mem` is committed in `ecs_host_prepare.sh` but is NOT on the fleet**
   (§5.4). The GCE instance-metadata startup script rewrites
   `/etc/sysctl.d/90-valkey-scale-lab.conf` nine seconds after every boot and
   carries no `tcp_mem`, so the repo copy and the fleet have diverged. Making any
   host-preparation change stick needs the metadata updated - an operator action -
   and **that hazard applies to every future edit of that script**, not just this
   one.
6. **The declared run-time quantities in §2 are still unmeasured**: 194/194
   batches, 60 cleanup rows, canary 256, ~21,900 management rows, the fault lane's
   9/12/15, RTO at r=4, formation dwell. Only the plan-time ones are confirmed,
   plus **60 cleanup rows in four kinds**, which three separate cleanups measured
   exactly as declared.
7. **The primary-placement defect (§3) is untouched and still fires**, and it
   should be decided *before* an M4 baseline class is founded, because fixing it
   moves `nodehost_density_plan` and the fault matrix's targets.
8. **Three reporting defects, reported not fixed**, all on `run_exact_gate`'s
   path: a Gate-plan refusal dies with `AdapterOwnershipError` and writes no
   verdict (§1.2); a failing teardown's exception replaces the failure that caused
   it (§5.2); and neither process RSS nor kernel socket memory appears in any
   artifact, so §7's whole measurement had to come from outside the product (§7).
9. **The fleet is healthy and exact-200 still passes on it** -
   `gate-20260817T082549Z-ff271f54` **PASS 1685.75 s, 12/12 OK** - so nothing here
   is a fleet regression. An over-committed 1280-node attempt, though, **wedges
   hosts rather than merely failing**: one host the first time, eight the second,
   each needing an operator restart.

## §7 The mesh cost, measured instead of extrapolated

The operator asked for the coefficient rather than a guess, at scales this
hardware survives. Instrument: a sampler on the controller reading each host's
`ps -eo rss,comm` and `/proc/net/sockstat` every 20 s - **from outside the
product, because a run's evidence records neither term.** `node_memory_limit_mb`
is a `maxmemory` dataset cap, nothing samples process RSS, and kernel socket
memory appears in no artifact at all. That is the same evidence-parity gap as
"neither backend records its observation volume".

Control run: `gate-20260817T082549Z-ff271f54`, **exact-200 PASS 1685.75 s,
`run_verdict` 12/12 OK, 200 nodes**, on the twelve-host fleet.

### §7.1 What a live node says, which settles it

Asked of a primary inside the running 200-node cluster:

| | |
|---|---|
| `maxmemory` | 67108864 - the 64 MiB **dataset** cap |
| `used_memory_human` | 3.92M |
| `used_memory_rss_human` | **9.71M** - the process, 2.5x the dataset |
| `mem_cluster_links` | **426656 = 417 KiB** for 199 peers = **2.09 KiB per link** |
| **`cluster-link-sendbuf-limit`** | **0 - unlimited** |

**The last line is the finding.** Valkey has a purpose-built guard against
exactly the memory that killed the 1280-node run, and this product's node config
never sets it, so it is at the default of unbounded. `_process_config_text`
writes fourteen directives and this is not one of them.

### §7.2 The measured scaling, and it is the transient that bites

| per host | N=200, 25/host | N=1280, 107/host | ratio |
|---|---|---|---|
| bus sockets | **10,789-15,037** (predicted 9,950) | **223,622** (predicted 273,706) | ~21x |
| kernel TCP memory, peak | **2,933-14,882 pages = 11-58 MiB** | **734,335 pages = 2.80 GiB** | ~49x |
| per-node RSS, steady | **10.5-10.6 MB** | ~15 MB (the survivors) | 1.4x |
| per-node RSS, peak | **10.6-12.5 MB** | **52-110 MB** (the OOM records) | ~9x |

**The socket count is linear and the arithmetic was right to 1%** - 10,800
measured against 9,950 predicted at N=200. But the two terms that actually blew
the host are **transients, and they grow far faster than the steady state**:
kernel-queued gossip 49x and peak per-node RSS 9x, while steady-state RSS moved
1.4x.

So the earlier reading - "1280 nodes cannot fit twelve 8 GB hosts" - is **too
pessimistic about the steady state and right about the run**. Steady state at
1280 on twelve hosts is about 15 MB x 107 = 1.6 GB of RSS plus a small link
budget, which fits easily. What does not fit is cluster formation, where every
node's send buffers grow without a bound because none is set, while the kernel
simultaneously queues 2.8 GiB of gossip it was newly permitted to hold.

**And the `tcp_mem` change is part of that mechanism, which is worth stating
plainly.** Raising the ceiling from 734 MiB to 4 GiB let the kernel absorb
2.80 GiB of backlog that it had previously refused. The first attempt failed
because TCP was throttled; the second failed because it was not. Raising the
ceiling was necessary - 734 MiB cannot hold a 1280-node mesh's traffic - but on a
7911 MiB host it is not sufficient on its own, because the total is what the OOM
killer sees.

### §7.3 The provisioning table, and why it is the second-best answer

Scaling the measured transients - kernel TCP with `nodes_per_host x N`, peak RSS
per node with N alone - gives what 1280 nodes needs **at today's unbounded send
buffers**:

| hosts | nodes/host | kernel TCP peak | RSS peak | total | on 7911 MiB |
|---|---|---|---|---|---|
| 12 | 107 | 2.87 GB | ~11.8 GB | **~14.7 GB** | **no** |
| 26 | 50 | 1.34 GB | ~5.5 GB | ~6.8 GB | marginal |
| 52 | 25 | 0.67 GB | ~2.75 GB | ~3.4 GB | **yes** |

So 1280 nodes fits the **52-host shipped-knob plan** - the one the quota refusal
killed - and twelve hosts would need roughly **24-32 GB each** instead of 8.

**But buying hosts is the second-best answer.** If
`cluster-link-sendbuf-limit` bounded the peak to even 25 MB per node, twelve hosts
would need 107 x 25 MB + 2.87 GB = **5.6 GB, inside 7911 MiB**. That is one
directive in `_process_config_text`, and it is a change on every run's path - a
new directive in every node config, so it moves `generated_valkey_configs_manifest`
and every `node_configs` comparison in the `runtime_start` diff view. It needs
operator approval and its own evidence, and it is **the thing to try before
provisioning anything**.

One number recorded rather than treated as a finding: the control's 1685.75 s is
above this fleet's recent exact-200 range of 1450-1550 s. The likeliest cause is
the sampler's own ssh traffic - ten hosts every 20 s for the whole run - and it is
not established.

