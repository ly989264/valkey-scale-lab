# Roadmap items 1.0 and 1.1: the simulated-host harness and the pinned native build

Session M3-A-1. Scope was exactly these two items and nothing else.

They are one session because neither proves anything alone. A manifest generator
with nothing to install proves that a JSON file can be written; a bundle with no
host to install it on proves that a tarball can be made. Together they prove that
a host described only by a manifest can be given the pinned binaries and run
them - which is the part a native backend will depend on.

Read `roadmap_preconditions_exit_report.md` for the state this inherits.

---

## 1. Where the harness lives, and why

`project/` holds the product; `project/src/valkey_scale_lab/` **is** the product.
Everything else under `project/` is already lab tooling that builds or checks
what the product consumes - `docker/valkey-custom/Dockerfile` and
`scripts/build_valkey_image.sh` produce the pinned image the runtime preflights,
and neither is importable by the product. The harness is the same kind of thing,
so it went in the same places rather than into a new top-level directory:

| Path | What |
|---|---|
| `docker/simulated-host/Dockerfile` | the simulated ECS instance's image |
| `docker/simulated-host/image-digests.json` | what that image was built from |
| `scripts/build_simulated_host_image.sh` | builds it and records the digests |
| `scripts/simulated_hosts.py` | brings a fleet up and writes its manifest |
| `scripts/build_native_bundle.py` | builds item 1.1's bundle |
| `src/valkey_scale_lab/runtime/native_bundle.py` | verifies one - the only product file |

Two reasons for this over a new `project/harness/`. It matches how the pinned
image is already carried, so there is one story for lab build products rather
than two. And `scripts/` is inside `assert_execution_axis_contract.py`'s scan
roots while a new directory would not be, so the harness inherits the repository's
vocabulary checks instead of escaping them.

The boundary that matters is not the directory, it is the import graph:
`simulated_hosts.py` imports nothing from `valkey_scale_lab`, and the product
imports nothing from `scripts/`. §15 holds because none of this is product code.

### 1.1 Why one product file

`native_bundle.py` is the exception, and deliberately: verifying the build
products a run will use is `verify_image`'s job, which is a `NodeBackend`
operation and therefore product. Under Docker that check lives in
`docker_runtime.py` as `_verify_custom_valkey_image`; a backend whose hosts have
no image needs the same question answered about a bundle, and answering it does
not require knowing what a host is or how a bundle gets to one. It has no caller
yet - item 1.2 gives it one. That is the same shape as `BackendSpec.node_backend`,
declared at `39e31b1a` and first consumed at `4f54442a`.

Its return shape is not a matter of taste. `_write_cluster_myslots_report` reads
`image_preflight["valkey_server_sha256"]` and stamps it on every observed node
(`docker_runtime.py:5176`), and `scripts/diff_stage_artifacts.py:159` carries the
whole preflight mapping into the `runtime_start` diff view. Both were measured,
not assumed, and both are why the native evidence uses the existing key names.

---

## 2. The simulated host

### 2.1 What the pinned image actually contains

Measured before anything was written, because the roadmap says the harness image
"needs standard tooling the minimal image lacks" without saying which:

- Debian 13 (trixie), aarch64.
- Present: `tar`, `python3`, `useradd`, and `/usr/local/bin/{valkey-server,
  valkey-cli,memtier_benchmark}` plus `/usr/local/share/valkey-scale-lab/build-manifest.txt`.
- Absent: `sshd`, `ssh-keygen`, `ssh`, `scp`, `ip`, `iptables`, `curl`, `rsync`,
  `sudo`.

So the harness adds `openssh-server`, `iproute2` and `iptables` - measured
installable from the pinned Debian snapshot, at OpenSSH 10.0p2 and iptables
1.8.11 (nf_tables). `snapshot.debian.org` returns 500 intermittently; the first
attempt failed on two package downloads, so the image's apt config raises
`Acquire::Retries` to 15 and turns pipelining off.

### 2.2 What it removes, which is the less obvious half

