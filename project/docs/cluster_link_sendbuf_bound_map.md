# M4-4: bounding the cluster-bus send buffers

`m4_first_1280_run_map.md` §7.1 found the knob that was switched off and named it
"the thing to try before provisioning anything". This item turns it on, proves it
changes nothing at exact-200, and then takes it to 1280.

**Read §1 before §2.** The map's own budget table recommends a value that would
free every cluster link on its first queued ping, and the reason it does is that
the table is memory arithmetic and the constraint that binds first is a message
size. That correction is this item's most transferable result and it was found by
compiling the pinned build's structs, not by running anything.

## §1 The cap's floor is a whole message, not a memory budget

`m4_first_1280_run_map.md` §7.1 budgets the knob purely by multiplying a per-link
cap by the link count:

| per-link cap | buffer bound per node | 107 nodes + 2.87 GiB kernel | on 7911 MiB |
|---|---|---|---|
| 64 KiB | 82 MB | ~9.9 GB | no |
| 16 KiB | 20 MB | ~6.1 GB | tight |
| **8 KiB** | 10 MB | ~5.0 GB | **yes** |

Read on its own that says: pick 8 KiB. **It is the one value in the table that
cannot work**, and nothing in a memory budget can see why.

**What the limit actually does, read in the pinned build's source rather than
inferred.** `cluster_legacy.c`'s `freeClusterLinkOnBufferLimitReached` is called
from `clusterCron`, and when a link's `send_msg_queue_mem` exceeds the limit it
**frees the link** and increments
`stat_cluster_links_buffer_limit_exceeded`. `send_msg_queue_mem` is
`sizeof(listNode) + totlen` summed over the queued messages. So the cap is not a
back-pressure valve that trims a queue: it is a threshold that discards the whole
link, and a cap below one message discards it on the first ping that ever queues.

**So the floor is the largest single cluster-bus message, and that grows with the
fleet.** `clusterSendPing` sizes a packet as

    estlen = sizeof(clusterMsg) - sizeof(union clusterMsgData)
           + sizeof(clusterMsgDataGossip) * (wanted + pfail_wanted)
    wanted = floor(dictSize(nodes) * cluster-message-gossip-perc / 100), min 3
    estlen = max(estlen, sizeof(clusterMsg))

with `cluster-message-gossip-perc` a hidden config defaulting to **10**. The two
struct sizes were **compiled** against the same declarations rather than counted
by hand, because padding makes hand-counting unreliable:

| | |
|---|---|
| `sizeof(clusterMsgDataGossip)` | **104** bytes |
| `sizeof(clusterMsg)` | **4352** bytes |
| header, `sizeof(clusterMsg) - sizeof(union clusterMsgData)` | **2256** bytes |
| **one PING at N=200** | `2256 + 104*20` = **4352** bytes (the floor binds) = 4.25 KiB |
| **one PING at N=1280** | `2256 + 104*128` = **15568** bytes = **15.20 KiB** |

before ping extensions, which add a few hundred bytes more.

**8 KiB is therefore 0.53 of a single message at 1280 nodes.** Every link that
queued one ping would be freed at the next `clusterCron`, ten times a second,
across 273,706 links, during exactly the convergence the cap exists to protect.

**The value taken is 32768 — 32 KiB.** It is 2.05 of the largest message this
product can generate and 7.5 of the smallest, so it cannot fire on a link merely
holding one queued ping at any scale a bounded exception admits, and it clips the
top of the measured no-cap distribution, which is the part that killed the host.

**And the honest consequence, stated before any run rather than after.** At 1280
on twelve 8 GB hosts the cap that *fits* and the cap that is *safe* barely
overlap. Fitting wants the per-node buffer bound near 20 KiB × 2558 links ≈
50 MB; staying clear of the message size wants ≥ 32 KiB. §5 is what the run said
about that, and it is the whole reason this needed a run rather than a table.

## §2 Declared in advance: what a no-op at exact-200 must look like

A new directive in every node config moves generated artifacts, and which ones is
a prediction that can be wrong. Declared before the runs, from reading the
producers:

| surface | predicted |
|---|---|
| `node_configs` (`runtime_start` view) | **all 200 files, one added line, nothing else** |
| `generated_valkey_configs_manifest` | **unchanged** |
| every other `runtime_start` view | unchanged |
| `cluster_form`, `management_matrix`, `fault_matrix`, `cleanup` | unchanged |
| `total_cluster_links_buffer_limit_exceeded` in run evidence | **0 everywhere** |
| `mem_cluster_links` per node | **426,656 bytes**, as at an unlimited cap |

