# Distributed cleanup — slice map for roadmap item 1.4

Roadmap revision 5.1, M3-A item 1.4. The criterion it serves is M3's own: *"no
managed process or host resource behind"*, and the roadmap's own words for this
item are the three kinds of ownership mark — **processes, state dirs, and any
network rules the actuator creates** — plus *"the residue check covers rule-level
state"*.

Written before any code, per the project's slice method. §0 checks the item's
premises against HEAD. §1 is what a run actually leaves on a host, measured
rather than read. §2–§6 derive the five decisions the operator reserved to this
session. §9 is what has to be shown.

Session M3-A-4. HEAD at derivation: `0bf9e181`.

---

## 0. Checking the item's premises against HEAD before deriving anything

Item 1.4 arrives with four observations handed over by M3-A-3, each recorded as
an observation to derive from rather than a design. Every one was re-checked at
HEAD, and the check changed two of them.

| Inherited claim | At HEAD |
|---|---|
| `release_run` terminates by `state.json` pids, which by cleanup time are all stale | **Confirmed**, and re-measured on a live host: §1.3 |
| `reclaim_run` (host pidfiles) and `release_run` (`state.json`) disagree about what is running | **Confirmed, and both are wrong** — the pidfile is not current either: §1.4 |
| No cleanup path touches iptables | **Confirmed** and measured: the chain and both jumps survive an abort, §1.5 |
| Two host resources sit outside every ownership mark: `RESOURCE_AGENT_ROOT`, and `HostTransport.close()` has no caller | **Confirmed, and there are three** — the Load Lane's remote directory is a third, §1.6 |

And one premise nobody handed over, which this derivation found first and which
changes what the item is:

> **The residue scan cannot see a running node.** `_release_scan` matches the
> process table with `ps -eo args= | grep -F "$root"`. A live Valkey node's argv
> is not its config path — Valkey rewrites its process title — so that arm
> matches nothing, ever. Measured in §1.2.

That inverts the operation's own docstring, which says it "reads the process
table rather than trusting the termination above, which is the whole point - a
backend that reported its own `rm` as proof would be asserting the criterion
instead of measuring it." Today it asserts. This item is therefore not only
"terminate what is alive instead of what state remembers"; it is also "make the
residue check able to observe the thing it reports on".

---

## 1. What a native run leaves on a host, measured

All measurements on the two-host simulated fleet `sim-a`
(`python3 scripts/simulated_hosts.py up --fleet-id sim-a --hosts 2`), Debian 13,
`iptables v1.8.11 (nf_tables)`, against the pinned bundle
`fe1839de28d861ad` — real `valkey-server` processes, started from a config
generated exactly as `_process_config_text` generates one (`daemonize yes`,
`dir <data_dir>`, `pidfile <data_dir>/valkey.pid`).

### 1.1 The surfaces

| # | What | Path or name | Run-scoped? | Removed today? |
|---|---|---|---|---|
| 1 | the run's state tree | `/tmp/valkey-scale-lab/<run_id>/` | yes | yes, both paths |
| 2 | node processes | *(marked only by their cwd — §1.2)* | see §1.2 | **no** — signalled by stale pid, never observed |
| 3 | the run bundle | `/tmp/vslab-bundle-<run_id>-<nodehost_id>/` | yes | yes, both paths |
| 4 | the actuator's firewall rules | chain `VSLAB-<NODEHOST-ID>` + `INPUT`/`OUTPUT` jumps | **no** | **no** — only `rejoin_nodehost` |
| 5 | the resource agent | `/tmp/vslab-resource-agent/<nodehost_id>/`, plus a package copy | **no** | **no** |
| 6 | the Load Lane's working directory | `/tmp/vslab-load-lane/<label>/` | **no** | **no** |
| 7 | the control channel | one `sshd` session per host, `ControlPersist=600` | n/a | **no** |
| 8 | the pinned bundle install | `/opt/valkey-scale-lab/bundles/<digest>/` | deliberately not | no, **and correctly so** — §2.4 |

