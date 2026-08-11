# The simulated development ladder — roadmap item 1.5 slice map

Session M3-A-5. HEAD at derivation: `e9e08812`.

Roadmap item 1.5 reads: *"On simulated hosts: two-host exact-30 smoke (smallest
scale reaching `management_matrix`/`fault_matrix`) → native exact-50,
equivalence-diffed against the frozen Docker exact-50 baseline with the
project's own diff tooling, vocabulary deltas declared in advance → native
exact-200."* The operator added a **native bring-up smoke** at its front on
2026-08-11: two simulated hosts, the backend driven directly, no Gate run, no
cluster, no scenario.

Read `distributed_cleanup_slice_map.md` §8 and `native_backend_slice_map.md` §3,
§7 and §11 first; this map derives from them and does not repeat them.

---

## 0. Checking the item's premises against HEAD before deriving anything

Four of the seven facts handed over at `e9e08812` were re-checked before any of
them was used. Two of them are **wrong**, and both were wrong in the direction
that would have been discovered as a run-time failure rather than as a plan.

### 0.1 The fleet arithmetic is wrong by a factor of two at both small rungs

The handover states: *"`max_logical_nodes_per_nodehost` defaults to 25 and a
native run places exactly one nodehost per host, so exact-30 and exact-50 need
**2 hosts**, and exact-200 needs 8."*

The density is not the binding term at small scale. `build_nodehost_density_plan`
computes, per availability zone:

```python
requested_for_az = max(min_per_az, ceil(count / max_per_nodehost))
```

where `min_per_az = max(nodehosts_per_az, min_fault_domains)` and
`config/valkey_scale_lab_global.yaml` sets **`nodehosts_per_az: 2`**. At
exact-50 each zone holds 25 nodes, so `ceil(25/25) = 1` and the floor of 2 wins.

Measured by compiling the plan at HEAD (`nodehosts_per_az` at its global
default, `azs: [az-a, az-b]`):

| scale | nodes per az | `ceil(n/25)` | nodehosts | **hosts required** | handover said |
|---|---|---|---|---|---|
| exact-30 | 15 | 1 | 4 | **4** | 2 |
| exact-50 | 25 | 1 | 4 | **4** | 2 |
| exact-200 | 100 | 4 | 8 | **8** | 8 ✓ |

The Docker baseline corroborates it from the other side: its `cleanup_report`
carries 21 rows in six kinds — `terminate` ×4, `verify_exit` ×4,
`verify_no_valkey_processes` ×4, `container stop` ×4, `container remove` ×4,
`network remove` ×1 — which is four nodehosts, not two.

**Four nodehosts at exact-50 is not merely what the arithmetic says; it is what
the equivalence diff wants.** A native run configured down to two nodehosts
would differ from the frozen baseline in its fault-domain count, which moves
`nodehost_density_plan`, every node's `nodehost_id`, the fault matrix's targets
and the cleanup row count all at once — a large declared delta bought for
nothing. The ladder therefore keeps the global density defaults and sizes the
fleet to the plan, not the plan to the fleet. The roadmap's acceptance says
"≥2 simulated hosts"; four satisfies it.

### 0.2 The handover's cleanup delta follows the same error

It states *"the native backend emits five rows per nodehost in four kinds … so
**ten rows** at exact-50."* Five rows per nodehost is right; the nodehost count
is not. At four nodehosts it is **twenty rows**, against the Docker baseline's
twenty-one. See §6.3, where this is declared in advance as required.

### 0.3 What was checked and held

