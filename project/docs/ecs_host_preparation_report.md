# Preparing a CentOS 8.2.2004 host for M3-B

Host preparation only. This is not roadmap item 1.6, it changes no product code,
and it deliberately bakes no Valkey, no memtier and no run state, so that the
existing native bundle deployment path is still exercised for the first time on
the real fleet.

Two scripts, both run on the host as root:

| | |
|---|---|
| `scripts/ecs_host_prepare.sh` | prepares a pristine host; idempotent; `--finalize-image` for the bake |
| `scripts/ecs_host_verify.sh` | answers whether a host is ready for the existing `native_multi_ecs` backend |

**The headline is not a package list.** Everything a host-preparation script can
install, installs. What it cannot fix is that **the pinned native bundle cannot
run on CentOS 8.2.2004 at all**, and that **CentOS 8.2's OpenSSH 8.0p1 refuses
two transport shapes the backend depends on**. Both were found by running the
real implementation against a real host, both are quantified in §3 and §4, and
neither is a host-preparation problem. They are decisions for you before the
fleet is provisioned.

---

## 1. How the requirement list was derived

Not from a checklist. Every requirement below traces to a site in the current
implementation, found by reading `runtime/native_backend.py` (2029 lines),
`runtime/host_transport.py`, `runtime/host_clock.py`, `runtime/native_bundle.py`
and the bundle-script generator in `runtime/docker_runtime.py`, and then
**checked by running that code against a live CentOS container over ssh**.

Reading alone got two things wrong, and only running caught them:

- `python3` is *present* on a stock CentOS 8 (3.6.8 as `platform-python`), and a
  package-presence check would have passed. It cannot import the resource agent.
- `scp` is present, `sshd` is present, the sftp subsystem is configured — and a
  recursive upload from the controller still fails.

## 2. What the implementation actually requires, and where it says so

### 2.1 The control channel — `host_transport.py`

| requirement | site | on pristine CentOS 8.2 |
|---|---|---|
| sshd, key-only (`BatchMode=yes`, so a prompt is a hang) | `MultiplexedSshTransport._ssh_argv` | **absent** — `openssh-server` not installed |
| one persistent master per host, many sessions | `ControlMaster=auto`, `ControlPersist=600` | stock `MaxSessions 10`; raised to 64 |
| `StrictHostKeyChecking=yes`, a *distinct* key per host | `_ssh_argv` | see §5.1 |
| `scp -r` both directions | `put`, `get` | **broken** — §4.1 |
| the host reports its own control port | `isolate_nodehost` reads `$SSH_CONNECTION` | sshd sets it; verified over a real session |

### 2.2 Programs the remote scripts name

Twenty-one, each named by a specific operation. Extracted from the shell
fragments the backend builds, not guessed:

`sh` · `printf` · `ls` · `head` · `mkdir` · `rm` · `touch` · `cat` · `test` ·
`readlink` · `sleep` · `wc` · `seq` · `cut` · `sha256sum` · `tar` · `gzip` ·
`awk` · `nohup` · `ip` · `iptables` · `python3`

On a pristine `centos:centos8.2.2004`, **19 are present and 2 are absent**:
`iptables` and `python3`. `ip` is present (iproute), `awk` is gawk, and the
coreutils set comes from `coreutils-single`.

Notable derivations:

- **`iptables` with `-m comment`** is not optional decoration. A chain name is
  capped at 28 characters and a run id is 42, so the run's ownership mark lives
  in the rule comment and both cleanup paths find rules by it
  (`fault_rule_tag`, `_remove_fault_rules`, `_scan_fault_rules`). Measured
  working on CentOS: `iptables v1.8.4 (nf_tables)`, the chain plus two
  comment-marked jumps installed, confirmed with `-C`, found again by
  `iptables -S`, and removed leaving nothing.
- **`ip route get`** is the whole of `create_network`: it asks each host for a
  route to every peer and refuses the fleet if any pair has none.
- **`readlink` on `/proc/<pid>/cwd`** is the ownership mark for a process,
  because Valkey rewrites its process title. Measured on CentOS: the real
  `_owned_process_walk` found two planted processes by working directory,
  `_signal_owned_processes` signalled both with `CONT` before `TERM`, and
  `_await_owned_processes_gone` reported zero left.

### 2.3 python3 — and why the stock one is not enough

`HOST_CLOCK_ARGV` is `python3 -c "import time;print(repr(time.time()),repr(time.monotonic()))"`,
and §11.1's sampler runs as `python3 -m valkey_scale_lab.observability.resource_agent`.