A host derived from the pinned image inherits `valkey-server` on `PATH`. That
would make item 1.1 unfalsifiable: the run bundle's `start_all.sh` invokes bare
`valkey-server` (`docker_runtime.py:1737`), so a host that already had one would
start *that* binary and a bundle install would prove nothing. The image therefore
deletes the three binaries and the build manifest, and the build script fails if
any of them is still present.

What stays is what a provisioned ECS host would also have: libevent, which
memtier links against, and `python3`, which §11.1's on-host resource sampler
needs. Keeping those is faithful rather than convenient - installing them is a
host-image concern on a real fleet too.

The parent is referenced by tag rather than digest, because it is built locally
and never pushed, so a digest reference would send Docker to a registry. The
build script reads the parent's digest before building and records it, which is
the same guarantee made where it can actually be checked.

### 2.3 A defect the first fleet found

The first fleet came up with **both hosts serving one host key fingerprint**.
The entrypoint runs `ssh-keygen -A` on boot, but Debian's `openssh-server`
postinst had already generated a set during the image build, so the boot-time
call found them present and did nothing - and the keys were baked into a shared
layer.

That is a real transport hazard rather than cosmetics: a fleet whose hosts are
mutually indistinguishable by host key hides every mistake in which host a
command reached. The image now deletes `/etc/ssh/ssh_host_*` after the apt step,
the build script refuses an image carrying any, and the rebuilt fleet serves two
distinct fingerprints. Found by looking at the manifest a bring-up produced,
which is the only reason it was found at all.

---

## 3. The inventory manifest

### 3.1 Three addresses, because a host has three roles

| Field | Meaning |
|---|---|
| `control_endpoint` | where the controller runs commands on the host |
| `data_address` | what the host's processes announce, and what peers dial |
| `client_endpoint` | where the controller speaks RESP to those processes |

Conflating these is the mistake the harness exists to make visible, and the seam
already names the distinction: `NodeBackend.client_host` documents that "the run
connects to a published port on loopback, while the cluster announces the
nodehost's address on its own network, because the macOS host cannot route it",
and warns that returning one where the other was meant yields a cluster that
forms but cannot be reached, or one reachable and never formed.

Under this harness the last two differ for exactly that reason. On a real fleet
they usually coincide, and the manifest then carries the same address twice - the
field set does not change. `client_endpoint` carries a contiguous **port range**
rather than a list, because a real host states the same thing as a security-group
range; which ports inside it a run uses is the run's business.

Each host also carries `host_id`, `availability_zone`, `os` and `capacity`.
`host_id` and the availability zone are the existing vocabulary: the density
planner already emits `host_id` (defaulted to `"local"`) and `az_id` per nodehost
(`nodehost_density.py:74-86`), so a backend mapping planned nodehosts onto
manifest hosts has both halves without new names.

### 3.2 Read from the host, not from Docker

Everything a real fleet would also have - the address, kernel, distribution,
architecture, cpu and memory - is read **from the host over its control
endpoint**, not from `docker inspect`. That is the demonstration, not tidiness:
the same generator would produce the same manifest against hosts nobody started.
Only the ssh port mapping is harness-allocated, and a real fleet answers on 22.

### 3.3 What the manifest must not carry

The acceptance condition is that a backend cannot tell the hosts are containers,
so `_reject_container_vocabulary` refuses to write a manifest containing
`container`, `docker`, `image`, `vslab-sim` or `simulated`, and eleven tests in
`tests/unit/test_simulated_host_manifest.py` hold it. This caught one real leak
during development: the fleet's private key path appears in the manifest, so the
state directory could not be called `artifacts/simulated-hosts/`. It is
`artifacts/host-fleets/`.

What the harness knows about itself - the image, its digest, the Docker network,
the container names, the bring-up timings, and `"simulated": true` - goes in a
sidecar `harness_provenance.json` beside the manifest, which the product never
reads. **Whether a run records that its fleet was simulated is an evidence
question for item 1.3 and a baseline question for item 1.5.** This session does
not answer it; it only makes sure the answer cannot be reached by the backend
sniffing its inventory.

### 3.4 Measured bring-up

Two hosts, 60 published client ports each, `--client-ports 60`:

| | |
|---|---|
| containers started | **1.07 s** |
| ssh answering on both | **1.71 s** |
| host key fingerprints | two, distinct |
| `data_address` | `172.18.0.2`, `172.18.0.3` |
| reported capacity | 10 cpus, 8.22 GB - **per host, and wrong**; see §6 |

`NET_ADMIN` and real iptables work inside a host: `iptables -A INPUT -p tcp
--dport 6399 -j DROP` installs, lists and deletes. That is what a later item's
partition actuator needs in order to use its real mechanism instead of
`docker network disconnect`; nothing in this session uses it.

---

## 4. The pinned native bundle

### 4.1 Built from the stage that already exists

`docker/valkey-custom/Dockerfile` already has a `binaries` target -
`FROM scratch` with the compiled `valkey-server`, `valkey-cli`,
`memtier_benchmark` and `build-manifest.txt` - and `build_valkey_image.sh`
already exports it to read the digests it passes into the runtime stage. The
bundle builder reuses that target rather than compiling anything of its own,
because a second way to build "the pinned build" is the one thing a provenance
artifact must not have. Nothing in the Dockerfile changed.

The bundle is `bin/{valkey-server,valkey-cli,memtier_benchmark}` plus
`build-manifest.txt`, as a tarball and unpacked, with `bundle_manifest.json`
recording the versions, the pinned source and patch digests, a sha256 per binary,
and the archive's own sha256 and size.

### 4.2 The anchor

A manifest checked only against its own tarball accepts a bundle and a manifest
corrupted together. So the builder cross-checks every binary digest against the
**pinned image's build labels** before writing anything, and refuses if they
differ. Those labels were recorded by a build the product already trusts and
preflights on every Docker run. Measured: all three matched, and
`valkey_server_sha256` is `91c67d9f…e494` on both sides.

### 4.3 The archive is byte-reproducible

Members are added sorted, with uid/gid 0 and mtime 0, and the gzip header is
written with `mtime=0` too. Two consecutive builds produced the identical archive
digest `fe1839de…067d`, 14,163,063 bytes. Without this the archive digest would
change every build and say nothing about the bytes inside it.

### 4.4 What the verifier refuses, and what it declines to claim

`verify_native_bundle` recomputes every recorded digest from the bytes on disk
and raises on any mismatch, missing file, malformed digest, absent or foreign
manifest. Measured against a real bundle: intact copy passes; **one byte appended
to `valkey-server` fails with both digests named, exit 1.** That is item 1.1's
acceptance - a mismatch fails preflight.

It does **not** report `command: CLUSTER MYSLOTS`, which its Docker sibling does.
The Docker preflight starts the server inside the image and asks it whether the
patched command exists; this one hashes bytes on the controller, and the bundle
holds host-platform binaries the controller need not be able to execute. The
evidence therefore carries `verified: [archive_sha256, binary_sha256]` and a
`not_verified.cluster_myslots_command` with the reason. Reporting the command
verified because the Docker path does would fabricate the single piece of
evidence the patched build exists for, and the repository's rule is that missing
evidence is represented with a reason and never invented.

That gap is closable only on a host, and §5 closes it there - but as a
measurement in this report, not as a claim inside the artifact.

---

## 5. The two items proved together

The bundle was installed on both simulated hosts using **only** what the manifest
carries - address, port, user, private key, known-hosts file. Nothing in the
procedure named a container, and nothing consulted the sidecar.

Per host, identically on `sim-host-00` and `sim-host-01`:

| Step | Result |
|---|---|
| archive copied over the control endpoint, hashed on the host | `fe1839de…067d`, **matches** the bundle manifest |
| extracted, `bin/` linked onto `PATH` | |
| installed `valkey-server` hashed on the host | `91c67d9f…e494`, **matches** |
| `valkey-server --version` | `v=9.1.0 … malloc=jemalloc-5.3.0 bits=64` |
| `memtier_benchmark --version` | `v=2.5.1 … libevent=2.1.12-stable` |
| server started, `COMMAND INFO cluster\|myslots` | **`cluster\|myslots`** |

The last row is the check §4.4 declines to claim: the patched command is present
in the bundle's binary, verified by running it on the host that received it.

