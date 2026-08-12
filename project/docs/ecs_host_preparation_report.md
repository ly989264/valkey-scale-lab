# Preparing a fleet host for M3-B

Host preparation only. This is not roadmap item 1.6, it changes no product code,
and it deliberately bakes no Valkey, no memtier and no run state, so that the
existing native bundle deployment path is still exercised for the first time on
the fleet.

Two scripts, both run on the host as root:

| | |
|---|---|
| `scripts/ecs_host_prepare.sh` | prepares a stock host; idempotent; `--finalize-image` for the bake |
| `scripts/ecs_host_verify.sh` | answers whether a host is ready for the existing `native_multi_ecs` backend |

Derived from the implementation and **measured on two real Google Compute Engine
`c4a-standard-2` instances** (arm64, 2 vCPU, 7.9 GiB, stock `ubuntu-26-04-lts`).
Both finish `READY`, every required check passed, zero advised.

`ecs` names the *role* the roadmap gives these hosts and the backend that drives
them, not a cloud. An earlier revision of this document targeted CentOS 8.2.2004;
that base was abandoned because it could not run the pinned bundle at all
(glibc 2.28 against a requirement of 2.38) and its OpenSSH 8.0p1 refused two
transport shapes the backend depends on. Both problems are absent on Ubuntu
26.04. The derivation in §2 is base-independent and carried over unchanged.

---

## 1. How eight hosts get built: a startup script, not an image

**`scripts/ecs_host_prepare.sh` is the single definition of what a fleet host
is.** Everything else is a way of delivering it.

The original plan was a golden image. It ran into a GCE constraint: **machine
images do not support Hyperdisk Balanced**, which is the only boot disk a C4A
instance takes. Two things follow, and they point the same way.

First, the distinction that matters if you still want an image — they are
separate features and only one is restricted:

| | what it captures | Hyperdisk |
|---|---|---|
| `gcloud compute machine-images create` | whole instance: all disks, config, metadata | not supported |
| `gcloud compute images create --source-disk` | one disk, as a reusable OS image | the normal golden-image path |
| `gcloud compute snapshots create` then `images create --source-snapshot` | via a snapshot | the fallback |

Second, and the reason this document now recommends the startup script instead:
the objection to per-host preparation turned out to be measurable, and it
measured zero. **Two hosts prepared independently came out with all six managed
files byte-identical and the same 622 packages.** `ecs_host_verify.sh` run on
each host is the gate that catches divergence rather than assuming it away, and
`apt` on GCE talks to a regional mirror rather than the 90 kB/s the CentOS
revision of this work was fighting.

A startup script also keeps the property the image was for: one definition, with
nothing that can drift from it. `scripts/ecs_host_startup_metadata.sh` embeds
`ecs_host_prepare.sh` verbatim and adds only the two things a startup script must
do that a hand-run need not — place the fleet public key and leave a completion
marker:

```bash
./scripts/ecs_host_startup_metadata.sh fleet_key.pub > startup.txt
gcloud compute instances create vslab-host-0{1..8} \
    --image-family ubuntu-2604-lts-arm64 --image-project ubuntu-os-cloud \
    --machine-type c4a-standard-4 --zone ZONE \
    --metadata-from-file startup-script=startup.txt
```

GCE runs a startup script on every boot; the prepare script is idempotent and,
once the packages are in, does not even reach `apt-get update`.

**One reboot, at most.** `/tmp` can be taken off tmpfs live — measured, `mask`
plus `stop` moved it to the root filesystem with 36 G free while the host stayed
up — but only when nothing holds a file open under `/tmp`, which at first boot
is not guaranteed. The generated startup script therefore reboots **once**,
guarded by its own marker, if `/tmp` is still tmpfs when it finishes. Measured
end to end on a real instance: boot 1 decided to reboot, boot 2 completed with
`/tmp` on disk, and a third run took no further action.

## 2. How the requirement list was derived

Not from a checklist. Every requirement traces to a site in the current
implementation — `runtime/native_backend.py` (2029 lines),
`runtime/host_transport.py`, `runtime/host_clock.py`, `runtime/native_bundle.py`
and the bundle-script generator in `runtime/docker_runtime.py` — and was then
checked by running that code against a live host over ssh.

Reading alone would have got three things wrong:

- A stock CentOS 8 has `python3` *present* (3.6.8) and it cannot import the
  resource agent at all. A package-presence check would have passed.
- `libevent-2.1-7t64` supplies only `libevent` and `libevent_core`; memtier needs
  four sonames. My first package list was short by three, and only running the
  binary showed it.
- `sudo` appears **nowhere** in `runtime/` — see §4.2.

### 2.1 The control channel — `host_transport.py`

| requirement | site |
|---|---|
| sshd, key-only (`BatchMode=yes`, so a prompt is a hang) | `MultiplexedSshTransport._ssh_argv` |
| one persistent master per host, many sessions over it | `ControlMaster=auto`, `ControlPersist=600` |
| `StrictHostKeyChecking=yes`, a *distinct* key per host | `_ssh_argv`; see §5.1 |
| `scp -r` in both directions | `put`, `get`; needs `expand-path@openssh.com` |
| the host reports its own control port | `isolate_nodehost` reads `$SSH_CONNECTION` |

### 2.2 Programs the remote scripts name

Twenty-one, extracted from the shell fragments the backend builds:

`sh` · `printf` · `ls` · `head` · `mkdir` · `rm` · `touch` · `cat` · `test` ·
`readlink` · `sleep` · `wc` · `seq` · `cut` · `sha256sum` · `tar` · `gzip` ·
`awk` · `nohup` · `ip` · `iptables` · `python3`

**All twenty-one are present on the stock GCE Ubuntu 26.04 image.** (The bare
`ubuntu:26.04` container image is a different thing and lacks five, so the
script still names them all.)

Notable derivations, unchanged from the CentOS revision because they come from
the product: `iptables` must support `-m comment`, because a chain name is
capped at 28 characters and a run id is 42, so the run's ownership mark lives in
the comment; `ip route get` is the whole of `create_network`; and `readlink` on
`/proc/<pid>/cwd` is the ownership mark for a process, because Valkey rewrites
its process title.

### 2.3 python3

`HOST_CLOCK_ARGV` is `python3 -c "import time;print(repr(time.time()),repr(time.monotonic()))"`,
and §11.1's sampler runs as `python3 -m valkey_scale_lab.observability.resource_agent`.
The floor is 3.7, because every product module opens with
`from __future__ import annotations`.

This image ships **3.14.4** — ahead of the 3.13 the product is developed on,
which was a real risk. Measured on the host: the agent imports, `HOST_CLOCK_ARGV`
returns two floats, and `LocalResourceSampler.host_sample()` runs.

### 2.4 Filesystem roots

`/opt/valkey-scale-lab/bundles` (`NATIVE_INSTALL_ROOT`, binaries are executed
from here), `/tmp/valkey-scale-lab` (`RUN_STATE_ROOT`) and `/tmp`
(`BUNDLE_DROP_ROOT`). The verifier proves each is writable **and exec-capable**
by writing and running a probe.

---

## 3. The bundle runs here, unmodified

The single most important measurement, taken on a real instance through the
product's own install path:

```
valkey-server        Valkey server v=9.1.0 sha=00000000:0 malloc=jemalloc-5.3.0
valkey-cli           valkey-cli 9.1.0
memtier_benchmark    memtier_benchmark v=2.5.1 sha=00000000:0 bits=64
CLUSTER MYSLOTS      node-id ebbeffb1… shard-id 78660c72… role …
```

`valkey-server` and `valkey-cli` link and run on a **completely stock** image
with nothing installed — glibc 2.43 against the bundle's 2.38 requirement,
`libssl.so.3`, `libsystemd.so.0` and `libstdc++.so.6.0.35` all already present.
Only memtier needed anything, and the four `libevent` sub-packages are the whole
of it.

**`CLUSTER MYSLOTS` answers**, which closes the one check `verify_native_bundle`
explicitly declines to make (`not_verified.cluster_myslots_command`): under
Docker the preflight starts a server and asks it, while a bundle verifier can
only hash bytes on the controller. On a host it can be asked, and the verifier
now does.

The bundle is **arm64**, and so are these instances. Keeping the real fleet on
arm64 keeps M3-B to one changed variable — every M3-A measurement, both frozen
Docker baselines and all four simulated native runs, is arm64. `architecture` is
a field in `bundle_manifest.json`, is returned as preflight evidence, and is
carried into the `runtime_start` diff view, so an x86_64 fleet would change it in
every artifact of every run.