The agent's transitive import closure inside the package is five modules:
`valkey_scale_lab/__init__`, `observability/__init__`, `observability/contracts`,
`observability/resources`, `observability/resource_agent`.

Measured on the stock interpreter:

```
$ /usr/libexec/platform-python -c 'import valkey_scale_lab.observability.resource_agent'
  File ".../observability/contracts.py", line 1
    from __future__ import annotations
SyntaxError: future feature annotations is not defined
```

CentOS 8's `python3` is **3.6.8**; `from __future__ import annotations` needs
3.7. The prepare script enables the `python38` module stream and points the
`python3` alternative at 3.8.0. Measured after that: the agent imports, and it
**runs on the host and writes samples** — five samples with a process row for a
planted pid, collected back over the transport.

### 2.4 Filesystem roots

Read off the implementation, not chosen:

| root | constant | requirement |
|---|---|---|
| `/opt/valkey-scale-lab/bundles` | `NATIVE_INSTALL_ROOT` | `valkey-server` is executed from here — must permit exec |
| `/tmp/valkey-scale-lab` | `RUN_STATE_ROOT` | node data dirs, journals, resource agent, the copied package |
| `/tmp` | `BUNDLE_DROP_ROOT` | the bundle archive is staged here and the run bundle lands here |

The prepare script creates the install root root-owned 0755; the verify script
proves each root is writable **and exec-capable** by writing and running a probe,
because `noexec` on `/opt` or `/tmp` is a real cloud-image default that would
stop `valkey-server` before it started.

### 2.5 Headroom, at the density the planner will actually place

A native run places exactly one nodehost per host and
`max_logical_nodes_per_nodehost` is 25, so a fleet host carries **25
valkey-server processes**, each defaulting to `maxclients 10000`. The generated
node config sets no `save` directive, so Valkey's built-in policy is live and a
background save forks a process holding a dataset — the mechanism roadmap
`313cacc9` traced a real failure to.

The prepare script writes `nofile 1048576`, `fs.file-max`, `somaxconn 4096`,
`vm.overcommit_memory=1`, an ephemeral port range, `nf_conntrack_max`, a THP-off
unit, and requests cgroup v2 on the kernel command line. None of these is
required for the backend to *function*; all of them keep a capacity result from
being a fact about the host's stock limits.

---

## 3. The bundle cannot run here — measured, and not fixable by host prep

The pinned bundle's binaries are built in the pinned image's `binaries` stage,
which is **Debian 13 (trixie), glibc 2.41**. CentOS 8.2.2004 is **glibc 2.28**.

Copied onto a prepared CentOS host and executed through the product's own
install path (which succeeded — the digest was verified on the host and the
archive extracted), `valkey-server` fails at exec:

```
valkey-server: error while loading shared libraries: libssl.so.3:
cannot open shared object file: No such file or directory
```

The full gap, from `ldd` on the host:

| the bundle requires | CentOS 8.2.2004 ceiling | closable by any 8.2 package? |
|---|---|---|
| `GLIBC_2.29, 2.32, 2.33, 2.34, 2.38` | `GLIBC_2.28` | no |
| `GLIBCXX_3.4.29, 3.4.32` | `GLIBCXX_3.4.25` (libstdc++ 8.3.1) | no |
| `libssl.so.3`, `libcrypto.so.3` | `libssl.so.1.1`, `libcrypto.so.1.1` (openssl 1.1.1c) | no |
| `libevent{,_extra,_openssl,_pthreads}-2.1.so.7` | `…-2.1.so.6` (libevent 2.1.8) | no |

Unresolved symbols and sonames per binary: **valkey-server 8, valkey-cli 7,
memtier_benchmark 11**.

This is a build-target mismatch, not a missing package. **No host-preparation
script can close it**, and I have not tried to: baking newer libraries onto the
host would be exactly the "bake Valkey/memtier into the image" you ruled out,
one layer down.

What the prepare script *does* do is install the CentOS 8.2 runtime libraries a
bundle **rebuilt against this host** would link: `openssl-libs`, `libevent`,
`systemd-libs`, `libstdc++`, `zlib`. Verified present with their sonames. That
is the host side of the fix; the build side is yours.

**The options, not pre-decided:**

1. Add a CentOS 8.2 builder stage to `docker/valkey-custom/Dockerfile` and build
   the bundle there. Keeps the 8.2 pin. Changes the pinned build's definition,
   which `build_native_bundle.py`'s header says must have exactly one.
2. Pick a newer base for the ECS image whose glibc is ≥ 2.38. Abandons the 8.2
   pin and — see §4 — also happens to fix both transport problems.
3. Build statically or vendor the libraries. Changes what "the pinned build"
   means and the digests that bind it into every run's provenance.