**`generated_valkey_configs_manifest` is the one worth declaring**, because the
handover predicted it would move and it does not.
`_write_generated_valkey_configs_manifest` does not embed the config text; it
records `io_threads_line_present`, `maxmemory_line_present`,
`cluster_node_timeout_line_present` and their values, and a directive it does not
name changes none of them.

**Inherited and not this item's**: on the twelve-host fleet `runtime_start`
already scores 6/7 against `real-exact-200-c58a762a` because
`nodehost_density_plan` carries the rebuild's four address-shaped paths, and
`fault_matrix` already scores 4/6 because the baselines predate the 2026-08-13
failover work. So the predicted candidate score is **5/7, 5/5, 7/8, 4/6, 2/2**,
with `management_matrix` 7/8 being what the frozen pair scores against itself.

## §3 The `tcp_mem` hazard is real and bit before any run did

`m4_first_1280_run_map.md` §5.4 records that the GCE instance-metadata startup
script rewrites `/etc/sysctl.d/90-valkey-scale-lab.conf` nine seconds after every
boot and carries no `tcp_mem`, so the committed fix is not on the fleet. Checked
at the start of this item rather than assumed, by reading
`/proc/sys/net/ipv4/tcp_mem` off all twelve hosts:

- **eleven of twelve carried stock `93963 125285 187926`** — a 734 MiB ceiling;
- **one, `10.148.0.42`, carried `393216 786432 1048576`** — and it is the host
  that went down during the first 1280 attempt and was prepared by hand *after*
  its own boot.

All twelve had rebooted about seventy minutes earlier. So the hazard is not
theoretical and is not confined to the host that failed: **any host that reboots
loses the tuning**, and an over-committed 1280 attempt reboots hosts. Re-applied
to all twelve with the committed script (idempotent, `rc=0` on each) and the
value re-read off each host afterwards.

**This has to be re-checked before every 1280 attempt**, because the failure mode
of the previous attempt is a reboot, and a reboot is what removes it.

## §4 Proof at exact-200, and every prediction it tested

Two consecutive real exact-200 on the twelve-host fleet at `39d44012`, from the
in-VPC controller: **PASS 1603.85 s** (`gate-20260817T093439Z-46d76999`) and
**PASS 1419.83 s** (`gate-20260817T100203Z-0b8c3b4a`).

Both: `run_verdict` PASS with **12/12 checks OK** and `tool_errors` empty, 200 of
200 nodes, fault lane **9 scenarios / 12 command rows / 15 windows** with nine
`REAL_PASS`, `cleanup_actions` **40 rows in four kinds** with
`resources_remaining` and `cleanup_errors` empty, **200/200 journals**, and the
string `ERROR` in no artifact of either. RTO **45.97 s** and **50.48 s**. All
twelve hosts asked over ssh from outside the product afterwards: zero
`valkey-server`, zero `vslab` rules, zero `VSLAB` chains, zero run trees, zero
bundles - only the known empty `/tmp/vslab-load-lane` that
`m3_acceptance_registration_map.md` §5.1 already records.

**The scores.** Calibrated first: the frozen pair against itself gives 7/7, 5/5,
7/8, 6/6, 2/2, reproducing its own `BASELINE.md`. Both candidates then score
**`runtime_start` 5/7, `cluster_form` 5/5, `management_matrix` 7/8,
`fault_matrix` 4/6, `cleanup` 2/2** against `real-exact-200-c58a762a` - exactly
§2's prediction. And **candidate against candidate is 7/7, 5/5, 8/8, 6/6, 2/2 -
identical in every view of every stage**, which is the isolating proof and is
better than the frozen pair manages on `management_matrix`.

**The declared delta held to the line.** Reduced through the diff view's *own*
normalisation rather than by raw `diff`, all 200 `node_configs` differ and the
whole difference across all 200 files is one added line:

    +cluster-link-sendbuf-limit 32768

Nothing removed, nothing else added, in any file. (A raw `diff` also shows
`cluster-announce-ip` moving from `10.148.0.9-16` to `10.148.0.36-45`; that is
the twelve-host rebuild, and the view rewrites addresses to `<nodehost:ID>`, so
it is not part of this delta.)

**One inherited prediction was wrong and is corrected.**
`generated_valkey_configs_manifest` does **not** move - the diff reports it SAME
in both runs. `_write_generated_valkey_configs_manifest` embeds no config text;
it records `io_threads_line_present`, `maxmemory_line_present`,
`cluster_node_timeout_line_present` and their values, and a directive it does not
name changes none of them. The second differing `runtime_start` view is
`nodehost_density_plan`, reduced to paths: **exactly four differ and no path
appears or disappears** - `fleet_manifest_sha256` and the three host addresses -
which is verbatim the twelve-host rebuild's own declared delta.

