# Roadmap item 1.6: the ladder on the operator's real fleet

M3-B-1. The same ladder as `simulated_ladder_slice_map.md`, on eight real GCE
hosts instead of eight containers sharing a laptop's kernel, driven from a
controller inside the same VPC.

Host preparation is not this item's and is not repeated here; read
`ecs_host_preparation_report.md` for what a fleet host is and how the eight were
built. This document is what happened when the product was pointed at them.

**The headline.** Two consecutive native exact-50 and two native exact-200
through the Gate on real hardware, all four PASS with 12/12 steps,
equivalence-diffed against the frozen Docker baselines and frozen as the native
baselines M3 acceptance will use. **The delta against the frozen exact-50
baseline is the same 111 field paths as the simulated fleet's, path for path,
with nothing added and nothing missing** - the strongest statement this ladder
can make, and it is a comparison of two delta sets rather than of one delta set
against prose.

Five defects were found, all of them by running rather than by reading, and four
of them only reachable from a controller that is not a development laptop.

---

## 1. What the controller had to become, and why it matters to the result

The gate runs from `vslab-controller`, a `c4-standard-4` in the same subnet, not
from the workstation. The host preparation report §6.6 measured why: 5.1 ms per
command in-VPC against 110-116 ms from a laptop, and the rolling restart's own
budget is 71 ms and 61 ms. A baseline frozen from a laptop would encode that
laptop.

Two things about the controller are part of the environment a real baseline
records, and both are stated here so they are reproducible rather than
incidental:

- **`ulimit -n 65536` before the gate.** `runtime_fd_limit` requires
  `max(1024, nodes*8 + nodehosts*32)`, which is 1856 at exact-200, and Debian's
  default soft limit is 1024. This is the one preflight check that is *right* to
  ask about the controller: the controller really does hold O(N) persistent RESP
  connections plus one ssh master per host. The environment was wrong, not the
  check.
- **No Docker daemon, and none is wanted.** The controller is x86_64 and the
  fleet is arm64, so a daemon there could never run this product's image.
  `./gate suite repository.all` therefore reports **91/92** on the controller -
  the missing one is `product.integration.docker_runtime_contract`, whose 152
  tests pass with one skipped for the absent CLI. The authoritative **92/92** is
  taken on the Mac, and every commit in this item has both numbers.

## 2. The five defects, and what each one says

### 2.1 A test that only tested its contract on macOS

`test_the_control_socket_path_is_held_under_the_platform_limit` asserted the
104-byte `sockaddr_un` limit using pytest's `tmp_path` unmodified, on a comment
saying it "is already 127 bytes on this platform". True under `/var/folders` on
macOS; about 60 bytes under `/tmp` on Linux, where the transport correctly did
not raise and the test correctly failed. The contract is right and unchanged;
the test now builds the run-artifacts nesting the first transport spike actually
failed on, and asserts that shape breaches the limit before asking the transport
to refuse it.

**What it says:** the first time this repository's tests ran anywhere but the
development machine, one of them was measuring the machine.

### 2.2 The preflight demanded a Docker daemon of a run that uses none

The first native exact-50 was refused in 0.2 s. `docker_available` and
`previous_cleanup_state` were the only two failures of fifteen, and both shell
out to the local Docker CLI.

The registry has declared `requires_local_docker_daemon` per backend since
`39e31b1a` - that is where the Gate's own daemon check moved when backend
selection became data - and the preflight simply never asked it. It does now,
from the backend the caller already resolved; `gates/real.py` and `lifecycle.py`
both had `backend_id` in hand and were passing nothing.

Both rows stay in the artifact as `SKIPPED_WITH_REASON` with a reason naming the
backend. **Operator decision, reported before the change was made**, because it
widens `can_run` from `all(status == "PASS")` to accept that one status. Dropping
the rows instead would have left two preflights differing by a missing name with
nothing saying why, which is the shape of fabricated evidence this product
forbids. `_check` still produces `PASS` or `FAIL` and nothing else, so nothing
else can reach the widened test.

A caller that names no backend keeps the check it always had, deliberately:
`cli preflight` and the scale ladder ask about a machine rather than about a run.

### 2.3 The memory budget asked the controller about memory spent on eight other machines