## 4. Two transport shapes CentOS 8.2's sshd refuses

Both found by driving `MultiplexedSshTransport` from this controller
(macOS, **OpenSSH 10.2p1**) against a prepared CentOS host, with the Debian 13
simulated host (**OpenSSH 10.0p2**) as a positive control.

### 4.1 `scp -r` cannot create a remote directory

An OpenSSH ≥ 9 controller's `scp` drives transfers over the **sftp protocol**,
and canonicalizes the target with the `expand-path@openssh.com` extension.
Measured by one SFTP INIT exchange against each host's `sftp-server`:

| host | sftp-server extensions | `expand-path@openssh.com` |
|---|---|---|
| Debian 13 / OpenSSH 10.0p2 | 11 advertised | **yes** |
| CentOS 8.2 / OpenSSH 8.0p1 | 6 advertised | **no** |

Consequence, measured with real transfers:

```
put file  -> new remote path      OK
get file  -> local                OK
put dir   -> new remote path      scp: realpath /tmp/t1: No such file
                                  scp: upload "/tmp/t1": path canonicalization failed
put dir   -> existing parent/     same failure
```

Two seam call sites do exactly this and would fail:

- `send_bundle` — `transport.put(bundle_artifact_dir, f"{BUNDLE_DROP_ROOT}/")`
- `NativeResourceAgent.start` — `transport.put(package, f"{root}/valkey_scale_lab")`

Legacy mode (`scp -O`) fixes both puts — measured — but **breaks `get`**:
`NativeLoadLaneHost.collect_evidence` fetches `f"{remote_dir}/."`, and legacy
scp rejects it with `error: unexpected filename: .`. So `-O` is not a drop-in
switch; any fix has to be per-direction. That is a `_scp_argv` change and
belongs to whoever owns the transport, not to host preparation.

`ecs_host_verify.sh` checks this directly by asking the host's own sftp-server
for its extension list — not by running the host's `scp`, which is 8.0 and still
speaks the legacy protocol and would measure the wrong client. The check is
calibrated by a positive control: it passes on the Debian simulated host and
fails on CentOS.

### 4.2 A backgrounded child holds the session open

`NativeResourceAgent.start` launches the sampler as
`nohup python3 -m … >log 2>&1 & echo $! > pidfile`. Through
`MultiplexedSshTransport`, back to back, three trials:

```
trial 1  CentOS-8.2    HUNG (>6s)      trial 1  Debian-13   rc=0 in 0.02s
trial 2  CentOS-8.2    HUNG (>6s)      trial 2  Debian-13   rc=0 in 0.02s
trial 3  CentOS-8.2    HUNG (>6s)      trial 3  Debian-13   rc=0 in 0.02s
```

On CentOS the session never closes, so the operation runs to its own 120 s
timeout and raises. Reproduced with the real agent, not only with a stand-in.

A fully detached form does return — `setsid sh -c '… & echo $! > pidfile'` with
all three fds redirected, rc=0 in 0.58 s with the agent running — but it is not a
free substitution: the extra process layer means `$!` no longer names the agent,
and `stop()` kills `$(cat agent.pid)`, so the pidfile contract breaks with it.
Again a product decision, not a host one.

**This is deliberately *not* a check in `ecs_host_verify.sh`.** Run locally with
the host's own ssh client, the same command hangs against *both* hosts —
including the Debian fleet that has passed four real native runs. A check that
fails on a known-good host is worse than no check. The measurement stays a
controller-side one; reproduce it with the transport against a real endpoint.

---

## 5. What the prepare script does, and two things it deliberately does not

### 5.1 Host keys are removed, not generated, under `--finalize-image`

Roadmap item 1.0 found a simulated fleet where **both hosts served one ssh host
key fingerprint**, because Debian's `openssh-server` postinst generated keys
during the *image build* and they sat in a shared layer. An ECS custom image is
that same defect at fleet scale. So `--finalize-image` removes
`/etc/ssh/ssh_host_*`; CentOS 8's `sshd-keygen@.service` regenerates them per
instance at first boot. It also clears `authorized_keys`, `known_hosts`,
`machine-id`, the dnf cache, and any run state or bundle left behind.

`ecs_host_verify.sh` reports both states as acceptable and says which it sees:
keys present means a live host, keys absent with `sshd-keygen` available means a
baked image.

### 5.2 Nothing run-specific and no Valkey

No `authorized_keys` (yours to place per instance), no fleet manifest, no run id,
and no `valkey-server`, `valkey-cli` or `memtier_benchmark`. This is the same
reason `docker/simulated-host/Dockerfile` *removes* what it inherits: a host that
already carried the binaries would make the bundle install unfalsifiable.

