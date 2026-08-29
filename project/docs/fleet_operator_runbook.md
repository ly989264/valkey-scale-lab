# Running a 1280-node cluster on your own fleet

This is the whole procedure, for an operator with no help. It assumes you have a
cloud account and nothing else: no fleet, no bundle, no manifest, and no prior
run. Every command is one you run yourself, and every number in it was measured
rather than chosen.

What you get at the end is a validated evidence tree and a readable report, on
the machine that took the run.

**It costs real money.** 32 hosts of 8 vCPU / 16 GB for about two hours. Read §8
before you start, and §9 before you decide to run it twice.

---

## §1 What the product needs from a machine, at any provider

The product provisions nothing. It reaches hosts over ssh and runs a pinned
Valkey build on them, so **any provider works** - the questions below are about
the machine, not about who sold it to you. Nothing in the product or in this
procedure names a provider.

| what | value | why this number |
|---|---|---|
| hosts | **32** | 1280 nodes at 40 a host |
| per host | **8 vCPU, 16 GB** | 40 valkey-servers a host is 5 per vCPU, inside the 50 per vCPU measured clean |
| OS | Linux with a POSIX shell, `ssh`, `iptables` | the backend runs command shapes, not packages |
| architecture | anything, **matching your bundle** | see §3 |
| network | one private network all 32 hosts share, and a controller on it | see §6 |
| ports | 7800-32000 reachable host to host | the run's client and cluster-bus range |

Two host settings are not defaults anywhere and one of them has already killed a
run:

- **`net.ipv4.tcp_mem` must be raised.** The cluster bus is a full mesh, so what
  a host's kernel holds is quadratic in the *fleet* and only linear in that
  host's density. At 40 nodes a host in a 1280-node fleet that is 102,320
  sockets and about **799 MiB** at the kernel's own per-socket minimum, against a
  stock ceiling on a 16 GB host of well under that. The first real 1280-node
  attempt died exactly here: 370 kernel `TCP: out of memory` messages beginning
  four minutes in, and cluster formation failing with 152 connection refusals in
  0-1 ms.
- **`ulimit -n` must be large.** A node wants 10,032 descriptors and the
  controller holds O(N) connections at once.

`scripts/ecs_host_prepare.sh` applies both, along with the rest. It says Ubuntu
in its header because that is where it was derived and measured; it is a POSIX
shell script that installs packages with `apt-get`, so on a non-Debian host read
it and do the same things rather than running it.

**Do not trust that it ran.** Most providers boot a host from a startup mechanism
that is a *copy* of a script rather than the script itself, so editing the
committed file does not reach a running host and a reboot can revert tuning you
applied by hand. This is not hypothetical: it is how a prepared fleet arrived at
a paid run untuned. §5 reads the values back off every host, which is the only
statement about a host worth having.

---

## §2 Get the code and the image

```bash
git clone <this repository> && cd valkey-scale-lab/project
python3 -m pip install -e .
python3 -m pip install -r requirements-dev.txt
./scripts/build_valkey_image.sh          # the pinned Valkey 9.1.0 build
```

The image build verifies the upstream archive and applies this repository's patch
with zero fuzz. A real run requires this exact local image and never falls back
to an upstream one.

## §3 Build a bundle your fleet can execute

The fleet does not run containers - it runs binaries out of a bundle the
controller ships to it.

```bash
./scripts/build_native_bundle.py
```

It takes the architecture from the pinned image it reads, so **build it on a
machine of your fleet's architecture** (or with an image built for it). The
result lands in `artifacts/native-bundles/valkey-<version>-memtier-<version>-<arch>/`.

Whether a given fleet host can actually execute a given bundle is a better
question than any library-version rule, and §5 asks it directly.

## §4 Write the fleet manifest

The manifest is the one thing that crosses from your fleet into the product.

```bash
./scripts/make_fleet_manifest.py --fleet-id m4-fleet \
    --user <ssh user> \
    --private-key ~/.ssh/<key> \
    --known-hosts ~/.ssh/<known_hosts> \
    --host az-a:vslab-host-a-0:10.0.1.10 \
    --host az-a:vslab-host-a-1:10.0.1.11 \
    ...                                    # 16 in az-a, 16 in az-b
    --out artifacts/host-fleets/m4-fleet/inventory.json
```