The install layout used here - `/opt/valkey-scale-lab` with symlinks into
`/usr/local/bin` - is **not a contract**. It is what this demonstration did, run
by hand rather than by a script, precisely so that item 1.2 chooses the install
mechanism rather than inheriting one from a convenience script written here.

---

## 6. What simulation cannot show, measured where possible

The roadmap quarantines real latency, real clock skew and real auth/kernel
configuration to M3-B. Two more are worth adding because they were measured here:

- **`capacity` is the VM's, not the host's.** Both hosts report 10 cpus and
  8.22 GB, which is Docker Desktop's Linux VM, shared. Density arithmetic on
  simulated hosts is therefore meaningless, and the roadmap's own density check
  (item 0.7, "count × spec must hold exact-200") can only be done on the real
  fleet. The field is in the manifest because a real fleet answers it truthfully.
- **The bundle is `arm64`.** It is built from this Mac's architecture and the
  bundle manifest records that. A real fleet is likely `x86_64`, so M3-B needs
  its own bundle build and its own digests; the manifest carrying `architecture`
  is what makes that a check rather than a surprise.

---

## 7. Deliberately not decided here

Each of these was reachable during this session and left alone on purpose.

- **The transport.** The harness offers sshd because the roadmap's item 1.0 says
  it does, and the manifest states `protocols: ["ssh"]` as what the host offers,
  not what a backend must use. Item 1.2's decision point - multiplexed SSH
  against an extended on-host agent - is untouched: both candidates are
  bootstrapped over the same endpoint, and the measurement that closes it is
  per-operation overhead against the rolling restart's budget, which nobody took
  here.
- **Inventory field vocabulary.** Whether a backend's identifiers fit the
  existing `container_*` fields is decided during item 1.2, locally, by whether
  they turn out semantically wrong. The manifest is the harness's output; a
  backend is free to map it however 1.2 concludes.
- **The install mechanism and layout**, per §5.
- **Node-log collection** (item 1.3) and **stale-pid teardown** (item 1.4). The
  simulated hosts would have made either easy to start; neither was touched.
- **Ownership checks on fault paths.** Accepted as absent, recorded, and a
  candidate for whoever writes a second backend. The harness adds no such check.

## 8. What was registered

Two Tests, once each, no placeholders:

| Test | Covers |
|---|---|
| `product.unit.native_bundle` | 11 checks on the bundle preflight |
| `product.unit.simulated_host_manifest` | 14 checks on the manifest boundary |

Both are in `product.unit`, `product.all` and `repository.all`, which is where
`product.unit.valkey_probe_lib` already sits for a `scripts/` module.
**`repository.all` is 90, from 88.** Registering a Test moves three numbers, not
one: two of the Gate's own contract tests pin the catalog size (92 → 94) and the
M1 plan size (87 → 89), and they fail loudly if only the catalog is edited.
`./gate milestone m1` stays `READY`.

No real gate run was taken, and none was needed: neither item is on a run's path
until item 1.2 exists to call them. The per-slice acceptance bar's real-run
clause has nothing to attach to here - there is no modified stage.

### 8.1 One older defect this made reachable

`repository.all` went **89/90** on a run taken while a fleet was being torn down:
`product.scenarios.execution_axis_contract` raised `FileNotFoundError` on
`artifacts/host-fleets/sim-a/inventory.json`. The scan lists every file under its
roots and then reads them, and it takes **4m17s** on this checkout, so anything
listed can be gone before it is read.

The race is older than the harness and does not need it - `artifacts/` is a live
output directory and any run writing or rotating files there during a suite can
lose the same way. Nothing had ever deleted a file there mid-suite, so it had
never fired. A vanished file has no vocabulary to check, so the read skips it;
verified by listing a path and unlinking it before `audit()` reads it. The test
passes standalone either way, which is why only the concurrent run surfaced it.

## 9. One thing item 1.5 should expect

`valkey_image_preflight` is carried whole into the `runtime_start` diff view
(`diff_stage_artifacts.py:159`). A native run's preflight evidence is a different
mapping from a Docker run's - same digest keys, different surrounding fields, and
`not_verified` where the Docker side has `command`. That is a **declared
vocabulary delta** for the equivalence diff, not a regression, and item 1.5 owes
declaring it in advance rather than discovering it red.