---

## 4. Two findings that change the fleet's shape

### 4.1 The guest agent de-provisions accounts, not just keys

Measured twice, on both instances, and it cost this exercise two lockouts.
`google-guest-agent` manages the accounts it provisions from instance metadata.
Its own journal, verbatim:

```
ERROR invalid ssh key entry - expired key: ly989264:... expireOn 2026-08-12T04:36:26
Removing user ly989264.
gpasswd[2080]: user ly989264 removed by root from group google-sudoers
```

The browser SSH console injects **short-lived** keys into metadata; when they
lapse, the agent removes the account — login, then sudo. A key appended to
`~/.ssh/authorized_keys` by hand authenticated once and was gone within minutes.

The fleet manifest carries a **static** key and `MultiplexedSshTransport` runs
with `BatchMode=yes`, so this does not degrade — it fails every host at once,
mid-run, and looks like the network.

The fix the image carries is a second authorized-keys location the agent does
not manage:

```
AuthorizedKeysFile .ssh/authorized_keys /etc/ssh/vslab_authorized_keys/%u
```

Proven, not assumed: `~/.ssh/authorized_keys` was **emptied completely** and
login still succeeded. Console SSH and `gcloud compute ssh` keep working through
metadata unchanged. The image ships the directory and the drop-in and **no key** —
a fleet key baked into an image is a key on every host forever.

### 4.2 The manifest user must be root

`sudo` appears nowhere in `runtime/` — measured by grep over the whole package.
The backend runs every command as the manifest user directly, and those commands
write under `/opt`, install iptables chains, read `/proc/<pid>/cwd` for processes
they do not own, and signal them.

A sudo account would require the product to prepend `sudo`, which would change
the `argv` of every row in the command log — and `argv` is precisely what the
equivalence diff compares field by field (slice map §14.5). So that is not a
change to make lightly, and not one host preparation may make at all.

This also matches the simulated fleet, whose `SSH_USER` is `root`, and whose
Dockerfile states the same reasoning: *"root is what this harness offers because
the partition actuator needs NET_ADMIN and adding a sudo path would be surface
with nothing behind it."*

So the fleet's `control_endpoint.user` is **root**, the operator places the fleet
public key at `/etc/ssh/vslab_authorized_keys/root`, and GCE's stock
`PermitRootLogin prohibit-password` already permits exactly that. The prepare
script creates no user and reports the effective `PermitRootLogin` rather than
changing it.

---

## 5. What the stock image gets right, and what needed fixing

Free on Ubuntu 26.04 GCE, and each was a fight on CentOS 8.2:

- **cgroup v2 already active** — no kernel argument, no reboot.
- **`Include /etc/ssh/sshd_config.d/*.conf`** at line 24 — a real drop-in.
  The `10-` prefix matters: sshd keeps the *first* value it sees and the image
  ships `50-` and `60-cloudimg-settings.conf`.
- **`expand-path@openssh.com`** advertised by the sftp-server, so `scp -r` from
  an OpenSSH ≥ 9 controller can create remote directories.
- **All 21 backend commands** present.
- **`net.core.somaxconn` already 4096.**

Fixed by the script, each measured stock first:

| | stock | after |
|---|---|---|
| `/tmp` | **tmpfs, 3.9 G** | ext4, 36 G |
| `nofile` in an ssh session | **1024** | 1048576 |
| `vm.overcommit_memory` | **0** | 1 |
| transparent huge pages | `madvise` | `never` |
| `MaxSessions` | 10 | 64 |
| ufw | active | disabled and masked |
| unattended-upgrades | active | disabled and masked |
| `net.ipv4.ip_local_port_range` | 32768–60999 | 10240–65535 |
| memtier's libevent sonames | 1 of 4 | 4 of 4 |

The `/tmp` one is a measurement problem more than a capacity one.
`RUN_STATE_ROOT` and `BUNDLE_DROP_ROOT` are both under `/tmp`, so every node's
data directory, RDB and journal lands there. On tmpfs that is RAM, held in page
cache and counted against the very `MemAvailable` the §11.1 sampler reports — the
run's memory evidence would conflate dataset storage with process footprint. The
simulated baselines were taken with `/tmp` on disk. `tmp.mount` is masked, which
is reversible with one `systemctl unmask`.