### 5.3 Three findings from making it work on a pristine host

- **The stock repositories are dead.** CentOS 8 is EOL and `mirrorlist.centos.org`
  does not resolve, so every `dnf install` fails before it starts. The script
  pins `https://vault.centos.org/8.2.2004/{BaseOS,AppStream,extras}` — the point
  release, not `$releasever`, because the host and the bundle have to agree on a
  glibc and `8` would drift. It only rewrites the repos if the existing ones
  cannot fetch metadata, so a vendor mirror that works is left alone.
- **`dnf install coreutils` aborts the whole transaction.** The stock image
  carries `coreutils-single`, which supplies every command the remote scripts
  name and *conflicts* with `coreutils`. Requested only when neither is present.
- **CentOS 8.2's OpenSSH 8.0p1 has no `Include`** — it exits with
  `Bad configuration option: Include`, and there is no `sshd_config.d`. Appending
  does not work either, because sshd keeps the *first* value it sees and the
  stock file sets `PasswordAuthentication yes` at line 85. The script therefore
  manages a marker-delimited block at the *top* of `sshd_config`, validated with
  a throwaway host key before it is installed. `Subsystem` is the one keyword
  sshd refuses twice (`Subsystem 'sftp' already defined`), so it is emitted only
  when the stock file defines none.

---

## 6. What was proven, and on what

### 6.1 Clean-room reproduction

Both scripts were developed against one container and then re-run from scratch on
**a second and a third pristine `centos:centos8.2.2004`**, which is the check that
matters — none of the development container's state was carried over.

```
docker run -d --name host --cap-add NET_ADMIN centos:centos8.2.2004 sleep infinity
docker cp scripts/ecs_host_prepare.sh host:/root/
docker cp scripts/ecs_host_verify.sh  host:/root/
docker exec host sh /root/ecs_host_prepare.sh
docker exec host sh /root/ecs_host_verify.sh --bundle /root/bundle
```

On the third container, starting from `sshd`, `iptables`, `python3` and `scp` all
absent:

- **prepare, run 1**: repos repointed to vault, packages installed, python3 →
  3.8.0, sshd block installed, install root created, limits/sysctl/THP written.
- **prepare, runs 2 and 3 — idempotent**: every managed file byte-identical
  (`/etc/ssh/sshd_config`, both sysctl and limits drop-ins, the THP unit, the
  vault repo file), installed package set identical, exactly one marker block in
  `sshd_config` after three runs. The first attempt was *not* byte-idempotent —
  a blank line accumulated after the block on each run — and that is fixed.
- **`--finalize-image`**: host keys 0, `/root/.ssh` empty, `machine-id` 0 bytes,
  dnf cache 15M → 4.0K, bundles directory empty, and no `valkey-server` or
  `memtier_benchmark` anywhere.
- **verify**, run on the same container **before** prepare: `NOT READY`, **11
  required failures**. Run **after** prepare with `--bundle`: **40 pass, 4 fail,
  2 advised**, exit code 1. The four are exactly the two blockers of §3 and §4
  and nothing else:

  ```
  FAIL recursive upload     sftp-server has no expand-path@openssh.com
  FAIL valkey-server        8 unresolved
  FAIL valkey-cli           7 unresolved
  FAIL memtier_benchmark    11 unresolved
  ```

  The `recursive upload` check is calibrated rather than merely agreeing with
  itself: the same script on the Debian 13 simulated host reports
  `ok  recursive upload  sftp-server advertises expand-path`.

- **verify leaves the host as it found it**: no new entries under `/tmp`,
  `iptables -S` byte-identical before and after, and the run state root it
  creates to test for `noexec` removed again.

Both scripts parse under `sh -n`. Neither is referenced from `src/`,
`verification/`, `milestones/` or `catalog.json`: they are lab tooling, and the
import graph stays as `CLAUDE.md` requires. `./gate suite repository.all` is
**92/92 PASS**, unchanged — no product code was touched.

### 6.2 The real implementation, driven against a prepared host

Beyond the checklist, the actual product modules were run against the prepared
CentOS container over ssh — 22 checks passing:

| surface | result |
|---|---|
| `MultiplexedSshTransport.run` | 74 ms first call, **median 17.5 ms** over 20 multiplexed |
| `put`/`get` a file | OK — `put`/`get` a *directory* fails (§4.1) |
| `HOST_CLOCK_ARGV` + `reduce_clock_exchanges` | offset **+9.6 ms ± 12.0**, round trip 24 ms |
| `_list_owned_processes`, `_scan_run_residue` | 2 processes found by working directory, plus the state row |
| `_signal_owned_processes`, `_await_owned_processes_gone` | 2 signalled with CONT first, 0 left |
| `isolate_nodehost` script + `-C` confirmation | both jumps installed and confirmed; **control channel survived** |
| `_scan_fault_rules` / `_remove_fault_rules` | 2 marked rules + chain found, removed, residue scan silent |
| `verify_native_bundle` + on-host install | 13831 KB in 75 ms, **sha256 verified on the host**, marker written |
| `valkey-server --version` | **fails** — §3 |
| resource agent (detached form) | launches, samples, `stop()` writes, samples collected back |
| `transport.close()` | masters released |

### 6.3 Measured facts worth keeping

- `docker exec` shows the container's kernel is the Docker host's, so the
  verify script now says so and marks its last section unbelievable in a
  container. **cgroup version, THP, every sysctl and every systemd unit state in
  a container run describe LinuxKit, not CentOS 8.2.**
- `sshd` privilege separation cannot traverse a `mktemp -d` (0700) to read an
  `authorized_keys` inside it, and `StrictModes=no` does not cover traversal.
  The failure is a bare `Permission denied` that names nothing.
- `docker cp` of an `authorized_keys` leaves it owned by the copying uid, and
  sshd refuses it. Whoever places keys per instance needs `chown root:root`.

---

## 7. What cannot be validated until there are real ECS hosts

Named so that nothing here is mistaken for settled.

1. **Everything kernel-level.** cgroup v2 (`systemd.unified_cgroup_hierarchy=1`
   needs `grubby` and a reboot, and there is no bootloader in a container), THP,
   `vm.overcommit_memory`, `fs.file-max`, `nf_conntrack_max`, `somaxconn`. The
   prepare script wrote all of them; **1 of 8 sysctls applied and 7 were
   refused** in the container. On a real CentOS 8.2 kernel the default is
   **cgroup v1**, and §11.1's sampler reads cgroup **v2** filenames through
   helpers that return `None` when absent — so an unmodified host produces a run
   whose every cgroup field is null, where the simulated fleet produced numbers.
   Not a failure; a column of evidence that would differ between the simulated
   baselines and the real ones.
2. **Everything systemd.** `sshd`, `chronyd` and the THP unit were enabled by
   file, not by a running systemd. firewalld and SELinux are absent from the
   container image and present on most real CentOS images; the prepare script
   disables and masks firewalld when it finds it, and touches SELinux only to
   `restorecon /root/.ssh`.
3. **Clock offsets.** Measured **+9.6 ms inside a 12.0 ms bound** here, on a host
   that shares the controller's kernel — so this is a lower bound and says
   nothing about real skew. It is the one place the estimator's decision to
   record a bound rather than test a threshold is expected to pay for itself, and
   M3-B item 1.6 is its first real test.
4. **Transport numbers.** Median 17.5 ms per multiplexed command against the
   rolling restart's 71/61 ms budget — but over loopback on one machine. A VPC
   is the number that closes the transport decision point.
5. **Transport-failure classification.** Shared-kernel hosts cannot produce the
   ambiguity a real network does.
6. **Whether §4.2 reproduces on a real instance.** It was measured against a
   containerised sshd. The sshd is the stock CentOS 8.2 build and the comparison
   was controlled, but a booted instance with systemd and PAM is a different
   configuration and it should be re-measured before anyone concludes it is
   only a container artefact.
7. **Anything about a *running cluster*.** No Valkey process has started on
   CentOS, because none can (§3). Formation dwell, RTO, the fault lane's
   9/12/15 and the health-gate escalation of slice map §16 are all untouched by
   this work.

---

## 8. Recommended order

1. **Decide §3** — where the native bundle is built for these hosts. Nothing
   else about M3-B can proceed past `start_node_processes` until it is settled,
   and the answer changes whether CentOS 8.2 is the right base at all.
2. **Decide §4** — `_scp_argv` and the agent launch shape, or a newer OpenSSH.
   Note that a base image with glibc ≥ 2.38 would very likely carry an OpenSSH
   new enough to make both §4 problems disappear, so §3 and §4 may have one
   answer between them.
3. **Then bake**: `ecs_host_prepare.sh`, then `ecs_host_prepare.sh
   --finalize-image` as the last step.
4. **On a booted instance from that image**, run `ecs_host_verify.sh --bundle
   <dir>` and re-read §7 items 1 and 2 — that run is the first one whose
   kernel-level lines mean anything.
5. Only then M3-B item 1.6, whose own bring-up smoke
   (`scripts/native_bringup_smoke.py`) is the next thing to point at the fleet.