Handover items 1 (five seam operations already driven against a live host),
5 (the Load Lane's remote directory is the one known residue), 6
(`host_evidence`'s ssh path unproven end to end) and 7 (the abort proof is
reusable) were checked and are accurate. The unexercised-operation list in item
1 is used verbatim as the smoke's scope in §5.

---

## 1. The harness cannot serve any native run, and the reason is not a bug in the product

This is the item's first finding and it blocks every rung. It was found by
bringing up a four-host fleet and compiling a plan against its real manifest,
which is the only way it could have been found: every part of it is individually
correct.

### 1.1 The measurement

```
$ python3 scripts/simulated_hosts.py up --fleet-id sim-l5 --hosts 4 \
      --azs az-a,az-b --client-port-base 31000 --client-ports 60
hosts: 4  start: 2.61s  ssh ready: 3.32s

REFUSED: host sim-host-02 serves ports 31120-31179 and nodehost
         nodehost-az-a-01 needs [31003, 31007, 31011, 31015, 31019, ...]
```

### 1.2 Why it happens

Three decisions, each right on its own, compose into a refusal:

1. `planner/plan.py:389` assigns `client_port = port_base + ordinal` — **once,
   globally, before nodehosts exist**. A node's port is a property of the
   cluster, not of where the node lands.
2. `nodehost_density.py` then round-robins nodes onto nodehosts *within* a zone.
   So a nodehost's client ports are an arithmetic progression with a stride,
   spanning the **entire** run's port window: at exact-50, `nodehost-az-a-00`
   holds 31000, 31004, … 31048.
3. The harness gives each host a **distinct contiguous block**
   (`client_port_blocks`), because `simulated_host_and_native_bundle_map.md`
   §3.1 reasoned that a real host states its client ports "as a security-group
   range" and that "which ports inside it a run uses is the run's business".

A contiguous per-host block can never cover a stride that spans the whole
window. No choice of `port_base`, `--client-ports` or host count fixes it, and
neither does reducing `nodehosts_per_az` to 1 — that changes the stride from 4
to 2 and leaves it interleaved.

### 1.3 Why Docker never met this

Under Docker a nodehost is *created by the run*, after the plan exists, and each
container publishes exactly the ports its own nodes were assigned. The
port-to-host question is answered by the plan and then executed. **A fleet that
exists before the plan cannot do that** — which is precisely the difference M3
exists to expose, arriving one item earlier than expected.

### 1.4 The fix is in the harness, and it makes the manifest more faithful

The site that is wrong is the harness, which maps every host onto one address.
On a real fleet the question does not arise: each host has its own IP and the
security group opens **the same** range on all of them. The harness now says the
same thing:

- each host gets its own client address, `127.0.0.2` … `127.0.0.9`;
- every host declares **one shared range** wide enough for the whole run;
- the manifest's field set is unchanged, so the product cannot tell.

Verified end to end before adopting it, because macOS was the doubt:

| what | measured |
|---|---|
| `bind(("127.0.0.2", …))` with no alias | `EADDRNOTAVAIL` — needs `ifconfig lo0 alias` |
| aliases `127.0.0.2`–`127.0.0.8` present | bind and connect OK on `.2` and `.8` |
| Docker Desktop 29.2.1 honours `-p 127.0.0.2:…` | yes — `127.0.0.2:31000->31000/tcp`, `lsof` confirms the listener is on `.2`, not `.1` |
| same port, two containers, two aliases | both reachable and correctly routed (`.2`→`HI`, `.3`→`THREE`) |
| exact-200 shape: 8 hosts × 200 ports | 7 of 8 up in 41 s; the 8th collided only because it was given `127.0.0.1`, already held by the live fleet |
| placement against an alias-shaped manifest | exact-30 and exact-50 both **PLACED OK** |

Two consequences follow from the last two rows.

**No simulated host may use `127.0.0.1`.** That address is shared with
everything else on the machine, including a Docker gate run's published node
ports, and the collision above is exactly that failure. Hosts take `.2` upward
and `.1` is left to the Docker backend.

**The aliases are the operator's to create.** `ifconfig lo0 alias` needs root,
and a lab harness must not invoke `sudo`. It therefore *checks* for the aliases
it needs and refuses with the exact command to run. They persist until reboot.

**Cost, measured and accepted.** Publishing 200 ports per host is ~2.9 s per
host at start and slow to tear down — removing five such containers exceeded two
minutes. That is a per-fleet cost, not a per-run one, and exact-200 pays it once.

---

## 2. The configuration contract still refuses a native run — half of it

`native_backend_slice_map.md` §6.4 reports item 1.2 fixing this: *"`config/
validation.py` refused any `runtime.provider` but `docker` … `ecs` is admitted
with two required fields of its own."* That is true of the hand-written checks
and **not** of the JSON schema, which runs first:

```
$ ... cli config validate --config <native draft>
status: FAIL
  SCHEMA_VALIDATION: $.runtime.provider: expected one of ['docker'], got 'ecs'
```

`schemas/config/run_config.schema.json` still pins `runtime.provider` to
`["docker"]`. Measured that this is the **only** schema blocker: with `"ecs"`
added to the enum and nothing else changed, the same draft validates `PASS`
with no findings. `runtime` already carries `additionalProperties: true`, so
`host_inventory_path` and `native_bundle_dir` need no schema of their own.

This is item 1.2's unfinished business rather than a new contract decision, and
it is inside item 1.5's acceptance rather than beyond it: a configuration the
schema refuses makes a native Gate run impossible. It is reported here and lands
as its own commit naming what it corrects.

---

## 3. The first native run configuration, derived

`real.local.full-flow` already takes `--config`, so the ladder needs **no new
catalog entry** — which is also why it must not have one: `real.ecs.*` belongs
to item 1.7.

What the configuration must say, and why each line is forced rather than chosen:

| key | value | forced by |
|---|---|---|
| `runtime.provider` | `ecs` | `execution.BACKENDS`; selects `native_multi_ecs` |
| `runtime.host_inventory_path` | the fleet manifest | `validation.py` requires it |
| `runtime.native_bundle_dir` | the pinned bundle | `validation.py` requires it |
| `runtime.valkey_image` | a `9.1.x` tag | `VALKEY_VERSION` check; `verify_image` reads it |
| `runtime.sandbox_mode` | `container_namespace` | `SANDBOX_MODE` admits only two values |
| `network.azs` | `[az-a, az-b]` | must match the fleet's zones or placement finds no host |
| `cluster.port_base` | inside every host's declared range | §1.4 |
| `cluster.*` otherwise | identical to `scale_50.yaml` | the equivalence diff |
| density keys | **absent** — global defaults | §0.1 |

`hosts:` stays as the Docker configs write it. The planner uses it only for
`_check_host_capacity` and for a pre-placement `host_id`, which
`_place_nodehosts_on_fleet` then overwrites with the fleet host. Introducing
fleet vocabulary there would duplicate the manifest in the configuration, and
the manifest is the single source by design.

One configuration per rung — `native_30`, `native_50`, `native_200` — mirroring
`scale_30/50/200`, because `cluster.shards` differs per rung and a single
parameterised file would have to encode the scale somewhere the vocabulary
contract forbids.

---

## 4. What the ladder can and cannot prove, per rung

| rung | fleet | what it first proves | what it cannot |
|---|---|---|---|
| smoke | 2 hosts | the ~19 seam operations no host has run through the product | anything about a cluster |
| exact-30 | 4 hosts | the whole lifecycle natively; first native `management_matrix` and `fault_matrix`; first native Load Lane | equivalence — no frozen 30-node baseline exists |
| exact-50 ×2 | 4 hosts | equivalence against the frozen Docker baseline | scale |
| exact-200 | 8 hosts | scale, and the formation-dwell measurement | real network, real skew |

exact-30 is the smallest run reaching either matrix (CLAUDE.md; `minimum: 30` in
the Gate and `min_nodes: 30` in the scenario definition), so it is where the
fault lane and the Load Lane are first exercised natively — and therefore where
this item's two decision points get their measurements (§7).

---

## 5. The bring-up smoke

Its purpose is search-space reduction, stated by `native_backend_slice_map.md`
§11: a first native exact-30 failure must not have a dozen unexercised
operations in it. Five operations already run against live hosts through
`scripts/native_cleanup_proof.py` — `verify_image`, `reclaim_run`,
`start_nodehost`, `isolate_nodehost`, `release_run` — and the smoke does not
re-prove them.

**Its scope is the complement**, taken verbatim from the handover:
`send_bundle`, `install_bundle`, `start_node_processes`, `start_node`,
`stop_node`, `kill_node`, `wait_nodes_ready`, `collect_node_pids`,
`run_cluster_admin`, `client_host`, `pause_node`, `resume_node`,
`pause_nodehost`, `resume_nodehost`, `rejoin_nodehost` on its **success** path
(item 1.4 reaches it only from `isolate`'s failure branch), `resource_sampler`,
`load_lane_host`, and `host_evidence`'s two verbs.

Ordering is not arbitrary. §11 of the 1.2 map names the three argv a fake
transport cannot shape-check, and they go first:

1. the digest-addressed **install** (`send_bundle` → `install_bundle`), because
   every later argv runs under the `PATH` it establishes;
2. the `PATH`-prefixed **`start_all.sh`** (`start_node_processes`), because a
   bundle that installed and cannot start is a different failure;
3. **`isolate_nodehost` → `rejoin_nodehost`**, on a host we are willing to lose,
   because a wrong control-port exception locks the actuator out of the host.

Then the rest, ending with `host_evidence` — the one surface with no on-host
proof at all (1.3 map §11.6) — and `load_lane_host`, which is where §7.1's
decision is checked against a real transfer.

It reuses `native_cleanup_proof.py`'s plan and record shapes rather than
inventing its own; those records are already the shapes the lifecycle produces,
which is the property that makes the smoke's result mean something. It does
**not** reuse that script's `place()`, which starts `valkey-server` by raw
`_run` — the smoke's whole point is to go through the operations.

---

## 6. The equivalence diff, and the deltas declared before the run

The roadmap requires vocabulary deltas declared **in advance**. Anything not
below is a finding.

### 6.1 What is compared

`./scripts/diff_stage_artifacts.py --stage <stage> BASELINE CANDIDATE` over the
five registered stages, against `artifacts/baselines/exact-50-6b6f57fd/`, which
stays frozen. Calibration first — the two baseline runs against each other, every
view identical — then the candidate.

### 6.2 The two inherited Docker deltas still apply

The frozen baseline predates `ded96fac` and `313cacc9` and `85d5096a`, so a
correct run scores **`management_matrix` 6/8** (row count +14,
`cluster_migrate_keys` 4 → 18, three row kinds changed and fourteen unchanged)
and **`fault_matrix` 5/6** (the three partition scenarios' isolated side). These
are inherited, not native; a native run must show the *same* shapes.

### 6.3 The native deltas, declared now

- **`cleanup`.** Docker emits 21 rows in six kinds. Native emits five rows per
  nodehost in four kinds — `terminate`, `verify_exit`, `remove` (firewall),
  `remove` (run state), `scan` — so **20 rows at four nodehosts**, and no
  `network remove`: `create_network` has no native meaning (1.2 map §4.3).
  `cleanup_timing` carries the same six second-valued keys plus
  `cleanup_remove_firewall_rules_seconds` and
  `cleanup_remove_run_state_seconds`.
- **`runtime_start`.** `nodehost_density_plan` gains the placement fields
  (`host_id` naming a fleet host rather than `local`, `host_control_endpoint`,
  `host_data_address`, `host_client_address`, `fleet_id`,
  `fleet_manifest_sha256`). `state:before_cluster` carries
  `runtime.type: native_multi_ecs`. `nodehost_bundle_manifests` describes the
  native bundle rather than the image.
- **`cluster_form`, `management_matrix`, `fault_matrix`.** No vocabulary delta is
  predicted beyond §6.2 — command *argv* differ (ssh rather than `docker exec`)
  but the views compare `command_kind`, not argv. **This is the prediction the
  rung tests**, and it is the one most likely to be wrong.

### 6.4 What is reported rather than diffed

Timings throughout, and the fault lane's three scale-fixed numbers as
invariants: **9 scenarios, 12 command rows, 15 windows**. RTO is compared per
scale — 45–50 s is the exact-50 band — and simulated dwell and RTO numbers are
development signal, not bands, because the network is not real.

---

## 7. The two decision points this item owns

### 7.1 The Load Lane's remote directory — decided, and cheaper than 1.4 predicted

§8.4 of the 1.4 map lists two candidate fixes and refuses both *there*. The
second — the lane makes its own root run-scoped, `f"{root}/{run_scope}/{label}"`
— was refused because "it changes memtier's argv on **both** backends, and that
argv is recorded evidence in every frozen baseline".

Measured against the frozen baseline, that cost is **smaller than stated**. The
argv appears in exactly two places, and neither is compared:

- `scalable_stability_observation.json` — but the `stability_observation:
  verdicts` view deliberately reduces it to statuses and structural scalars
  ("40,168 diff lines between two runs of the same code"), and the argv is not
  among them;
- `memtier_*.stderr.log` — and `load_lane_evidence` is a **reported** view that
  lists filenames, sizes and JSON parseability, not contents.

So the run-scoped root moves **no diff view and no reported line**. It is the
correct fix, it is cheap, and it is taken here. It still reaches a real Docker
run's path, so it is proven the way CLAUDE.md requires: two consecutive real
exact-50 Docker runs diffed against the frozen baseline, with the prediction
7/7, 5/5, 6/8, 5/6, 2/2 unchanged stated before the runs.

### 7.2 The fault actuator's pidfile — measured, and the measurement reversed it

**Decided: changed.** The criterion below was set before measuring, and the
measurement met it.

`_signal_run_processes` (`pause_nodehost`, `resume_nodehost`) still enumerates
`<run_root>/*/valkey.pid`, the notion of "what is running" both cleanup paths
abandoned. 1.4 §8.3 left it deliberately and assigned it here, "to the item whose
ladder exercises the fault lane".

The concrete risk is **pid reuse**, not a stale signal: item 1.4 measured that a
`SIGKILL`ed node leaves a pidfile holding a dead pid, and the fault matrix kills
nodes. `kill -STOP <dead pid>` fails harmlessly; `kill -STOP <reused pid>`
suspends something that is not ours.

The enumeration to replace it with already exists — `_owned_process_walk`, the
`/proc/<pid>/cwd` scan both cleanup paths share. The change is small. What is
not yet known is whether the exposure is real *in this lane*, and the
measurement is available for free at rung 1: instrument the fault matrix's
`pause_nodehost` to report `signalled` against the number of live owned
processes on that host. If they agree in every scenario, the pidfile is current
whenever pause acts and the change is not this item's to make; if they disagree,
it is.

**Decided by that measurement, not in advance**, because changing it moves
`fault_command_log`'s argv and its `signalled` count — a declared delta that has
to be worth buying.

**The measurement, and what it cost to get.** A run's artifacts cannot answer
this: the fault record keeps the pause *action string* and not the `signalled`
count. So it was taken on the hosts, through the smoke, with a `kill_node`
placed before the pause — the only arrangement where the two notions can
disagree:

```
pause_nodehost                {pidfiles: 2, live: 2, signalled: 2}
kill_node
pause_nodehost after a kill   {pidfiles: 2, live: 1, signalled: 1}
```

They disagree by one, because a SIGKILLed node leaves a pidfile holding a dead
pid. The count self-corrects — `kill -STOP` on a dead pid fails and is not
counted — so no signal is lost, but the actuator *attempted* one against a pid
it no longer owned, which is exactly §8.3's collateral-signal risk. Changed to
`_owned_process_walk`, so the backend has one notion of what is running instead
of two. Native-only; the Docker actuator is separate and untouched, so no frozen
baseline moves.

The first attempt at this measurement was **inconclusive and did not say so**:
the smoke killed the pid the node had before `stop_node`/`start_node`, so the
kill was a no-op and the counts stayed 2/2/2, which reads exactly like agreement.
Caught only because the numbers failed to move when they should have. `start_node`
now keeps the node's pid current in the smoke, as the lifecycle does.

### 7.3 The 240s formation dwell window — deferred to M3-B, with reasons

CLAUDE.md requires the window re-argued "on any distributed backend". Judgement:
**the measurement is taken at rung 3 and recorded; the bound is not re-argued
here.** The window exists to bound gossip convergence, gossip crosses the
network, and these hosts share a kernel and a loopback — so a simulated dwell is
a lower bound on the quantity the bound is protecting against, and a bound
argued from lower bounds is worse than the one it replaces. The roadmap already
places this in item 1.6, whose acceptance says "record formation-dwell
statistics; CLAUDE.md requires the 240s window re-argued on any distributed
backend". Rung 3 supplies the simulated datum so M3-B has something to compare
against, and says so.

---

## 8. What this item changes outside itself

- `scripts/simulated_hosts.py` — per-host client address, one shared port range,
  the alias precondition check. Lab tooling; no product import either way.
- `schemas/config/run_config.schema.json` — one enum value (§2).
- `src/valkey_scale_lab/observability/load.py` — the run-scoped remote root
  (§7.1). **On a real Docker run's path**; proven as such.
- `templates/configs/native_{30,50,200}.yaml` — new, and the first configuration
  in the repository naming `provider: ecs`.
- `scripts/native_bringup_smoke.py` — new lab tooling.
- No catalog entry, no milestone attachment, no new `NodeBackend` operation
  predicted. The seam stays at **twenty-four**.

---

## 9. Session grain: this item is two sessions, and the boundary is the diff

Item 1.5 is a smoke plus three rungs, two decision points, a harness defect that
blocks all of it, a schema correction, three new configurations, and a Docker
re-proof for §7.1. That is more than one session's scope, and the roadmap's
session rule wants boundaries where the operator reads a report and re-authorises.

The natural boundary is **before the equivalence diff**, because the diff is
only meaningful against a candidate whose deltas have stopped moving:

- **M3-A-5** — this map; the harness fix; the schema enum; the three
  configurations; the smoke; **rung 1 (exact-30)**; and the two decision points
  §7.1 and §7.2 settled on rung 1's measurements, including §7.1's Docker
  re-proof.
- **M3-A-6** — **rung 2** (native exact-50 ×2 and the equivalence diff) and
  **rung 3** (native exact-200 on eight hosts), plus the dwell datum of §7.3.

Proposed, not assumed: the operator sets the boundary.

---

## 10. Proof — what has to be shown

For M3-A-5:

- `./gate suite repository.all` at **92/92** before each commit.
- The alias-shaped manifest places at exact-30, exact-50 and exact-200 —
  compiled, not run.
- The smoke drives every operation in §5 against two live simulated hosts and
  reports, per operation, what the host answered.
- Rung 1: native exact-30 through the Gate on four simulated hosts, PASS, 12/12
  steps, zero residue, no `ERROR` in any artifact, fault lane 9/12/15.
- §7.1: two consecutive real Docker exact-50 at 7/7, 5/5, 6/8, 5/6, 2/2 with both
  inherited deltas at their declared shapes and no third.
- §7.2: the `signalled`-versus-live measurement recorded, and the decision it
  produced.

For M3-A-6, the roadmap's own hard stop: equivalence diff clean apart from the
deltas declared in §6, native exact-50 ×2 and exact-200 PASS at 12/12.

---

## 11. What the smoke measured

`python3 scripts/native_bringup_smoke.py --fleet-id sim-smoke`, two simulated
hosts, two nodes each. **30 of 30 operations answered.** Every operation the
handover listed as unexercised has now run against a live host through the
product, and so has every one of the five that had already run.

Four results are worth keeping beyond the pass mark:

- **`host_evidence`'s ssh path is closed.** Item 1.3's honest boundary — "no
  journal has been fetched off a host over ssh *through the product*" — is
  answered: 4 journals, 4601 bytes, from 2 hosts, through `collect_node_journals`,
  which is `runtime_start`'s own caller and not the raw verb. Clock exchanges
  answered at +4.7 to +7.9 ms offset inside a 15–21 ms bound, on hosts whose true
  offset is zero. Wider than item 1.3's +2.1..3.2 ms, which is what a busy
  machine looks like; the bound contains it, which is the property that matters.
- **The client-address design is proven by RESP, not by inspection.**
  `wait_nodes_ready` opens a real TCP connection to `client_host(node)` and
  speaks `PING` — §16.2 forbids reaching a node's protocol through a runtime
  transport, so this is the one operation that could not pass unless the alias
  publishing genuinely works. It answered in 9 ms for four nodes.
- **The content-addressed install is doing what it claims.**
  `start_nodehost` took 0.410 s on a host seeing the bundle for the first time
  and 0.036 s on the next run — the digest marker skipping a 14 MB transfer.
- **`pause_nodehost` agreed with the host**: `signalled=2`, `pidfiles=2`,
  `live_owned_processes=2`. That is one datum for §7.2 and **not** the decisive
  one: at that point no node had been killed, so every pidfile was current. The
  case that matters is after `kill_node`, and the fault matrix at exact-30 is
  where it arises.

### 11.1 The one thing the smoke found that reading could not

The Load Lane's residue, **observed rather than predicted**. With managed
residue at zero on both hosts — no run directories, no `valkey-server`, no
`VSLAB` chains — one directory remained: `/tmp/vslab-load-lane/` on the host
that ran the lane. That is §8.4 of the 1.4 map, seen for the first time.

Fixing it took two measurements rather than one. Making the root run-scoped
(§7.1) makes the directory *attributable*; it does not remove it. Having the
lane remove the leaf it created left `/tmp/vslab-load-lane/<run>/` behind —
smaller residue, still residue. The parent is removed with `rmdir`, not
`rm -rf`, because the lane runs under two labels and only the last to finish
finds it empty; a non-empty parent means another label is still running, which
is not that call's business. **Re-measured: zero on both hosts, lane directory
included.**

The disposal is in the native lane host only, and that is not an asymmetry: the
Docker sibling's remote directory is inside a container `release_run` removes,
so it already satisfies the same contract. What remains open is an *aborted*
run, which leaves the directory — now under a path that says whose it is.

---

## 12. Rung 1, and the four defects it found

Native exact-30 took **four attempts**, and the three failures are the rung's
real product. Every one of them was invisible to 798 hermetic tests, to a fake
transport, and to the bring-up smoke — and each would have been far more
expensive to meet for the first time at exact-200.

| attempt | outcome | what it found |
|---|---|---|
| 1 | ran on Docker; killed | `runtime.provider` never selected the backend |
| 2 | `BLOCKED` at 3.89 s | attempt 1's leftover network — the preflight refusing correctly |
| 3 | `FAIL` at 340.40 s | `ResourceSampler` under-declared its contract |
| 4 | **PASS 737.29 s** | — |

and a fourth, found in attempt 3's wreckage rather than by a failure of its own:
`state.json` could not describe where a nodehost was.

### 12.1 The backend was never chosen from the configuration

Attempt 1 is the worst kind of failure: it *succeeded*. `runtime.provider: ecs`
was validated, the manifest was read, placement correctly assigned four
nodehosts to `sim-host-00..03` — and the run then started four **Docker
containers** for them, because `gate execute --backend` had
`choices=["docker_process"]` with that as its default and nothing joined the two
names. Its artifacts named a fleet no process had touched.

This is the fourth instance of one shape in this seam: `cleanup_scenario`
dispatching on `runtime.type` (`4f54442a`), `_execute_runtime` constructing
`DockerNodeBackend()` by name and `validation.py` disagreeing with
`execution.BACKENDS` (1.2 map §6.1, §6.4), and now the selection itself. Item
1.2's acceptance — "the `native_multi_ecs` rejection gone because the backend
exists" — was met without the backend ever becoming *reachable*.

### 12.2 A protocol that under-states its contract makes a second
implementation look finished

`ResourceSampler` declares three methods. The observation layer also reads
`runner.sampler.sampler_id` and `runner.sampler.processes`, and only the Docker
agent carried them. The native agent satisfied the protocol **as written** and
died 340 s in, after `runtime_start` and `cluster_form` had both passed.

Neither a fake transport nor the smoke could catch it, and the reason is worth
keeping: both drive the agent *directly*, and this attribute is read only by the
observation layer. So the test added for it asserts against **both** backends
through the same expression the observation layer uses — a native-only test
would not have prevented the omission it exists to catch.

### 12.3 `state.json` could not say where a nodehost was

`_process_runtime_state` serialised eight fixed fields, none of them the
placement, and `cleanup_scenario` gets a state file and nothing else. Attempt
3's `cleanup_report` carried four `carries no host control endpoint` errors and
no actions. **It was not the failure path's doing** — the serialiser drops them,
so a passing run would have failed its cleanup identically, which is M3's
cleanup criterion failing on the one artifact that measures it. Added
conditionally, so the Docker record keeps the same eight keys.

### 12.4 What the passing run proved

- `backend_id: native_multi_ecs`, no Docker container but the four simulated
  hosts, **30 processes at 8/8/7/7** across `sim-host-00..03`.
- **12/12 steps PASS**, `run_verdict` PASS, no `ERROR` in any artifact.
- **Fault lane 9 scenarios / 12 command rows / 15 windows** — identical to the
  Docker baseline. The three scale-fixed numbers surviving a change of runtime
  is M3's thesis, tested for the first time. RTO 47.26 s.
- The fault matrix ran its real mechanisms: `iptables` chains on the host for
  the three partition scenarios, the in-process TCP proxy for delay/loss/flap
  (Slice 4's finding that those touch no runtime primitive, confirmed on a
  second backend), and `pause_nodehost` for `node_host_stop` and `az_stop`.
- **`cleanup` exactly as §6.3 declared in advance**: 20 rows in four kinds —
  `terminate` ×4, `verify_exit` ×4, `remove` ×8, `scan` ×4 — no network row, and
  both extra timing keys. Declared before the run, matched after it.
- **Zero residue on all four hosts**, Load Lane directory included.

### 12.5 The confirming run, after §7.2's actuator change

The actuator change is on a real run's path, so it was proven the same way:
a second native exact-30, **PASS 729.05 s**, at marks identical to the first —
12/12 steps, fault lane **9/12/15** with all nine `REAL_PASS`, cleanup PASS at
20 rows in the same four kinds with no errors, zero residue on all four hosts,
no `ERROR` in any artifact. RTO 46.45 s against the first run's 47.26 s.

`node_host_stop` and `az_stop` still report the same actions — the change is in
how the actuator finds the processes, not in what it does to them, and the two
runs agreeing on every mark is the evidence for that.

Two consecutive native exact-30: **PASS 737.29 s and PASS 729.05 s.**

One thing rung 1 could not prove, and it is the honest boundary: **there is no
frozen 30-node baseline**, so nothing here is an equivalence result. That is
rung 2's against the exact-50 baseline, and it is why the session splits here.

---

## 13. Findings this derivation produced and does not fix

- **`nodehosts_per_az: 2` is a global default that no scale configuration
  states.** Every reader of a `scale_*.yaml` who computes nodehosts from
  `max_logical_nodes_per_nodehost` alone gets the wrong answer, which is exactly
  what the handover did. Not fixed: the default is correct and moving it into
  each configuration would duplicate it four ways. Recorded so the next reader
  does not repeat it.
- **The harness's `capacity` is the Docker VM's, not the host's** — carried
  unchanged from `simulated_host_and_native_bundle_map.md` §6. It matters more
  now: `_check_host_capacity` reads `memory_gb` from the *configuration*, which
  says `auto`, so nothing currently reads the manifest's capacity. If a later
  item makes it, it will be reading eight copies of one VM's memory.
- **A run id is shared by two runs of one scenario on one date** (1.4 map §8.1),
  and the ladder runs the same scenario repeatedly on one day. It is why rung 2's
  two runs must not overlap, and it is not this item's to fix.

---

## 14. Rung 2, and what the equivalence diff actually found

Session M3-A-6. Four native exact-50 runs were taken; two of them are the rung's
result and the first two are what found the two defects below.

| run | config | outcome | why it was taken |
|---|---|---|---|
| 1 | port_base 31000 | PASS 868.24 s | first native exact-50; found §14.1 and §14.2 |
| 2 | port_base 7400 | PASS 860.66 s | §14.1 fixed; confirmed the delta it removed |
| 3 | + bundle release | **PASS 832.32 s** | §14.2 fixed |
| 4 | + bundle release | **PASS 871.47 s** | the consecutive pair |

Runs 3 and 4 are identical in **every** view and every field: `runtime_start`
5/7, `cluster_form` 5/5, `management_matrix` 6/8, `fault_matrix` 4/6, `cleanup`
1/2, with the same per-field delta set below. Both 12/12 steps, `run_verdict`
12/12 checks OK, 50 of 50 nodes, fault lane **9 scenarios / 12 command rows / 15
windows** with all nine `REAL_PASS`, cleanup 20 rows in four kinds, `found: 0` on
all four nodehosts, no `ERROR` in any artifact. RTO 47.798 s and 47.255 s, inside
the exact-50 band. Residue was also checked from outside the product, over the
harness's own ssh: **bundles 0, run trees 0, `valkey-server` 0, `VSLAB` rules 0
on all four hosts** after each.

The calibration was re-taken at this HEAD before any of it was trusted: the two
frozen baseline runs against each other give **7/7, 5/5, 8/8, 6/6, 2/2**.

### 14.1 The equivalence diff's first finding was in this map, not in the product

§3 said `cluster.port_base` must lie inside every fleet host's declared range and
chose 31000, and §6.3 then declared what `runtime_start` would differ in without
noticing that the port base was one of those things. Measured on run 1:
`nodehost_density_plan.nodehosts[].ports` ×100, `state.nodes[].client_port` and
`cluster_bus_port` ×50 each, and **all 50 `node_configs`** — four lines each,
`port`, `cluster-port`, `cluster-announce-port`, `cluster-announce-bus-port`, and
nothing else.

The harness publishes whatever range it is told to, so the base was free all
along. Set to `scale_50.yaml`'s own 7400/17400 and the fleet brought up with
`--client-port-base 7400`, `node_configs` goes to **SAME** — 50 of 50 — and the
fault lane's `proxy_snapshot.target_port` and `details.target_port` stop
differing with it. `runtime_start` 4/7 → 5/7. The configuration's header already
claimed everything but the two runtime keys was "deliberately identical to
`scale_50.yaml`"; it is now true. `native_200` takes `scale_200`'s 7800/17800 for
the same reason; `native_30` is left at 31000, because rung 1's two passing runs
were taken with it and no 30-node baseline exists to compare against.

### 14.2 A PASS with `found: 0` was leaving 88 KB per host

Found by checking the hosts rather than the artifact — `cleanup_report` said
`found: 0` on all four nodehosts and every host still held
`/tmp/vslab-bundle-<run_id>-<nodehost_id>/`: node configs, `install.sh`,
`start_all.sh`, `collect_pidfiles.sh`, `manifest.json`. Two defects, one on each
side of M3's cleanup criterion, and neither visible from inside a run.

**The removal read a field the serialiser drops.** `_release_remove_state` took
the path from `state.json`'s nodehost record and `_state_nodehost` records eight
fields with `remote_bundle_dir` not among them, so `removals` was `[run_root]`
alone and the step reported `PASS`. This is rung 1 §12.3's shape in the sibling
field — the serialiser, not the failure path — and it is why item 1.4's own abort
proof did not catch it: `native_cleanup_proof.py` builds the state it releases
and puts `remote_bundle_dir` in it.

**The scan asked about two of the three things a native run leaves.**
`_scan_run_residue` asked for the tree and the processes running out of it, so
`found: 0` was truthful about what it scanned and silent about the rest. The
operation whose docstring says it measures rather than asserts was measuring an
incomplete question — the same shape item 1.4 §1 found in the process arm of the
very same scan.

Both fixed at the site that was wrong. The path is now **derived from the run
id**, which is the expression `reclaim_run` has always used, so the two cleanup
paths agree about what a run owns and neither depends on being told — item 1.4's
own principle, applied to the resource it had missed. The scan asks for all three
residues in one session and the row says `scanned: [state, bundle, process,
firewall]`. Native only: the Docker backend removes its bundle with the
container, so no frozen baseline moves. Proven on the hosts, twice.

### 14.3 The delta, measured to the field, in both accepted runs

Every difference in every differing view, with nothing else present:

| view | difference | declared? |
|---|---|---|
| `nodehost_density_plan` | `fleet_id`, `fleet_manifest_sha256`, `host_client_address`, `host_control_endpoint`, `host_data_address` added ×4; `host_id` ×4 | §6.3 |
| `nodehost_density_plan` | `config_sources.scenario_config_path` | no — it names the configuration file |
| `state:before_cluster` | `backend_id`, `runtime_type` | §6.3 |
| `state:before_cluster` | `nodes[].host_id` ×50 | no — the placement, in the sibling field §6.3 did name |
| `state:before_cluster` | `valkey_image_preflight` gains nine keys, loses `command` | §6.3, **but named in the wrong artifact** — see §14.4 |
| `management_command_log` | +14 rows, all `cluster_migrate_keys` (4 → 18); 3 kinds changed, 14 unchanged | §6.2, exact shape |
| `management_command_log` | `argv` on 212 of 1592 shared rows | no — §14.5 |
| `management_command_log` | `stdout_tail` on 5–7 health-gate rows | no — §14.6 |
| `management_sequence` | `command_count` 270 → 277, `command_log_refs` and `command_ids` shifted by the 14 inserted rows | §6.2 |
| `management_sequence` | `workload_impact.errors_observed_during_operation` on 1–2 operations | no — §14.7 |
| `fault_command_log` | `argv`, and **nothing else at all** — 17 rows plus one length change | no — §14.5 |
| `fault_sequence` | `isolated_reachable_from_this_side` ×3 and `isolated_unreachable_reason` ×3 added, `isolated_cluster_info` ×3, `isolated_cluster_state_ok` ×1, `client_observations` ×3 | §6.2, exact shape |
| `fault_sequence` | `details.actions[]` ×14, `proxy_snapshot.target_host` ×3 | no — §14.5 |
| `cleanup_report` | 21 rows in six kinds → 20 in four; no `network remove`; two extra `cleanup_timing` keys | §6.3, exact shape |

`cluster_form` is **5/5 identical**, which is §6.3's prediction holding in the one
stage where it holds completely.

### 14.4 What §6.3 predicted that did not happen

`nodehost_bundle_manifests` was declared to "describe the native bundle rather
than the image". It is **byte-identical** on both backends, because that artifact
is the *run* bundle — the node configs and the three scripts the lifecycle
writes — and not the software bundle. The native software bundle's description
does appear, in `state:before_cluster.valkey_image_preflight`, which gains
`bundle`, `bundle_dir`, `archive_sha256`, `architecture`, `memtier_version`,
`memtier_benchmark_sha256`, `memtier_source_sha256`, `verified` and
`not_verified`, and loses the Docker preflight's `command`. Right fact, wrong
artifact. `not_verified` is item 1.1's declared gap — the controller hashes bytes
and cannot ask a running server for `CLUSTER MYSLOTS` — arriving in a real run's
evidence for the first time.

### 14.5 The prediction the rung was built to test is false: argv is compared

§6.3: *"command argv differ (ssh rather than `docker exec`) but the views compare
`command_kind`, not argv. **This is the prediction the rung tests**, and it is
the one most likely to be wrong."* It is wrong. The command-log views keep the
whole row, so `argv` is compared in full, and it is the **only** thing that
differs in `fault_command_log`:

```
- ["docker", "exec", "vslab-...-nodehost-az-b-00", "valkey-server", "<conf>"]
+ ["sh", "-c", "PATH=/opt/valkey-scale-lab/bundles/fe1839de28d861ad/bin:$PATH; valkey-server <conf>"]
- ["docker pause vslab-...-nodehost-az-a-00", "docker unpause vslab-...-nodehost-az-a-00"]
+ ["kill -STOP every owned Valkey process on sim-host-00", "kill -CONT ... on sim-host-00"]
```

`fault_sequence.details.actions[]` ×14 and `proxy_snapshot.target_host` ×3 are the
same class: the actuator's action strings, and the address the in-process TCP
proxy dials, which is a fleet host's client address rather than a container IP.

**This is a delta to declare, not a normalisation to add**, and the reasoning is
CLAUDE.md's own seeded-regression rule. Two backends cannot issue the same argv
by construction, so a literal comparison can never be equal; but a view that
collapsed argv would stop being able to see the wrong command being run, which is
the single most valuable thing a command log carries. So the boundary is drawn by
what the field *is*: `argv` is backend-specific evidence and everything around it
— `command_kind`, `operation_id`, `target_logical_id`, `status`, `returncode`,
`attempt_count` — is not, and all of it is identical here.

The strength of the result is in the second half of that sentence. On the fault
lane, **argv is the entire difference**: same kinds, same order, same targets,
same statuses. On the management lane, 212 of 1592 rows differ in `argv` and the
other 1380 do not differ at all.

### 14.6 The health gate escalates where Docker did not - read §15.5

The largest measured behavioural difference between the two runtimes, and it is
not in any compared field — it is inside `stdout_tail` on the rolling restart's
`rolling_restart_health_probe_summary` rows. The gate probes a representative
sample per batch; when that round is not clean it falls back to one diagnostic
round over the whole fleet, recorded as `sample_scope: all_nodes_diagnostic` with
`full_probe_count` 0 → 50 and `node_command_count` 12 → 112.

| runtime | runs | escalations per run |
|---|---|---|
| Docker exact-50 | 6 (two frozen baselines + four since) | **0, 0, 0, 0, 0, 0** of 44 gates |
| native exact-30 | 2 | 2 and 3 of 26 gates |
| native exact-50 | 4 | 6, 4, 3, 5 of 44 gates |

Ten runs, and the split is clean. **Corrected at rung 3, which is why the rung
exists: §15.5 measures zero escalations on native exact-200 and on four Docker
exact-200, so "native escalates and Docker does not" is false as stated. Read
§15.5 before using this table** - every escalation observed is on a native run
under the heavy workload, and rung 3 runs a light one. The verdict is unaffected — `status`,
`cluster_state`, `known_nodes`, `slots_assigned` and the gate's `command_ref` are
all compared and all identical, and both rolling restarts PASS — so this is
development signal rather than a regression. It is reported here because of what
it costs: each escalation is ~100 extra node commands at exact-50, and a
whole-fleet diagnostic round at exact-200 is four times that. §16 item 1 asks the
normal path not to run whole-fleet `CLUSTER NODES` periodically, and this is a
runtime that reaches for it more often. **Rung 3 measures it at 200.**

Not fixed and not normalised: `PROBE_COUNT_FIELDS` already excludes
`retry_count`, `full_probe_count`, `representative_probe_count` and
`node_command_count` from comparison as a retry record, but that exclusion does
not descend into the serialised summary in `stdout_tail`, and `sample_scope` is
not in the set at all. Left alone deliberately — the view differs for declared
reasons anyway, so the score does not move, and this is the one place the
escalation is visible.

### 14.7 A third field the frozen baselines agree on by coincidence

`management_sequence.result.operations[].workload_impact.
errors_observed_during_operation` is a per-run workload observation. Both frozen
baselines record `[…, True, True, …, True]` for the two rolling restarts, which
is why the calibration cannot see it; the four native runs record `F,F`, `T,F`,
`T,F` and `F,F`. It is the third instance of CLAUDE.md's warning that two runs
agreeing is not proof a field is deterministic, after the rolling-restart probe
counts and the light probe. Reported rather than excluded, for the same reason as
§14.6: the view already differs for a declared reason.

### 14.8 What rung 2 settles

The roadmap's hard stop for this half is met: two consecutive native exact-50 at
PASS with 12/12 steps on four simulated hosts, equivalence-diffed against the
frozen Docker exact-50 baseline, every delta accounted for to the field. Four of
the fourteen delta rows were not declared in advance; one was this map's own
arithmetic (§14.1) and is now removed rather than declared, one is a product
defect that is now fixed (§14.2), and the rest are §14.4–§14.7, which correct
§6.3 rather than the product.

The thesis M3 exists to test — that the same lifecycle, the same evidence and the
same verdicts survive a change of runtime — holds at exact-50 with the difference
confined to *what command was run on which host*.

---

## 15. Rung 3, and what fleet width measured

**Native exact-200 on eight simulated hosts: PASS 1544.44 s, first attempt.**
Eight nodehosts, one per host, 25 logical nodes each, `sim-host-00..07` at
`127.0.0.2..9` on a shared 7800–7999 range.

- **12/12 steps PASS**, `run_verdict` 12/12 checks OK, **200 of 200 nodes**,
  no `ERROR` in any artifact.
- **Fault lane 9 scenarios / 12 command rows / 15 windows**, all nine
  `REAL_PASS`. The three scale-fixed numbers now hold across two runtimes and
  three scales.
- **`cleanup` 40 rows in four kinds** — `terminate` ×8, `verify_exit` ×8,
  `remove` ×16, `scan` ×8 — which is §6.3's five-rows-per-nodehost at eight
  nodehosts, and no `network remove`.
- **Zero residue on all eight hosts**, checked from outside the product over the
  harness's own ssh: bundles 0, run trees 0, `valkey-server` 0, `VSLAB` rules 0,
  Load Lane directory empty. `found: 0` in all eight scan rows, now meaning it.

### 15.1 The delta does not grow with fleet width

Diffed against the frozen `exact-200-6b6f57fd` baseline, which covers
`runtime_start` and `cluster_form` only because both its runs fail downstream.
Calibrated first: **6/6 and 4/4**, one view unavailable in each.

**`cluster_form` is 4/4 identical** and **`node_configs` is SAME — 200 of 200**.
`runtime_start` differs in the same two views as at exact-50, in the same fields,
scaled: the six placement fields ×8 nodehosts, `config_sources`, `backend_id`,
`runtime_type`, `nodes[].host_id` ×200, and the nine `valkey_image_preflight`
keys. **No field appears at 200 that did not appear at 50**, which is the
strongest thing this rung can say about §14.3's table.

`lifecycle_timeline` reports `ERROR` in both stages because the frozen baseline
never wrote one — the same limitation `BASELINE.md` records, now visible from the
other side because the candidate passes.

### 15.2 Transport overhead at fleet width, which is what the roadmap left open

M3-A-2 chose multiplexed SSH on a spike: `docker exec` 66.4 ms median, un-multi-
plexed ssh 63.8 ms, multiplexed ssh 10.8 ms. That was a micro-benchmark. This is
the same question inside a real 200-node run, from the two runs' own command
audits — native here against the Docker exact-200 at `47905626`:

| command kind | native n | native median / p90 | native total | Docker n | Docker median / p90 | Docker total |
|---|---|---|---|---|---|---|
| `runtime_command` (the backend's own) | 3037 | 2.0 / 12.0 ms | **25.7 s** | 4853 | 3.0 / 105.0 ms | **276.6 s** |
| `cluster_probe` (RESP) | 2951 | 3.0 / 6.0 ms | 11.4 s | 3629 | 3.0 / 45.0 ms | 37.4 s |
| `cleanup` | 0 | — | — | 39 | 51.0 ms / 29.9 s | 236.4 s |
| all rows | 11289 | | | 13821 | | |

The seam's own transport costs **25.7 s across eight hosts against `docker exec`'s
276.6 s on one**, in fewer commands, and the whole native run is 1544 s against
the Docker spread of 1486–1661 s. The tails are where the difference lives: the
medians are within a millisecond and the p90s are 12 ms against 105 ms.

**These are lower bounds and must not be quoted as fleet numbers.** The hosts
share a kernel and a loopback; a real fleet adds a network to every one of those
3037 commands. What the measurement does establish is that the transport is not a
bottleneck *at this width* and that nothing about eight hosts broke the choice —
M3-B (item 1.6) still owns the real-network number.

### 15.3 Evidence volume at fleet width

| | native exact-50 | Docker exact-50 | native exact-200 |
|---|---|---|---|
| node journals | 50, 7.9 MB | 50, 8.0 MB | **200, 86.8 MB** |
| whole run's artifacts | 37.3 MB | 36.1 MB | **192.6 MB** |
| hosts clocked in `host_evidence` | 4 | 4 | **8** |

Journal volume is a property of the cluster and not of the runtime — 7.9 MB
against 8.0 MB for the same 50 nodes on the two backends. It is **not** linear in
node count: 4× the nodes gives 11× the journal bytes, 158 KB per node at exact-50
against 434 KB at exact-200, because a node's log is dominated by cluster
gossip and every node has four times as many peers to talk about. A run's whole
evidence footprint grew 5.2×.

At the roadmap's later scales this is the number to plan against, not the node
count: 200 nodes cost 87 MB of journals collected once at the last boundary where
they are complete, and the per-node figure is still climbing.

### 15.4 The formation dwell datum §7.3 owes M3-B

Native `cluster_form` at 200 nodes: **60.9 s**. The four passing Docker exact-200
runs measure 59.4, 77.7, 88.1 and 104.9 s, and the five formation-only runs
`convergence_bound_map.md` argues from measure 83.1, 102.5, 137.0, 152.0 and
205.8 s. At exact-50, native measures 52.1, 48.0, 19.7 and 35.7 s against
Docker's 122.6, 57.8, 43.0, 72.1 and 56.6 s.

**The datum is recorded and the bound is not re-argued**, exactly as §7.3
proposed, and the measurement supports the deferral rather than merely leaving
it. Native formation sits at the low end of the Docker spread and inside it at
both scales — it is not a different regime, and at 60.9 s it is a quarter of the
240 s no-progress window. §7.3's argument was that a simulated dwell is a lower
bound on the quantity the bound protects against; the measurement lands near that
lower bound, which is what a shared kernel and a loopback should produce. Nothing
here argues for narrowing the window, and only M3-B's real network can.

### 15.5 Rung 3 falsifies §14.6's claim, which is what it was for

§14.6 said the health gate escalates to a whole-fleet diagnostic round "on native
runs and never on Docker runs". At exact-200 the native run escalated **zero
times in 80 gates**, and so did four Docker exact-200 runs. So the claim as
stated is wrong.

What the ten-plus runs actually say:

| runtime | scale | workload | escalations |
|---|---|---|---|
| Docker | exact-50 | 800 qps, pipeline 8 | 0 in each of 6 runs (44 gates) |
| native | exact-30 | 800 qps, pipeline 8 | 2 and 3 (26 gates) |
| native | exact-50 | 800 qps, pipeline 8 | 6, 4, 3, 5 (44 gates) |
| Docker | exact-200 | 50 qps, pipeline 1 | 0 in each of 4 runs (80 gates) |
| native | exact-200 | 50 qps, pipeline 1 | **0** (80 gates) |

`native_200.yaml` inherits `scale_200`'s far lighter workload — 50 qps and
pipeline 1 against 800 and 8 — so **rung 3 does not separate runtime from
workload**. Every escalation observed is on a native run *under the heavy
workload*, and neither runtime escalates under the light one. Two candidate
causes remain and this ladder cannot choose between them; a native exact-50 run
with `scale_200`'s workload parameters would, and it is one run.

Left as an open finding rather than pursued: the verdict is unaffected in every
run, and the honest correction — that scale is not the variable — matters more
than the cause. §14.6 stands as a *measurement* and falls as an explanation.

### 15.6 One number outside its prior spread

Primary-kill RTO at exact-200: **41.28 s**. Every prior exact-200 measurement is
47.6–53.8 s and the exact-50 band is 45–50 s, so this is the first below either.
It is recorded rather than treated as a finding: a faster recovery is not a
failure, `failover_success` and `redundancy_recovery_success` are both true, and
CLAUDE.md's rule fires on a shift in the whole spread rather than on one run.
The three fault-lane invariants that rule protects — 9, 12 and 15 — are exact.
A second native exact-200 below 45 s would make it a spread.