Three things about it:

- **`host_id` is yours to choose** and is not the instance's name. Nothing
  cross-checks it against the machine, and the artifact diff tool compares it
  literally - so a rebuilt fleet that reuses the previous fleet's ids keeps its
  comparisons, and one that takes the provider's generated names strands them.
- **The two AZs are the product's, not the provider's.** They are fault domains
  in the plan. Mapping them onto real availability zones is better and is not
  required.
- The manifest carries no container, image or network vocabulary and no flag
  saying whether the fleet is real. That is deliberate: a backend that could tell
  would make every result taken on simulated hosts a fact about the harness.

Then point the configuration at it. In
`templates/configs/scale_1280_native_ecs_optin.yaml`, exactly three lines are
yours:

```yaml
  host_inventory_path: artifacts/host-fleets/m4-fleet/inventory.json
  native_bundle_dir: artifacts/native-bundles/valkey-9.1.0-memtier-2.5.1-arm64
  nodehosts_per_az: 16
```

**Leave `profile_name` alone.** A real run above 200 nodes is admitted by name:
one predicate keys on that exact string plus eleven other clauses, and a copy of
this file with an edited node count is refused. That is the point of a named
exception rather than a raised cap. None of the three lines above is one of the
clauses, so setting them to a fleet you have does not weaken anything.

If you build a fleet of a different size, keep one nodehost per host and keep the
per-host density inside what your machines carry. Sixteen per AZ is derived from
32 hosts at 40 nodes each; it is not a magic number.

## §5 Check the fleet before you spend anything

```bash
sh scripts/fleet_run.sh preflight --config templates/configs/scale_1280_native_ecs_optin.yaml
```

Three checks in an order where each one's failure is cheaper than the next one's:

1. **Every host, over the control channel the run will use** - not locally, so
   the transport and the session's own limits are under test too. It answers the
   way the backend will ask, by running the command shapes the backend runs. It
   reads `net.ipv4.tcp_mem` back off the host and **refuses** if the fleet you
   declared will not fit in it.
2. **The bring-up smoke**, which drives the seam end to end against your fleet
   before any cluster exists. Without it, a first failure has a dozen
   unexercised command shapes in its search space.
3. **The cleanup proof, at 40 nodes a host.** Reclaim working at two processes a
   host is not evidence about a run that places forty, and a two-hour run that
   strands 1280 processes across 32 hosts is the outcome this ordering exists to
   prevent.

Anything that refuses here costs you nothing. Fix it and run it again.

## §6 Run it from inside the fleet's network

**Not from a workstation.** Transport measured 5.1 ms median from a controller
inside the network against 110-116 ms from a laptop. Across an exact-200 run's
3037 command rows that is 15.5 s against about 5.6 minutes, and at 1280 nodes it
is the difference between a run and a timeout. It also means a baseline frozen
from a workstation run could never be reproduced.

Put a small controller on the same private network, clone the repository there,
and run everything from it.

## §7 Launch

```bash
sh scripts/fleet_run.sh start --config templates/configs/scale_1280_native_ecs_optin.yaml
```

`start` runs §5 again and launches only if it passes. It detaches the run with
`setsid nohup ... < /dev/null &` - all four parts. A run launched without them
dies with the ssh session that started it, mid-flight, and leaves 25 or 40
`valkey-server` processes on every host.

Then:

```bash
sh scripts/fleet_run.sh watch
```

**Watch for `valkey_scale_lab.cli gate execute`, never for the launcher's name.**
The launcher `execv`s into the CLI, so nothing matches the wrapper once a run
starts and a watcher that greps for it reports "finished" immediately. `watch`
already looks for the right thing.

Expect roughly two hours. Formation alone is bounded by a 240-second no-progress
window under a 1800-second ceiling, and that bound has not been measured above
200 nodes.

## §8 The report

When the run ends - **pass or fail** - it renders its own report into the run's
tree at `runtime/report/`: 40 files, an `index.html`, a Markdown summary, 22
CSVs and 11 SVGs. It is entirely offline. A contract check rejects any external
URL, CDN reference, or bare `//` in it, so it opens on a machine with no internet
and nothing is fetched from anywhere.