Rows 1 and 3 are the whole of what the current implementation handles. Rows 2,
4, 5, 6 and 7 are this item's.

### 1.2 A live node is invisible to the residue scan

Two nodes started under `/tmp/valkey-scale-lab/run-alpha`, and the host's own
process table:

```
  126 valkey-server 0.0.0.0:31000 [cluster]
  139 valkey-server 0.0.0.0:31001 [cluster]
```

The config path is gone: Valkey rewrites its process title after reading the
configuration file. Running `_release_scan`'s script verbatim against that host,
with both nodes live and the run root present:

```
rc 0
  > state
```

One row, for the directory. **Zero rows for two running nodes of that very run.**
The `state` arm works because `[ -e "$root" ]` is a filesystem test; the process
arm is dead code against a real Valkey.

Two further properties of that script, both measured:

- **It does not report itself**, but only by accident. The scan's own
  `sh -c` command line does contain the run root, and `ps` does list it — but the
  script text also contains the word `grep`, so the `grep -v grep` filter
  removes it. Nothing states that; a reword of the script would reintroduce it.
- **It is not prefix-safe.** With a second run at
  `/tmp/valkey-scale-lab/run-alpha-2`, a scan for `run-alpha` reported
  `run-alpha-2`'s process as its own residue. `grep -F "$root"` matches any run
  id having this one's as a prefix.

What *does* survive is the process's working directory, because the generated
config sets `dir <data_dir>` and Valkey chdirs there:

```
235  cwd=/tmp/valkey-scale-lab/run-alpha/node-a  exe=/opt/.../bin/valkey-server
248  cwd=/tmp/valkey-scale-lab/run-alpha/node-b  exe=/opt/.../bin/valkey-server
261  cwd=/tmp/valkey-scale-lab/run-alpha-2/node-z  exe=/opt/.../bin/valkey-server
```

A `/proc` walk keyed on cwd, scoped prefix-safely with a trailing separator,
returned exactly the two nodes of `run-alpha` and excluded `run-alpha-2`'s — and
kept returning the right pair after a restart gave `node-a` a new pid.

### 1.3 The pids in state are stale, re-measured

`state.json` is last written before the management matrix; the rolling restart
and the fault matrix then replace every process. Measured directly rather than
inferred: `node-a`'s pidfile read `126` at start, and `185` after one
stop/start — while `state.json` would still hold `126`. This reproduces on one
node what M3-A-3 measured across both frozen exact-50 baselines as 50 pids and
zero overlap.

### 1.4 The pidfile is not the answer either

`reclaim_run` kills by reading each `<run_root>/*/valkey.pid`, which the
handover called "current". It is more current than `state.json` and still not
sound, in two measured ways:

- **A node that was SIGKILLed and never restarted leaves its pidfile behind,
  holding a dead pid.** `kill -KILL` on that number is not a no-op on a busy
  host — it is a signal to whatever process now holds that pid. Cleanup must not
  be a source of collateral kills.
- **A node shut down cleanly removes its pidfile.** Measured: after
  `SHUTDOWN NOSAVE`, `valkey.pid` is gone and `nodes.conf`, `valkey.conf` and
  `valkey.log` remain. So pidfile presence is neither necessary nor sufficient
  for "this node is running".

A third measurement, incidental but pointed: a cleanup script of the form
`pkill -f valkey-server; rm -rf …` killed **its own shell** before reaching the
`rm`, because the shell's command line contains the pattern. Pattern-matching
the process table is the wrong instrument for this job in three separate ways.

### 1.5 Rule-level state survives an abort, and the chain name cannot be the mark

The actuator's own script was run on a host and then nothing else, which is what
an abort in the middle of a partition looks like:

```
-A INPUT -j VSLAB-AZ-A-00
-A OUTPUT -j VSLAB-AZ-A-00
-N VSLAB-AZ-A-00
```

