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

### 7.2 The fault actuator's pidfile — measured at rung 1, not pre-decided

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

## 12. Findings this derivation produced and does not fix

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