Copy the directory off and open `index.html`.

The report is a reader, not a second analyzer: **every number in it is lifted
from an artifact the run already validated**, because a report that recomputed
its own figures could disagree with the evidence it summarises. Where a source is
absent it says so and gives the reason - never a zero, never an estimate.

Two absences appear in every report and are structural rather than faults:
per-node ready times (the lifecycle records no per-node timestamp) and per-node
resource ranking (resource observation aggregates per sampler). Do not
approximate either from a stage total.

One thing to check when reading the fault section: the nine scenarios each report
their own duration, and `failover_details` is a **single** measurement from the
primary-kill lane. If you ever see nine identical client-outage values, that is a
known regression returning.

## §9 If it fails

**Stop and audit. Do not relaunch.**

Five paid 1280-node runs were each spent finding one defect, one at a time. The
rule that came out of it: state the expected number of runs before the first one,
and when one fails, audit the *class* of the defect rather than launching again.
The expected number of runs here is **one** - one run, instrumented from the
first second, which either passes or yields a complete diagnosis.

To stop a run:

```bash
sh scripts/fleet_run.sh abort
```

Kill and reclaim are **one move**, and the order matters. The cluster bus is
peer-to-peer, so killing the controller relieves nothing - the nodes carry on
gossiping, and the heaviest link-freeing was sampled *after* the controller died.
`abort` kills the run by pid and immediately reclaims every host from the run's
own state.

Never `pkill -f` a pattern broad enough to match the run: it also matches the
shell you typed it into.

Two things to know before you diagnose:

- **A failing run collects no node journals and writes no lifecycle timeline.**
  The failures that would help most are cluster-formation ones. Its report is
  therefore thinner than a passing run's, and that is a known gap rather than
  something the wrapper is hiding.
- **If the fault lane fails, check the deadline before you suspect the cluster.**
  This configuration sets `cluster_node_timeout_ms: 60000`, and failover recovery
  time scales with it. The canary recovery deadline is a hardcoded 180 seconds. At
  60000 a small cluster recovered in about 95 s; at 120000 it lands near 190 and
  fails outright. An observed time above 180 s is that deadline being reached.

## §10 What a result here does and does not compare to

- **This repository's 45-50 s failover band does not apply to a run taken with
  this file.** Every fault-lane number recorded here was taken at
  `cluster_node_timeout_ms: 30000`; this configuration uses 60000, and the only
  anchor at that value is about 95 s on a small cluster.
- **Rank on the split, not on the aggregate.** One aggregate recovery time per
  run cannot separate cluster sizes: measured on one afternoon, the aggregate
  moved 6.7 % between 50 and 200 nodes while the control-plane term moved
  sevenfold.
- **A run with four replicas per shard is a new comparison class.** It cannot be
  diffed against this repository's one-replica baselines in nodehost placement,
  run state, the fault lane's targets, or the cleanup report.

## §11 Everything this procedure runs, in one list

| step | command |
|---|---|
| pinned image | `./scripts/build_valkey_image.sh` |
| bundle | `./scripts/build_native_bundle.py` |
| manifest | `./scripts/make_fleet_manifest.py ... --out artifacts/host-fleets/<id>/inventory.json` |
| host preparation | `sudo sh scripts/ecs_host_prepare.sh` on each host |
| host check | `sh scripts/ecs_host_verify.sh --nodes-per-host 40 --fleet-nodes 1280 --bundle DIR` |
| preflight | `sh scripts/fleet_run.sh preflight --config ...` |
| launch | `sh scripts/fleet_run.sh start --config ...` |
| watch | `sh scripts/fleet_run.sh watch` |
| stop | `sh scripts/fleet_run.sh abort` |
| acceptance | `./gate milestone m4` - **this launches the paid run**, see below |

`./gate milestone m4` runs M4's registered checks, and one of them is the
1280-node run itself, carrying the operator opt-in and cost acknowledgement in
its own argv. On a controller with a live manifest **invoking it spends the
money**. That is deliberate - the milestone's acceptance *is* the run, and the
alternative was a milestone that could never be accepted by any command - but it
is not something to discover by typing it.