All three persist. Neither `reclaim_run` nor `release_run` contains the string
`iptables`, so a subsequent run on that host inherits a DROP rule.

The chain name carries no run id, and **it cannot**: measured, `iptables`
accepts a chain name of 28 characters and refuses 29 —

```
  28 chars: rc=0
  29 chars: chain name `VVV…' too long (must be under 29 chars)
```

— while a run id (`cluster_lifecycle-local_full_flow-20260811`) is **42**. This
is the same shape of constraint as the 104-byte `ControlPath` limit M3-A-2 found:
a platform limit that decides a design, discoverable only by trying it.

What *can* carry it, measured on the same host: an iptables rule **comment**.

```
-A INPUT -m comment --comment "vslab-run=cluster_lifecycle-local_full_flow-20260811" -j VSLAB-TEST
```

The full 42-character run id fits (the module's limit is 256), the rule is
enumerable by `iptables -S` and removable by the same match.

### 1.6 Three host resources outside every ownership mark, not two

The handover named `RESOURCE_AGENT_ROOT` and `HostTransport.close()`. Reading the
producers at HEAD found a third:

- **`/tmp/vslab-resource-agent/`** holds a copy of the whole `valkey_scale_lab`
  package plus one directory per sampler. `sampler_id` is the **`nodehost_id`**
  (`_deploy_resource_samplers` groups by it), e.g. `az-a-00` — which names no
  run. Nothing removes any of it.
- **`/tmp/vslab-load-lane/<label>/`** — `observability/load.py` sets
  `remote_dir_root = "/tmp/vslab-load-lane"`, and `NativeLoadLaneHost.command`
  creates it on the host. It holds memtier's JSON and HDR output. It names no
  run and nothing removes it. **This one is new here**; it was in neither the
  handover nor the seam-completion map.
- **The control channel.** Measured: a process that uses the transport and exits
  without `close()` leaves **one `sshd: root@notty` session alive on each host**
  and an orphaned control-socket directory on the controller. `close()` exists
  and works — its docstring already calls a surviving master "a resource the run
  owns and did not release" — and **nothing in the product calls it**.

---

## 2. What a run's ownership mark on a host actually is

This is the first decision the operator reserved. Item 1.2 chose a run-scoped
path. The question is whether one mark serves all three kinds.

### 2.1 State directories: the path is the mark, exactly

`[ -e "$root" ]` is an exact test on an exact path. Nothing to derive.

### 2.2 Processes: the mark is the working directory, not the command line

§1.2 settles it. The path *is* still the mark — a node process is ours because it
is running out of our tree — but the evidence for it is `/proc/<pid>/cwd`, not
`ps`. Two consequences:

- The comparison is `"$cwd/" = "$root"/*`, with the trailing separator, or the
  prefix collision of §1.2 is reintroduced.
- `/proc/<pid>/exe` is read too, and **recorded, not used as a filter**. It says
  what was terminated (`…/bin/valkey-server`, or `/usr/bin/python3` for the
  resource agent). Filtering on it would silently leave behind exactly the
  process a reader most wants to hear about — something unexpected, running out
  of the run's own tree.

The run root is created by this run and nothing else writes there; that is
already `reclaim_run`'s own stated premise ("Anything holding a file open under
the run root is this run's, by construction"). So cwd-inside-the-run-root **is**
ownership, and the row records `exe` so the claim is auditable rather than bare.

There is a TOCTOU window between reading a pid's cwd and signalling it. It is
closed as far as it can be by doing both inside one on-host script, and it is
bounded by the re-scan afterwards, which is what the report is actually built
on.

### 2.3 Network rules: the chain name is a handle, the comment is the mark

§1.5 settles it: 28 bytes against 42 means the name cannot carry the run id, and
a comment can. So the chain keeps its readable, nodehost-derived name — it is a
handle, the way `container_name` is — and **the two jump rules that activate it
carry `vslab-run=<run_id>`**, which is what makes them enumerable, attributable
and removable by a run that did not create them.

An alternative was considered and rejected: encoding a truncated hash of the run
id in the chain name (`VSLAB-<8 hex>-<nodehost>`), which does fit in 28 bytes. It
was rejected because it makes the host's firewall unreadable to an operator
looking at it directly, for no capability the comment does not already give.

### 2.4 The principle this settles, and the one exception

The native backend's module docstring already states the intended rule:

> **The run's ownership mark on a host is a path.** Everything a run puts on a
> host lives under `/tmp/valkey-scale-lab/<run_id>` … or is named after the run.

§1.6 shows that claim was false in two places when it was written. This item
makes it true in the one place it is entitled to, and reports the other.

**The resource agent moves under the run root**, package copy and all.
`RESOURCE_AGENT_ROOT` is a constant of `native_backend.py`, chosen by this
backend for itself — the seam says nothing about where a sampler's files live,
because `resource_sampler` returns an opaque object. Moving it needs no
removal logic at all (removing the run root removes it) and makes the agent
visible to the cwd-based process scan for free, which is what matters when a run
aborts with a sampler still running.

**The Load Lane's working directory does not move, and §8.4 records why.** Its
location is not the backend's to choose: `LoadLaneHost`'s protocol docstring says
in as many words that `remote_dir` "is the lane's own choice of where its output
goes, not the backend's". That was decided with an argument in item 0.5, and
`LoadLane._output_prefix` bakes the path into memtier's own argv, so a backend
that quietly relocated it would create one directory and have memtier write to
another. Overturning a seam decision is not something this item may do in
passing.

The line this draws is worth stating, because it is the one that decides both:
**what the backend chose, the backend may move; what the lane chose, only the
lane may move.**

**The one exception, kept deliberately:** the pinned bundle install at
`/opt/valkey-scale-lab/bundles/<digest>/`. It is fleet-scoped and
content-addressed by design, and item 1.2 argued that explicitly ("two runs of
the same build share one install … re-shipping 14 MB per host per run proves
nothing"). It is a fact about the fleet, not residue of a run, and this item does
not remove it. Stated here because a residue check that ignores something must
say why.

The rule this leaves is one sentence: **everything a run puts on a host is under
its run root, except firewall rules, which carry the run id in a comment.**

---

## 3. What teardown terminates

The second reserved decision. Answer: **what is alive and provably ours, read
from the host at the moment of teardown** — never `state.json`'s pids (§1.3),
never the pidfile (§1.4).

The sequence, per host, mirroring the Docker path's row vocabulary so that
item 1.5's equivalence diff has something to compare:

| Row | What it does | Status rule |
|---|---|---|
| `terminate` | enumerate by cwd, `TERM` each | `PASS`, or `SKIPPED_WITH_REASON` if there was nothing to signal |
| `verify_exit` | re-enumerate for up to 30s; `KILL` whatever remains, then re-enumerate | `PASS` if empty, else `SKIPPED_WITH_REASON` naming the survivors |
| `remove_rules` | drop this run's jumps and chains, found by comment | `PASS`/`FAIL` |
| `remove` | `rm -rf` the run root and the bundle dir | `PASS`/`FAIL` |
| `scan` | re-read the host: processes, tree, rules | `PASS`/`FAIL` on whether the scan itself ran |

`TERM` before `KILL` because a Valkey node that exits on `TERM` removes its own
pidfile and closes its files; the escalation exists because teardown has to
finish. The pids come from the enumeration in the same script, never from state.

State's pids do not disappear from the record: the `terminate` row keeps
`pid_count`, and gains `state_pid_count` beside it, because the difference
between the two is the evidence for §1.3 and a reader should be able to see it in
the artifact rather than in this document.

---

## 4. Whether the residue scan can assert rather than measure

The third reserved decision. **It cannot**, and the reason is now stronger than
the one the handover carried.

The handover's reason was structural: Docker's `docker rm -f` is the backstop
that actually stops a fleet, and a backend with no container to remove has no
such backstop, so its termination is best-effort signalling and only a fresh read
of the host can close the criterion.

§1.2 adds an observed reason: the scan that exists *already* asserts, by
reporting zero processes whatever is running. A cleanup path whose measurement
instrument cannot see its subject reports `PASS` for the same reason
`cleanup_scenario` reported `PASS` for a native fleet before item 0.5 — it asked
a question that could only have one answer. That is precisely the defect item 0.5
existed to prevent, in the operation item 0.5 created.

**A rule-level residue check** is, concretely: after removal, ask the host for
every `INPUT`/`OUTPUT` jump carrying this run's comment, and every chain those
jumps target. Anything returned is a `resources_remaining` row of type
`nodehost_firewall_rule`. It is the same shape as the process and state rows —
ask the host, report what it says.

---

## 5. One notion of "what is running", two callers

The fourth reserved decision. **Yes, they should share it**, and §1.3/§1.4 make
the argument: they disagree today, and neither is right, so unifying them is not
a tidiness change but the fix to both.

What is shared is the enumeration — one on-host script, one prefix-safe cwd walk,
one definition of "ours". What stays different is everything the seam already
says is different:

- `reclaim_run` runs before any state exists, works from `run_id` alone, reaches
  hosts through the **manifest**, returns `None`, and escalates straight to
  `KILL` — it is not the same run's processes, it is a previous attempt's, and
  there is nothing to shut down gracefully.
- `release_run` works from `state`, reaches hosts through the **control
  endpoints state recorded**, reports rows, and does `TERM` then `KILL`.

Both also remove this run's firewall rules; `reclaim_run` did not remove them at
all before, which §1.5 shows is how an aborted run poisons the next one.

---

## 6. What "abort" means concretely enough to stage

The fifth reserved decision, and the acceptance's own words: *"abort a
simulated-host run mid-flight, run reclaim, zero managed residue"*.

The worst moment is not a random one. It is **after `isolate_nodehost` has
installed rules and before `rejoin_nodehost` removes them**, with node processes
running and a resource sampler alive. Any earlier and there are no rules to
strand; any later and the actuator has already undone itself.

So "abort" is staged as: place the full residue set on the simulated hosts
through the backend's own operations, then **`SIGKILL` the controller process**
— no exception handler, no `finally`, no teardown — and run `reclaim_run` from a
fresh process, which is exactly what the next run would do.

`SIGKILL` rather than `SIGINT` deliberately: `SIGINT` would run Python's
finalizers and could be argued to have been given a chance to clean up.

**This is not the item 1.5 bring-up smoke.** It drives no cluster, forms no
topology, runs no scenario and no Gate step, and exercises the seam's operations
only as far as is needed to *place residue*. The smoke that drives the twenty-four
operations as a sequence remains the first rung of item 1.5, by the operator's
decision of 2026-08-11.

---

## 7. What this item changes outside itself

**Nothing on a Docker run's path.** Every change is inside
`src/valkey_scale_lab/runtime/native_backend.py`, which a Docker run does not
import a name from. Specifically not changed: `teardown.py`, `lifecycle.py`,
`docker_runtime.py`, `node_backend.py`'s protocol, any schema, any verdict rule.

**The seam stays at twenty-four operations.** Nothing here needs a
twenty-fifth. Closing the transport is not a new operation: the backend
lazily *creates* the transport when none was injected, so releasing it belongs to
the object that made it, at the end of the operation the seam already declares
terminal. A backend does not close a transport it was handed — the injector owns
that one.

The prediction this makes for the acceptance runs is therefore specific and
falsifiable: the `cleanup` diff view stays **2/2**, and every other stage keeps
item 1.3's marks. The prompt for this session warned that item 1.4 is *expected*
to change `cleanup_report`, and that the delta should be declared in advance.
The declaration is: **there is no delta, because `cleanup_report` on the Docker
path is assembled by `teardown.py` from `DockerNodeBackend.release_run`, and
neither is touched.** A delta of any shape is a finding.

---

## 8. Findings this derivation produced and does not fix

### 8.1 Two runs of the same scenario on the same day share a run id

`_run_id` is `f"{capability_id}-{scenario}-{RUN_DATE}"`. Two runs of one scenario
on one date have not merely colliding but *identical* ownership marks, on both
backends: Docker's labels carry the same string. So `reclaim_run` correctly
destroying "a previous attempt" and destroying "a concurrent run" are the same
act. This is inherited, not introduced, and it is a property of the run-id scheme
rather than of cleanup. Recorded because §2's whole subject is the ownership
mark, and this is its real boundary.

### 8.2 The run-path backend's own transport is still not closed

§7 closes the transport the *teardown* backend created. `_execute_runtime` builds
a separate backend for the run itself, whose masters stay open until the process
exits and then for `ControlPersist=600` beyond it. Fixing that needs a disposal
point above the seam that does not exist — the lifecycle has no "the run is
over, release the backend" moment, and inventing one is a seam change with its
own argument to make. Measured cost of leaving it: one `sshd` session per host,
self-expiring in 10 minutes. Reported, not fixed.

### 8.4 The Load Lane's remote directory is residue this item cannot reach

`/tmp/vslab-load-lane/<label>/` (§1.6) is a host resource with no ownership mark
and no remover. It is left as it is, and the residue scan does **not** report it,
because a scan must not claim what it cannot attribute: nothing on the host says
which run that directory belongs to, and two runs can share a host.

Two fixes exist and each is refused here for its own reason:

- *The backend rewrites the path under the run root.* Refused: it contradicts
  `LoadLaneHost`'s stated contract, and `_output_prefix` has already written the
  unrewritten path into memtier's argv, so the lane would write outside the
  directory the backend created.
- *The lane makes its own root run-scoped* — it already takes a `run_scope`, so
  `f"{root}/{run_scope}/{label}"` is available to it. Refused here because it
  changes memtier's argv on **both** backends, and that argv is recorded
  evidence in every frozen baseline. It is a correct fix and it is an artifact
  change needing its own commit and its own diff, not a rider on this one.

It belongs to item 1.5, which is where a native full-flow run — and therefore the
first native Load Lane — first exists.

### 8.3 No fault path checks ownership

Unchanged and deliberately untouched. The operator accepted this loss on
2026-08-10 and decided nothing in M1 changes for it. Adding the run-id comment to
the actuator's rules in §2.3 is an ownership *mark*, not an ownership *check*: it
records whose the rule is, and does not make `isolate_nodehost` refuse a host
that is not this run's. Naming the difference because the two are easy to
conflate and only one of them is this item's.

---

## 9. Proof — what has to be shown

Per CLAUDE.md's per-slice acceptance bar, read against an item whose changes
reach no Docker run.

1. `./gate suite repository.all` green at its count, with this item's Test
   registered once and the two Gate contract numbers moved with it.
2. Hermetic proof against a fake transport of each derived behaviour: the cwd
   enumeration and its prefix safety, `TERM` then `KILL`, the rule removal by
   comment, the residue rows for all three kinds, and the refusals.
3. **On the simulated fleet, the measurements this map's claims rest on, re-run
   against the implementation** — a live node found by cwd where `ps` cannot see
   it; a restarted node still found; a second run's node not claimed.
4. **Zero residue on a passing simulated teardown**: place the full residue set,
   call `release_run`, and confirm from the hosts — no process, no tree, no rule,
   no session.
5. **The abort proof of §6**: place the residue set, `SIGKILL` the controller,
   confirm from the hosts that all five kinds are present, then `reclaim_run`
   from a fresh process and confirm all five are gone.
6. Because §7 predicts no Docker-path change, the real-run evidence is the
   prediction itself: two consecutive real exact-50 with item 1.3's marks and the
   `cleanup` view at 2/2. Any other shape falsifies §7 and is a finding, not a
   re-baselining.