At exact-200 it compared the run's whole 12800 MB requirement against the
controller's 12117 MB available and refused, while the same artifact's own
`projected_nodehost_memory_mb` said 1600 MB per nodehost against 7.9 GiB on each
placed host. At exact-50 it passed only because 3200 MB happens to be small. It
was asking the wrong machine at both scales; one of them noticed.

**Operator decision, also reported first:** each placed nodehost is compared
against the host it is placed on, read from that host with the same
`MemAvailable` the local arm reads. A host that will not answer fails the check
rather than being assumed to fit - fail-closed, the way `create_network` refuses
a fleet it cannot see. One transport for the whole check, closed before
returning. A run that names no fleet keeps the controller comparison exactly as
it was, and a test measures that no fleet is contacted for one.

### 2.4 A reason the §12.1 validator could not see

This one is the best of the five, because the run that found it was otherwise
perfect. The first native exact-50 ran all 860 s, formed the cluster, completed
both matrices, cleaned up to zero residue on four hosts, scored 12 of 12 steps
PASS and `run_verdict` 12/12 OK - and was then refused:

```
real gate source evidence is invalid: runtime/resource_preflight.json
.checks[2] status SKIPPED_WITH_REASON requires a non-empty reason
```

`_validate_missing_taxonomy` walks every object of every raw source and requires
a non-empty `reason` **beside** any status in `MISSING_STATUSES`. §2.2 had put it
inside `details`, where the walk cannot see it, so a preflight that recorded
exactly why it skipped a check read as one that had not said. The taxonomy was
working; the new row was not speaking to it.

**What it says:** the missing-evidence contract is enforced, not decorative, and
a new `SKIPPED_WITH_REASON` producer has one place to put its reason.

### 2.5 The preflight had no fleet to read, two frames below a caller holding one

§2.3's fix passed its standalone check and then refused the first real exact-200
in 2.7 s, with `compared_against: "controller"`. The reason is a property of the
gate path worth knowing on its own:

> **`_prepare_runtime` preflights the profile's canonical template, not the
> configuration the run uses.** For exact-200 that is
> `templates/configs/scale_200.yaml`, which names no fleet and never has.

The fleet is now passed in by the caller, which holds the run's configuration,
and the caller's wins over the document's. Nothing else about which document is
preflighted changes: widening that would move `config_path` in every run's
evidence and would evaluate `_is_exact_200_bounded_exception` against a
different document, which is a safety guard and not this change's business.

The first attempt at that commit added the keyword to four call sites instead of
two - `_process_runtime_state` happens to end in the same two lines - and the
**92/92 suite did not notice**, because no hermetic test reaches that call site
with its real signature. Three real runs did, in ten seconds each, with zero
residue left on any host.

## 3. Auth, kernel and conntrack reality at fleet width

Measured through the product's own `MultiplexedSshTransport`, on all eight hosts.
The host preparation report's §9 listed these as what two hosts could not answer.

**All eight hosts are identical**, which is the check that makes per-host
preparation as safe as an image:

| | |
|---|---|
| sshd `MaxSessions` / `MaxStartups` | 64 / 30:50:120 |
| `nofile` in a session | 1048576, `file-max` 2097152 |
| process limit / `threads-max` | 28562 / 57125 |
| `somaxconn` / `tcp_max_syn_backlog` | 4096 / 8192 |
| `ip_local_port_range` | 10240-65535 |
| THP / `vm.overcommit_memory` | never / 1 |
| `/tmp` | ext4 (not tmpfs) |
| machine | 2 vCPU, 7.7 GiB, arm64 |

**Auth fails the four ways it should and hangs in none of them.** Each case was
given its own transport, because a multiplexed session over an existing master
never re-authenticates - the first attempt at this measured "wrong key → rc 0"
and was measuring the mux, not the auth:

| shape | time | outcome |
|---|---|---|
| unrouted VPC address | 5.01 s | rc 255, "Connection timed out" |
| reachable host, closed port | 0.00 s | rc 255, "Connection refused" |
| reachable host, no key offered | 0.06 s | rc 255, "Permission denied (publickey)" |
| reachable host, host key not known | 0.01 s | rc 255, "Host key verification failed" |

The last is a positive control for the roadmap item 1.0 defect:
`StrictHostKeyChecking=yes` refuses a host it has not been told about.