**The cap never fired at exact-200, and that is stated as a limitation rather
than a result.** `total_cluster_links_buffer_limit_exceeded` is **0 in all 2,950
readings the two runs' own artifacts carry** (1,483 and 1,467), and 0 in 463 of
464 rows of the outside sampler. `mem_cluster_links` is **426,656 bytes per
node**, byte-identical to what §7.1 measured at an unlimited cap. So the exact-200
proof establishes that the directive is harmless **where it never binds** - 32 KiB
is 7.5 messages at 200 nodes - and it cannot establish anything about where it
does.

**The one non-zero row is worth reading.** 25 freed links on one host at
10:00:56Z, **27 seconds before candidate 1 ended** - a teardown window, where a
node still alive holds links to peers that have just been killed, those queues
back up, and the link is discarded. That is the mechanism doing exactly its job,
on a run that had already passed. It is invisible in the artifacts because the
in-evidence readings come from the fault lane, which is over by then.

## §5 The 1280-node run: the cap is not the lever, and the fleet is

`gate-20260817T102918Z-1473cc96`, at `39d44012`, **aborted from outside at about
3 minutes 15 seconds** by the watchdog of §5.1 - not by the product, and not by
the OOM killer, which had not yet fired anywhere when the abort was issued.

**How far it got, and it is further than either M4-3 attempt.** Resource
preflight **PASS** with `runtime_fd_limit` `required_min` **10,624**, exactly as
M4-3 §2 declared. **1280 of 1280 node configs carry the directive.** All twelve
nodehosts claimed, the pinned bundle installed on each, and **all 1280 nodes
started** - 106-107 per host, counted on the hosts. Cluster formation began and
issued **684 `cluster_meet`, every one PASS**.

**The `tcp_mem` fix held, and this is the first clean read of it.** M4-3's first
attempt died on 370 kernel `TCP: out of memory` messages and 152 refused MEETs.
Here: **zero `TCP: out of memory` on every host**, and zero refused MEETs in 684.
So §3's re-application worked and that failure mode is closed.

**What replaced it.** Two samples 45 s apart, all twelve hosts, from outside the
product:

| per host | t ≈ 2m20s | t ≈ 3m05s | at exact-200 |
|---|---|---|---|
| nodes | 106-107 | 106-107 | 25 |
| valkey RSS, total | 1326-1432 MB | **1701-2652 MB** | 242-247 MB |
| valkey RSS, largest node | 23-33 MB | **52-67 MB** | 10.5 MB |
| bus sockets | 65,640-112,561 | **147,406-177,635** | 10,049 |
| kernel TCP | 1.6-2.6 GB | **2.1-3.1 GB** | 0-1 MB |
| load average (2 vCPU) | 9-18 | **38-59** | 0.0-1.7 |

`MemAvailable` on the worst host went **3569 MB → 271 MB in one 45 s interval**,
and the socket count was still only **54-65 % of the full mesh's 273,706**.

**The cap did clip the top, and it was nowhere near enough.** Largest per-node
RSS reached 52-67 MB against M4-3's uncapped 52-110 MB, so the ceiling is
working. But at the same moment the **kernel** held 2.1-3.1 GB - a term this knob
does not touch, already at 77 % of the raised 4 GiB `tcp_mem` ceiling, with 40 %
of the mesh still to establish.

**And the risk §7.1 named is not hypothetical: it is severe.** Over only **four
sampled nodes per host**, `total_cluster_links_buffer_limit_exceeded` reached:

| host | .36 | .37 | .38 | .39 | .40 | .41 | .42 | .43 | .44 | .45 | .46 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| links freed | 1 | 2,390 | 12,632 | 3,253 | **33,094** | **34,567** | 19,197 | 13,321 | 16,862 | 18,370 | 17,742 |
| `mem_cluster_links`, largest node | 2.0 MB | 12.1 MB | **31.5 MB** | 12.5 MB | 8.8 MB | 8.5 MB | 6.2 MB | 8.2 MB | 5.7 MB | 7.7 MB | 6.3 MB |

Four nodes of 107. Scaled to the host that is roughly 800,000 link frees, and the
cluster bus is thrashing rather than converging. Against 426 KB per node at
exact-200, `mem_cluster_links` is **5x to 70x higher** *with the cap in place*.

**So both of the cap's failure modes are present at 32 KiB at the same time**,
and that is what settles it. The queues are being discarded in their tens of
thousands *and* memory still exhausts the host. Lowering the cap makes the first
worse; raising it makes the second worse; and the measured average occupancy of a
capped link is already ~12.6 KB across 2558 links, so the demand the mesh is
expressing is real rather than a tuning artefact.