`vm.overcommit_memory` is not speculative: **valkey-server printed the warning
itself** on this host — `WARNING Memory overcommit must be enabled!`

### 5.1 Host keys

`--finalize-image` removes `/etc/ssh/ssh_host_*`, and cloud-init regenerates
them per instance at first boot. Roadmap item 1.0 found a simulated fleet where
both hosts served **one** fingerprint because their keys were generated during
the image build; an image bake is where that defect gets manufactured at scale.

---

## 6. Measured on the real fleet

Driven through the product's own modules — `MultiplexedSshTransport`,
`host_clock`, `native_backend`'s own script builders — against both instances.

### 6.1 The partition actuator works on a real network

Against a listener on `7800`, the port `native_200.yaml` actually uses:

```
before partition   host-b -> host-a:7800    reachable 0.7 ms
during partition   host-b -> host-a:7800    unreachable: TimeoutError
                   control channel                     still answers
after rejoin       host-b -> host-a:7800    reachable 0.1 ms
                   residue scan                        silent
```

The `85d5096a` cross-backend invariant — the isolated side must be *unreachable*
— holds on real hardware, and the control channel is spared because the port is
read from `$SSH_CONNECTION` rather than from the manifest.

A first attempt at this measured port **22** and reported "STILL REACHABLE",
which is the one port the actuator deliberately spares. The test was wrong, not
the actuator. Recorded because a later reader may make the same mistake.

Also banked: the default VPC's `default-allow-internal` rule already permits
7800 between instances, so the cluster's client and bus port ranges need no
additional firewall rule in the default VPC.

### 6.2 `create_network` would accept this fleet

`ip route get` succeeds in both directions between `10.148.0.2` and
`10.148.0.3`, and a TCP connect between them takes **0.1–0.8 ms**.

### 6.3 The controller must live in the VPC — a finding for item 1.6

| | median | p90 |
|---|---|---|
| controller (laptop) → host, multiplexed | **110–116 ms** | 118 ms |
| host → host, same subnet | **0.1–0.8 ms** | — |

The budget is the rolling restart's own two backend operations, **71 ms and
61 ms** median, taken from the frozen baseline. A laptop controller is *over
budget on every single command*. A native exact-200 issues **3037
`runtime_command` rows**; at 110 ms that is ~5½ minutes of pure round trip
against the 25.7 s measured on the simulated fleet.

So M3-B's controller should be a GCE instance in the same subnet, not a
workstation. This is not a property of the transport — inter-host latency shows
the network is fast — and it does **not** reopen M3-A-2's multiplexed-ssh
decision; it says where the controller has to sit. The real per-operation
transport number still has to be re-measured from an in-VPC controller before
the decision point can be called closed.

### 6.4 Real clock offsets, and why the bound was the right design

| | offset | bound | round trip |
|---|---|---|---|
| host-a | +39.12 ms | ±61.50 ms | 123.0 ms |
| host-b | +38.54 ms | ±58.54 ms | 117.0 ms |

Zero lies inside the bound on both, which is correct: these hosts run chrony
against Google's NTP and their true offset from each other is small, while the
*controller* is 110 ms away and the estimator's uncertainty is dominated by that
round trip. This is exactly the case `host_clock.py` was designed for — a
threshold calibrated on the simulated fleet (+4.7 to +7.9 ms inside a 15–21 ms
bound) would have failed here, and the bound did not. Expect the bound to shrink
by two orders of magnitude once the controller is in-VPC, at which point real
inter-host skew becomes visible for the first time.

### 6.5 An evidence-shape delta to declare before freezing baselines

`LocalResourceSampler.host_sample()` populates **2 of 6 cgroup fields** on a real
VM — `cpu_usage_usec` and `cpu_throttled_usec` yes, `memory_current_bytes`,
`memory_max_bytes`, `oom_count`, `oom_kill_count` **null**. Under Docker all six
populate, because a container *is* a delegated child cgroup, whereas on a VM the
sampler reads the **root** cgroup, which does not expose the memory files.

Every simulated baseline carries six. The real baselines item 1.6 freezes will
carry two. That is a vocabulary delta of exactly the kind
`simulated_ladder_slice_map.md` §6 requires to be declared *in advance*, and it
is not drift. The verifier reports the count so it cannot be discovered late.