**conntrack is not consumed by this product.** The module is loaded on every
host with `nf_conntrack_max` 1048576, and `nf_conntrack_count` reads **0 before,
during and after a partition** installed by the backend's own
`isolate_nodehost`. The actuator's rules are filter-table rules carrying
`-m comment` and no state match, so they start no tracking. Rules 0 → 6 → 0
across isolate and rejoin. At exact-200 the fleet holds a 200-node full mesh and
the table stays empty.

### 3.1 Transport-failure classification across a VPC, which the roadmap kept open

Answered, and the answer is that the transport does not classify these at all:

- **`put`/`get` (scp) raise `TransportError` for every failure**, including an
  unreachable host, and the evidence paths convert that to `CollectionError`.
  Correct.
- **`run` (ssh) returns every failure as a `CommandResult` with rc 255** - a host
  that cannot be reached at all included. `run`'s own docstring says
  `TransportError` is for "the transport failing to carry the command at all",
  and that is exactly this case.

**Reported, not fixed**, because changing it would change what
`is_collection_failure` sees for a whole class of failures, which is a verdict
contract. It is currently harmless at every site that can be named: the fault
actuator is *required* by §9.1 to keep a failure to act as a result;
`clock_exchanges` checks `returncode != 0` explicitly and raises
`CollectionError`; the ordinary lifecycle sites raise `NativeRuntimeError` either
way. What it costs is that a caller cannot distinguish "the host said no" from
"there is no host", and the only thing making that safe is that no site relies on
the distinction. ssh's 255 is genuinely ambiguous - a remote command can exit 255
too - so any fix has to read stderr, and that is its own change with its own
evidence.

## 4. Transport overhead on the real fleet

The roadmap asks for this to be re-measured, because M3-A-2 chose multiplexed SSH
on simulated numbers. Measured from the in-VPC controller through
`MultiplexedSshTransport`, 200 commands per width, round-robin across all eight
hosts:

| parallelism | median | p90 | max | throughput |
|---|---|---|---|---|
| 1 | **5.3 ms** | 5.8 | 7.2 | 192/s |
| **8** (the run's own `_bounded_parallel`) | **8.6 ms** | 12.5 | 16.4 | 871/s |
| 32 | 26.9 ms | 43.5 | 85.7 | 963/s |

Per-host at width 8: **7.4-8.9 ms median**, spread 1.5 ms across two zones.
Eight masters open in 3.75 s. Against the rolling restart's own 71 ms and 61 ms,
the transport is under budget by a factor of seven at the parallelism a run
actually uses, and still under it at four times that. **The transport decision
point is closed: multiplexed SSH stands, on real-network numbers.**

Note the shape at width 32: throughput saturates near 960/s while latency rises
proportionally, which is the controller's four vCPUs rather than sshd - the
sessions are queued client-side, not refused. `MaxSessions 64` is never reached.

### 4.1 A claim from the simulated ladder that this corrects

`simulated_ladder_slice_map.md` §15.2 reports "the seam's own transport costs
25.7 s across eight hosts against `docker exec`'s 276.6 s on one", taken from the
two runs' `runtime_command` rows. **Those rows are not the seam's transport on
the native backend.** Measured in this item's runs: every row in a native run's
command audit is `valkey-cli`-shaped - the controller's RESP path - and **not one
ssh command is recorded**, because `NativeMultiEcsBackend._run` does not call the
recorder and only `run_cluster_admin` records explicitly. On the Docker backend
the same `runtime_command` kind *is* the backend's own `docker` invocations.

So §15.2 compared two different populations. The comparison it reports is still
a real one - controller-to-node work on each backend - but it is not the seam's
transport cost, and a native run's audit cannot answer that question at all.
Hence the direct measurement above.

**Reported, not fixed.** Recording the native backend's ssh calls would add
thousands of rows to every native run's audit and change a raw source's volume
and content; it belongs to whoever owns the audit contract, with its own
evidence. It is worth doing: the Docker path's runtime commands are auditable
after the fact and the native path's are not, which is an evidence-parity gap
between two backends that are meant to be comparable.

## 5. Clock offsets, and the first real skew this product has seen

Recorded as a bound, never against a threshold. Read through the product's own
`host_clock` on all eight, and again inside every run's `host_evidence.json` at
both ends of the run:

| when | offsets | bound | round trip |
|---|---|---|---|
| direct, all eight | **-4.15 to -4.83 ms** | ±6.5-7.0 ms | 13-14 ms |
| exact-50 run A, four hosts, at start | +1.79 to +2.40 ms | ±6.5-7.0 ms | 13-14 ms |
| exact-50 run B, four hosts, at start | +3.53 to +4.04 ms | ±6.5-7.0 ms | 13-14 ms |

Zero is inside the bound on every host in every reading. Two things are visible
that neither the simulated fleet nor a laptop controller could show:

- **The eight hosts agree with each other to within 0.7 ms.** Chrony holds them
  there. The common term - -4.5 ms in one reading, +2.1 ms in another, +3.8 ms in
  a third - moves together on all hosts, so it is the *controller's* clock
  drifting relative to the fleet, not the fleet disagreeing.
- **The common term is a large fraction of the bound.** At -4.8 ms against ±6.5
  it is three quarters of the way to the edge. A threshold calibrated on the
  simulated fleet (+4.7 to +7.9 ms inside 15-21 ms) or on a laptop (+39 ms inside
  ±60 ms) would have been wrong here in both directions. This is the clearest
  vindication yet of recording a bound.

## 6. The deltas, declared before the runs

Everything `simulated_ladder_slice_map.md` §6.2 and §6.3 declares still applies,
because the only configuration difference between a simulated and a real run is
`runtime.host_inventory_path`. One further delta was declared in advance for the
real fleet, before any run was taken:

> **`LocalResourceSampler.host_sample()` populates 2 of 6 cgroup fields on a VM**
> - `cpu_usage_usec` and `cpu_throttled_usec` yes, `memory_current_bytes`,
> `memory_max_bytes`, `oom_count` and `oom_kill_count` no - because a container
> is a delegated child cgroup while a VM's sampler reads the root one. Every
> simulated baseline carries six.

**Measured, and better than declared.** The four absent fields are not null: each
carries a `MISSING` object with its own JSON-path and reason, e.g.
`$.resource_documents[0].samples[0].cgroup.memory_current_bytes was unavailable
or not applicable for this artifact.` The product represents the absence with a
reason, which is the contract. It moves **no diffed view** - no resource-document
path appears in the delta set of §7 - so it is a change in evidence content
rather than in the equivalence result, and it is declared here so it is not
discovered later and read as drift.

---

## 7. The result

Every run below was taken at `c58a762a`, from the in-VPC controller, with
`ulimit -n 65536`, against fleet `gce-m3b` (manifest sha256 `9ee2c4dc…`).

| run | config | outcome | steps | run_verdict |
|---|---|---|---|---|
| exact-200 run-1 | `real_ecs_200` | **PASS 1462.73 s**, first attempt | 12/12 | 12/12 OK |
| exact-50 run-1 | `real_ecs_50` | **PASS 861.46 s** | 12/12 | 12/12 OK |
| exact-50 run-2 | `real_ecs_50` | **PASS 869.18 s** | 12/12 | 12/12 OK |
| exact-200 run-2 | `real_ecs_200` | **PASS 1454.44 s** | 12/12 | 12/12 OK |

The second exact-200 was taken so the baseline could be calibrated against
itself; item 1.6 asks for one, and a single-run baseline cannot answer the
question CLAUDE.md requires of one.

200 of 200 and 50 of 50 nodes, no `ERROR` in any artifact of any of them, and
zero residue on all eight hosts after each - checked in `cleanup_report` *and*
from outside the product over ssh.

Two earlier exact-50 at the preceding HEAD (**PASS 882.73 s** and **862.06 s**)
are not part of the frozen set but scored identically in every view; they are
what found §2.5.

### 7.1 The equivalence diff, and the strongest statement this ladder can make

Calibrated first at this HEAD, the two frozen Docker exact-50 baseline runs
against each other: **7/7, 5/5, 8/8, 6/6, 2/2**, every comparable view identical.
The exact-200 baseline calibrates 6/6 and 4/4 with one view unavailable in each,
because both of its runs fail downstream.

Both real exact-50 runs score **`runtime_start` 5/7, `cluster_form` 5/5,
`management_matrix` 6/8, `fault_matrix` 4/6, `cleanup` 1/2** - the same marks the
accepted simulated pair scored - and are **identical to each other in every view
and every field**.

Scores are a summary, so the comparison was made on the delta itself. Reducing
each view to the set of generalised JSON paths that differ:

| | paths |
|---|---|
| frozen Docker exact-50 → simulated native exact-50 | 111 |
| frozen Docker exact-50 → **real native exact-50** | **111** |
| set difference, either direction | **none** |

**The real fleet's delta against the frozen Docker baseline is the simulated
fleet's delta, path for path.** Not "the same size", not "the same views" - the
same 111 paths. At exact-200 the same comparison over the two stages that
baseline covers gives **22 paths on both, again with no difference**, and no path
appears at 200 that did not appear at 50.

Every path is in the declared set - `simulated_ladder_slice_map.md` §6.2's two
inherited Docker deltas, §6.3's native ones, and §14.3-§14.5's corrections. The
`management_command_log` length is 1592 → 1606, which is §6.2's +14
`cluster_migrate_keys` rows exactly, and `command_log_refs` 270 → 277 with
`command_ids` 1030 → 1044 to match.

### 7.2 The one path that comes and goes, and why it is not growth

The two frozen runs give 111 paths; runs A and B give **112**. The extra one is

```
management_sequence  result.operations[].workload_impact.errors_observed_during_operation
```

which is **§14.7's field**, already named there as one the frozen baselines agree
on by coincidence. Measured across six runs at the two rolling-restart positions:

| run | those two values |
|---|---|
| frozen Docker run-1, run-2 | `T, T` |
| real exact-50 (earlier HEAD) | `T, T` |
| real exact-50 (earlier HEAD) | `F, F` |
| real exact-50 A | `F, T` |
| real exact-50 B | `F, F` |

So the path is present when the run happens to disagree with the baseline and
absent when it happens to agree. It is a per-run workload observation, not a
delta that grew - and it is the **fifth** instance of CLAUDE.md's warning that two
runs agreeing is not proof a field is deterministic.

### 7.3 The invariants, on real hardware

| | exact-50 A | exact-50 B | exact-200 |
|---|---|---|---|
| fault scenarios / command rows / windows | **9 / 12 / 15** | **9 / 12 / 15** | **9 / 12** |
| fault verdicts | 9 × `REAL_PASS` | 9 × `REAL_PASS` | 9 × `REAL_PASS` |
| `cleanup` rows | 20 in 4 kinds | 20 in 4 kinds | **40 in 4 kinds** |
| residual scan `found` | 0 × 4 | 0 × 4 | 0 × 8 |
| primary-kill RTO | **49.54 s** | **48.54 s** | **52.55 s**, **51.57 s** |
| node journals | 50, 7.99 MB | 50, 7.93 MB | **200, 88.28 MB** |
| whole run's artifacts | 48 MB | 48 MB | **227 MB** |

(The exact-200 column is run-1; run-2 matches it in every row above.)

The three scale-fixed fault numbers now hold across **two runtimes, two
environments and three scales**; the diff tool's own `stage_shape` reporter says
`scenarios=9 command_rows=12 windows=15 status=PASS` on both sides at exact-50.
`cleanup` is §6.3's five rows per nodehost at four and at eight.

RTO at exact-50 is inside the 45-50 s band; at exact-200, **52.55 s and 51.57 s**
sit inside the 47.6-53.8 s exact-200 spread. That is worth stating explicitly, because
`simulated_ladder_slice_map.md` §15.6 recorded a simulated exact-200 at 41.28 s -
the first below either band - and said a second below 45 s would make it a
spread. **It did not happen**: both real exact-200 runs are squarely back in the
historical range, so 41.28 s stays a single simulated outlier.

Evidence volume is again a property of the cluster rather than the runtime or the
environment: 7.93-7.99 MB of journals for 50 real nodes against 7.9 MB simulated
and 8.0 MB under Docker; 88.28 MB for 200 real nodes against 86.8 MB simulated.
Per node that is 160 KB at 50 and 441 KB at 200, still climbing with peer count.

## 8. Formation dwell, and the 240 s window

`CONVERGENCE_NO_PROGRESS_SECONDS = 240.0`, `CONVERGENCE_TIMEOUT_SECONDS = 1800.0`
(`observability/cluster.py:57`, `:61`). Item 1.6 asks for the statistics and for
the window to be re-argued if they move.

| environment | exact-50 `cluster_form` | exact-200 `cluster_form` |
|---|---|---|
| **real fleet** | **47.4 s, 53.4 s** (and 50.4, 61.6 at the earlier HEAD) | **52.0 s, 72.1 s** |
| simulated native | 19.7, 35.7, 48.0, 52.1 s | 60.9 s |
| Docker | 43.0, 56.6, 57.8, 72.1, 122.6 s | 59.4, 77.7, 88.1, 104.9 s |
| Docker, formation-only runs | - | 83.1, 102.5, 137.0, 152.0, 205.8 s |

**They moved down, which is the direction that leaves the bound safe.** The real
exact-200 forms in **52.0 s and 52.3 s - the lowest 200-node formations ever
measured here**,
below the whole Docker spread and below the simulated native run, and **22 % of
the 240 s window**.

`convergence_bound_map.md` sized the window on the *longest single dwell*, 83.1 s
at 200 nodes, and total formation bounds every single dwell from above: a run
whose whole `cluster_form` is 72.1 s cannot contain a dwell longer than 72.1 s.
So the real fleet's longest possible dwell is at most 87 % of the number the
window was sized on, and its measured worst case is well inside it.

The spread between the two runs - 52.0 s against 72.1 s, on identical hardware
one run apart - is itself worth recording: formation dwell is dispersed on a real
network as it is under Docker, and a single number would have misrepresented it.
That is also why the window is bounded on *lack of progress* rather than on total
formation.

**The window is not re-argued and should not be.** Nothing here suggests
narrowing it: the roadmap's own reason for the bound is that convergence is a
serialised queue whose length and per-item dwell both grow with node count, and
200 nodes on a real network is the largest real measurement available. It must
still be re-measured before 500 nodes, which `convergence_bound_map.md` already
says.

The other real-network number worth keeping: the stability window and the
matrices dominate a run's wall clock, not formation. At exact-200 the split is
`runtime_start` 4.6 s, `cluster_form` 52.0 s, `management_matrix` 931.2 s,
`fault_matrix` 279.6 s, `cleanup` 9.7 s - and in run-2, 4.6 / 72.1 / 930.2 /
299.6 / 8.9 s.

## 9. Ownership and reclaim on real hosts

Two proofs, and the second is the one the roadmap asks for literally.

**The harness proof**, `native_cleanup_proof.py`, which places real residue with
the backend's own operations and then asks the hosts over its own ssh:

| mode | managed residue | control channels |
|---|---|---|
| `release` | **43 → 0** | 12 → 4 |
| `abort` (controller SIGKILLed mid-flight, a host isolated) | **43 → 0** | 12 → 12 |
| `stubborn` (a process that traps TERM) | **43 → 0** | 12 → 12 |

On eight real hosts: 3 processes per nodehost against 2 in `state.json` - the gap
item 1.4 exists to close - the actuator's chain and both jumps, the run tree and
the run bundle, all gone in every mode. Reproduce with
`python3 scripts/native_cleanup_proof.py release|abort|stubborn --fleet-id gce-m3b`.

The `abort` and `stubborn` rows leave their control channels open, which is item
1.4 map §8.2's known and unclosed item: an aborted controller's ssh masters are
daemonised, not children, and nothing afterwards can tell whose they are. Bounded
by `ControlPersist=600`. Reported, not part of the verdict.

**The real-run proof.** A real 50-node gate run was started, allowed to form its
cluster and get into the management matrix, and then its controller process tree
was `SIGKILL`ed:

```
live valkey processes before the abort: 50
after the abort   a-1 runtrees=1 bundles=1 valkey=13   a-2 … valkey=12
                  b-1 runtrees=1 bundles=1 valkey=13   b-2 … valkey=12
reclaim           cli gate cleanup --state <the aborted run's state.json>
                  status PASS, 20 rows in 4 kinds, scan found 0 ×4, no errors
after the reclaim every host: runtrees=0 bundles=0 valkey=0 rules=0 chains=0
```

Zero managed process, state and network-rule residue, from the product's own
teardown path, on a run that never reached it - and checked from outside the
product rather than from the report that claims it.

## 9a. The health-gate escalation, measured in a third environment

`simulated_ladder_slice_map.md` §14.6 found that the rolling restart's health
gate escalates to a whole-fleet round on native runs and not on Docker runs at
exact-50, and §16 concluded, after excluding workload, that **the runtime** is
the variable. The real fleet is a third environment and refines both.

First, a correction to how it is counted. §14.6 counts
`sample_scope: all_nodes_diagnostic`. That is one shape the escalation takes and
not the only one: on the real fleet a gate retries once and probes all 50 nodes
(`full_probe_count` 0 → 50, `node_command_count` 12 → 124, `retry_count` 0 → 1)
while keeping the *representative* scope label. Counting only the diagnostic
label reports zero for every real run, which is how this was nearly written up
backwards. `full_probe_count > 0` is the signal that the whole fleet was asked,
whatever the round is called, and both are reported below.

| environment | scale | gates | whole-fleet rounds | of which `all_nodes_diagnostic` | retries |
|---|---|---|---|---|---|
| Docker, laptop (frozen baseline ×2) | 50 | 44 | **2, 2** | 0, 0 | 0, 0 |
| simulated native, heavy workload ×2 | 50 | 44 | 7, 9 | **3, 5** | 2, 2 |
| simulated native, light workload | 50 | 44 | 8 | **5** | 1 |
| **real native ×4** | 50 | 44 | **3, 4, 6, 6** | **0, 0, 0, 0** | 1, 2, 4, 4 |
| simulated native | 200 | 80 | 2 | 0 | 0 |
| **real native ×2** | 200 | 80 | **2, 2** | **0, 0** | 0, 0 |

Two whole-fleet rounds with no retries is the floor every non-escalating run
has; anything above it is an escalation.

**What survives:** at exact-50 the native runtime reaches for the whole fleet
where Docker does not - 3 to 6 rounds against a floor of 2, in four real runs and
three simulated ones - and at exact-200 no runtime in any environment escalates
at all. §14.6's finding and §16.2's inversion with scale both hold on real
hardware.

**What is new:** *how far* it escalates is environmental. On simulated hosts 3 to
5 rounds per run went all the way to `all_nodes_diagnostic`; **on real hosts none
ever did**, in six runs. The retry succeeds inside the representative scope and
the diagnostic round is never needed. So the failure §16.3 was worried about -
one whole-fleet `CLUSTER NODES` round costing a network - is the rarer half of
the behaviour, and it did not occur once on the fleet where it would cost most.

**What this says about §16.1.** It concluded "the runtime is what distinguishes
an escalating run from a non-escalating one". That is right about the retry and
wrong about the severity, and the confound it could not see is the harness: eight
"hosts" sharing one laptop's CPU is a plausible reason a representative round
finds something unhealthy, and it is the one variable the real fleet removes.
Not proven - CPU contention on the simulated hosts was not measured - so it is
recorded as the surviving candidate rather than as the answer. §16.2's question,
why it inverts with scale, is untouched and still open.

## 9b. What was frozen

Two baselines, both from runs at `c58a762a`, both on the controller under
`project/artifacts/baselines/`:

| | runs | size | self-calibration |
|---|---|---|---|
| `real-exact-50-c58a762a` | PASS 861.46 s, 869.18 s | 97 MB | 7/7, 5/5, **6/8**, 6/6, 2/2 |
| `real-exact-200-c58a762a` | PASS 1462.73 s, 1454.44 s | 457 MB | 7/7, 5/5, **7/8**, 6/6, 2/2 |

They live on the controller and not on the workstation, deliberately: the
workstation cannot reach the fleet, so every diff against them will be run where
they are. Each carries a `BASELINE.md` recording the commit, the fleet and its
manifest digest, the hosts, the invocation including `ulimit -n 65536`, and the
calibration limits below.

**`management_matrix` does not self-calibrate and cannot.** Two fields in it are
genuine per-run observations - §14.6's retry record inside `stdout_tail`, and
§14.7's `errors_observed_during_operation` - so a candidate must be judged on the
other views and on the field-level delta rather than on that view's score. This
is recorded rather than normalised away: `PROBE_COUNT_FIELDS` already excludes
those counters structurally, the exclusion does not descend into a serialised
summary, and §14.6 keeps it that way on purpose because it is the only place the
escalation is visible.

**One normalisation gap was real and is fixed** (`b1c1a507`). `cleanup`
self-calibrated at 1/2 because `_cleanup_scrub` reimplements `scrub`'s dict
descent and had lost its `pid` rule, and because item 1.4 gave the native residue
rows a process record - `pid`, `cwd`, `exe` - where the Docker rows had a bare
pid list. The list is now sorted and its pids scrubbed, and it is *not* reduced
to a count, because `cwd` is item 1.4's ownership mark and `exe` exists so a
reader hears about something unexpected running out of the run's own tree.
Proven by seeding rather than by calibrating: an unexpected `cwd`, a residual
scan reporting `found: 1`, and a process missing from a terminate row are each
reported, while the same processes in a different order stay quiet. The frozen
Docker baselines still calibrate 7/7, 5/5, 8/8, 6/6, 2/2.

## 10. What this item leaves open, and to whom

Nothing below was fixed here, and each says who it belongs to.

1. **`run` does not classify a transport failure** (§3.1). Every ssh failure -
   including "there is no host" - arrives as `CommandResult` rc 255, while
   `put`/`get` raise `TransportError` for the same conditions. Harmless at every
   site that can be named today, and a change there would move what
   `is_collection_failure` sees for a whole class of failures, which is a verdict
   contract. Whoever takes it needs stderr parsing and its own evidence.
2. **A native run's command audit records no ssh at all** (§4.1). Every row is
   the RESP path; `NativeMultiEcsBackend._run` does not call the recorder and only
   `run_cluster_admin` records explicitly, where the Docker backend records every
   `docker` invocation under the same `runtime_command` kind. This is an
   evidence-parity gap between two backends meant to be comparable, and it makes
   `simulated_ladder_slice_map.md` §15.2's transport comparison a comparison of
   two different populations.
3. **`_prepare_runtime` preflights the profile's template, not the run's
   configuration** (§2.5). Worked around rather than resolved: the fleet is passed
   in, and everything else about that call is unchanged. Whether the preflight
   should validate the document the run uses is a real question with a safety
   guard attached (`_is_exact_200_bounded_exception` reads that document), and it
   is the operator's rather than a session's.
4. **The 92/92 suite does not reach `_process_runtime_state`'s call site with its
   real signature** (§2.5). A wrong keyword there passed the whole hermetic suite
   and was caught by three real runs in ten seconds each.
5. **Carried forward untouched**: the aborted controller's ssh masters (1.4 map
   §8.2, measured again here in §9), the resource-to-timeline monotonic
   correlation (1.3 map §10.1), a failing run collecting no journals and writing
   no lifecycle timeline (1.3 map §10.2), the absent fault-path ownership check
   (accepted 2026-08-10), the missing `signalled` count in a run's own evidence,
   `SamplerSpec`'s duplication of `_AgentSamplerSpec`, `_state_nodehost` dropping
   `remote_bundle_dir`, and why the health-gate escalation inverts with scale
   (`simulated_ladder_slice_map.md` §16.2).

### 10.1 What item 1.7 inherits

- **The real baselines are frozen on the controller**, not on the workstation -
  see §11 - because that is where a native acceptance run can be taken. The
  workstation cannot reach the fleet.
- **`real.ecs.*` is still absent from `catalog.json`.** The two configurations
  `real_ecs_50.yaml` and `real_ecs_200.yaml` are what those entries will name,
  and the invocation they must reproduce is
  `ulimit -n 65536; ./gate test real.local.full-flow --param nodes=N --param
  config=templates/configs/real_ecs_N.yaml` from the controller.
- **Registering a Test moves three numbers**, unchanged from the M3-B handover:
  `repository.all` 92, catalog 96, M1 plan 91, the last two pinned by
  `verification/tests/test_contracts.py:79` and `:344`. Read them; do not run
  `./gate milestone m1` to check a count.
- **M3 has a registered check on 1 of its 6 criteria.** This item produced the
  evidence for four of them - the native runtime, exact-50, exact-200, evidence
  and cleanup - but attached no check to any criterion, because that is 1.7's.