**Conclusion: no value of `cluster-link-sendbuf-limit` fits 1280 nodes on twelve
`c4a-standard-2`.** §7.1's hope - "bounding the peak to ~25 MB per node would put
1280 nodes inside twelve 8 GB hosts" - is measured false: per-node link memory
reached 31.5 MB *under the cap* while the kernel simultaneously held 2-3 GB, and
the two together exhaust a 7911 MiB host before the mesh is two-thirds built.
**`m4_first_1280_run_map.md` §7.3's provisioning table is the answer** - 52 hosts
at shipped knobs, marginal at 26 - and this item's contribution is that it is now
the answer on evidence rather than by elimination.

The directive stays, on its own merits: it is a real bound on a real unbounded
resource, it is proven a no-op at every scale the fleet actually runs, and
without it the 1280 attempt's largest node reached 110 MB instead of 67 MB.

### §5.1 Aborting a 1280-node run does not relieve the fleet, and this cost a host

The watchdog killed the controller at `MemAvailable` 271 MB with **zero OOM kills
anywhere**. That was not sufficient, and the reason is worth writing down:
**killing the controller does not stop the fleet.** The cluster bus is
peer-to-peer, so 1280 unmanaged nodes carried on trying to form a mesh, and the
heaviest link-freeing in the table above was sampled *after* the controller was
already dead. In the minutes that followed, four hosts OOM-killed 4-6 processes
each and **`10.148.0.47` stopped answering ssh and ICMP**, the same signature as
the eight hosts M4-3 §5.3 lost.

So the abort turned eight wedged hosts into one, which is worth having, but the
correct sequence is **kill the controller and immediately reclaim**, not kill and
observe. A reclaim was issued and eleven of twelve went to zero.

**The reclaim behaved exactly as designed on a partly-unreachable fleet**, which
is the third independent confirmation of M4-3 §2's declared row count:
`cleanup_actions` **60 rows in four kinds**, with the unreachable host's three
rows `FAIL` carrying a stated reason - "The process enumeration could not be run
on this host" - and `resources_remaining` **empty**, because the machinery
refuses to claim it cleaned what it could not see.

**`10.148.0.47` needs an operator Console restart**, and when it returns it needs
`ecs_host_prepare.sh` re-applied (§3) and a reclaim. The other eleven are clean
and still carry the raised `tcp_mem`.

**One reporting note, and it is mine rather than the product's.** A run killed
with `SIGKILL` from outside writes no `run_verdict.json`, so this attempt's
outcome lives in its `command_audit`, its `state.json` and the outside samplers.
That is the same *shape* as map §1.2 and §5.2 but not the same defect: those are
about the product mis-reporting its own failures, and this is an external kill
with no failure handler to run.

## §6 A third way `repository.all` is non-deterministic, found and not fixed

`repository.all` is **92/92 on the Mac** at this commit. On the controller it is
**89/92**, and only two of the three are the documented ones -
`product.integration.docker_runtime_contract` for the absent daemon, and
`product.scenarios.execution_axis_contract`, whose finding is a `Pxx` match inside
a run's base64 HDR histogram because `SCAN_ROOTS` includes `artifacts`.

The third is **`product.unit.nodehost_density::test_resource_preflight_records_
density_checks`**, and it is new to this record rather than new to the code.
**Measured at the parent commit `b61f13b6` in a throwaway worktree: it fails there
identically**, so it is not this item's.

The cause is worth writing down. The test monkeypatches the docker, cleanup and
port checks and then asserts `run_resource_preflight("scale_100.yaml")` is `PASS`,
which makes its verdict depend on the **memory** of whatever machine runs it: 100
nodes x 64 MiB needs 6400 MB, and the check reported
`host_available_memory_mb: 3128` with `reason: required memory exceeds host
available memory`. At that moment the OS reported **14,224 MB available** and only
4,085 MB free - the controller was holding **10.4 GB of page cache** from the
day's runs. So the product's "available" is free memory rather than
`MemAvailable`, and a supposedly hermetic unit test fails on a machine that has
recently done I/O.

Two separate things a later session may want, and neither is taken here: whether
the preflight should read `MemAvailable` (a semantic change to a safety check, so
the operator's call), and whether a hermetic test should assert `PASS` on a
host-dependent budget at all. What is established is the same lesson MR-3 §9.4
recorded for `execution_axis_contract`: **`repository.all` is not deterministic on
a machine that has taken real runs**, and the honest response is to read which
test failed rather than to chase the count.