---

## 7. What was proven

- **Prepare is idempotent**: on a prepared host, a second run reports every step
  as already done and leaves all managed files byte-identical and the package
  set unchanged. Three log lines originally *claimed* to change an already-changed
  host — `systemctl is-enabled` exits non-zero for `masked` while still printing
  it, so the obvious `$(… || echo x)` never compares equal. Fixed, because a
  report that misstates what changed is worse than none.
- **Reproduction on a second host**: instance 1 went from `NOT READY, 5 required,
  8 advised` to `READY, 0 required, 0 advised` with one run plus a reboot, and
  ends byte-identical to instance 2.
- **Everything survives a reboot**, including the fleet account, `/tmp` on disk,
  THP `never`, `overcommit=1`, and `nofile` 1048576 in a fresh ssh session.
- **The verifier is calibrated, not merely agreeable**: it reported the true
  pre-prepare state on both hosts, and its `recursive upload` check passes on
  Debian 13 and fails on CentOS 8.2 — a positive and a negative control.
- Two real bugs in the prepare script were caught by running it: the
  `ip_local_port_range` sysctl was mangled by `tr -d ' '` collapsing its two
  values into one, and the libevent package list was short by three.
- `./gate suite repository.all` **92/92** — no product code was touched.

---

## 8. Creating the fleet

The startup-script route of §1 needs no image and no manual step per host.

If you would rather have an image anyway — it boots faster and removes `apt`
from the boot path — build it from a **stock** instance, never from one that has
been worked on:

```bash
# on a fresh instance, as root
sh ecs_host_prepare.sh
sh ecs_host_verify.sh --bundle <bundle dir> --package <src dir>   # must print READY
sh ecs_host_prepare.sh --finalize-image
# then: stop the instance and `gcloud compute images create --source-disk`
```

`--finalize-image` removes the ssh host keys, any fleet key, run state, bundles,
`machine-id`, cloud-init state, the apt cache and logs. **It removes your own
access**, so run it immediately before stopping the instance. It deliberately
does *not* delete user accounts or arbitrary directories — a script that removes
users it did not create is not one to run on a host you care about — which is
exactly why the instance you image should be a stock one. The two instances this
work was done on accumulated three stray accounts, one of which
(`vslab-m3b`) the guest agent created by itself from an ssh key's *comment*.

Either way, each host still needs the fleet public key at
`/etc/ssh/vslab_authorized_keys/root`, and the manifest's `control_endpoint`
names `user: root`. The startup script places it; with an image, use a startup
script for that one file, or accept that baking the key in makes the image a
credential that cannot be rotated without rebuilding it.

For eight hosts, remember the fleet arithmetic: `nodehosts_per_az` is 2 over two
AZs and `max_logical_nodes_per_nodehost` is 25, so exact-200 plans 8 nodehosts
and a native run places **exactly one per host and refuses otherwise**. The AZs
should be real availability zones or the fault evidence describes a topology that
never held. Sizing measured from the native exact-200 run: 25 nodes/host at
~355 MiB summed RSS, ~10,300 descriptors, 0.13–0.48 cores busy in steady state;
**4 vCPU / 8 GiB** recommended, since only steady state is measured and
formation, the rolling restart and the fault matrix are not.

---

## 9. What still cannot be validated here

1. **Anything about a running cluster.** No Valkey cluster has been formed on
   these hosts. Formation dwell, RTO, the fault lane's 9/12/15 and the health-gate
   escalation of slice map §16 are all untouched.
2. **The per-operation transport number from an in-VPC controller** — §6.3. The
   110 ms here is a laptop-to-Singapore number and must not be quoted as a fleet
   number.
3. **Real inter-host clock skew** — §6.4. It is currently buried under the
   controller's round trip.
4. **Transport-failure classification across a VPC**, which the roadmap keeps
   open and which two healthy hosts cannot produce.
5. **Eight hosts.** Everything here is two. Nothing about `MaxStartups`, the
   conntrack table or the descriptor ceiling has been tested at fleet width.
6. **The image itself.** Both hosts were prepared in place; no instance has yet
   been booted *from a snapshot*, so cloud-init's host-key regeneration and the
   absence of a baked fleet key are reasoned rather than measured. That is the
   first thing to check on the first instance created from the image.
