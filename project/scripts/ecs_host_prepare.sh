#!/bin/sh
# Prepare a pristine CentOS 8.2.2004 host to be an M3-B fleet host.
#
# Lab tooling, not product. It imports nothing from `valkey_scale_lab` and the
# product imports nothing from here - the same boundary `docker/simulated-host/`
# keeps. What crosses to the product is a host that answers ssh and carries the
# programs the native backend runs on it; nothing else.
#
# Every step below is here because a named site in the current
# `native_multi_ecs` implementation needs it. The derivation is in
# `docs/ecs_host_preparation_report.md` §2, which cites the file and line for
# each one. Nothing is installed because it seemed prudent.
#
# What this deliberately does NOT do, because M3-B has to still prove it:
#   * no valkey-server, valkey-cli or memtier_benchmark - `start_nodehost`
#     installs the pinned bundle, and a host that already had them would make
#     that install unfalsifiable. This is the same reason
#     `docker/simulated-host/Dockerfile` *removes* what it inherits.
#   * no run-specific state, no run id, no fleet manifest, no authorized_keys.
#   * no host keys of its own under `--finalize-image`, so that each instance
#     booted from the baked image generates a unique one. A fleet whose hosts
#     all present one key hid a whole class of transport mistake in roadmap
#     item 1.0, on the simulated fleet, and an image bake is exactly where that
#     defect gets manufactured at scale.
#
# Idempotent: every step checks before it acts, and a second run changes
# nothing. Safe to re-run on a host already prepared.
#
# Usage:
#   sudo sh ecs_host_prepare.sh                 # prepare, keep host keys
#   sudo sh ecs_host_prepare.sh --finalize-image  # ... then strip instance identity
#   sudo sh ecs_host_prepare.sh --no-tuning     # skip the sysctl/limits/kernel arm
#
# Verify with `ecs_host_verify.sh`, which is the separate half of this pair.

set -eu

CENTOS_STREAM_VERSION="8.2.2004"
VAULT_BASE="https://vault.centos.org/${CENTOS_STREAM_VERSION}"
REPO_FILE="/etc/yum.repos.d/CentOS-Vault-${CENTOS_STREAM_VERSION}.repo"
STOCK_REPO_ATTIC="/etc/yum.repos.d/pre-vault"
LIMITS_FILE="/etc/security/limits.d/90-valkey-scale-lab.conf"
SYSCTL_FILE="/etc/sysctl.d/90-valkey-scale-lab.conf"
THP_UNIT="/etc/systemd/system/valkey-scale-lab-thp.service"

# `NATIVE_INSTALL_ROOT` in runtime/native_backend.py. The bundle unpacks under
# it and `valkey-server` is executed from there, so it has to exist, be ours,
# and be on a filesystem that permits exec.
NATIVE_INSTALL_ROOT="/opt/valkey-scale-lab/bundles"

DO_TUNING=1
DO_FINALIZE=0

for arg in "$@"; do
    case "$arg" in
        --no-tuning) DO_TUNING=0 ;;
        --finalize-image) DO_FINALIZE=1 ;;
        -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
        *) echo "unknown argument: $arg" >&2; exit 64 ;;
    esac
done

log()  { printf '[prepare] %s\n' "$*"; }
skip() { printf '[prepare] .. %s\n' "$*"; }
warn() { printf '[prepare] !! %s\n' "$*" >&2; }

[ "$(id -u)" = "0" ] || { echo "this must run as root" >&2; exit 77; }

ARCH="$(uname -m)"
log "host is $(sed -n '1p' /etc/centos-release 2>/dev/null || echo 'not CentOS') on ${ARCH}"
if ! grep -qF "${CENTOS_STREAM_VERSION}" /etc/centos-release 2>/dev/null; then
    warn "this was derived and measured on CentOS ${CENTOS_STREAM_VERSION}; continuing anyway"
fi

# ---------------------------------------------------------------------------
# 1. Package repositories.
#
# CentOS 8 is end-of-life, so the stock `mirrorlist.centos.org` entries resolve
# to nothing and every `dnf install` below would fail before it started. Vault
# still serves 8.2.2004 exactly, which is also what pins this host to the same
# minor version the bundle would be built against.
#
# Only rewritten if the existing configuration cannot actually fetch metadata.
# A real ECS image may already point at a working vendor mirror, and replacing
# a working repo set with vault would be a change nobody asked for.
# ---------------------------------------------------------------------------
if dnf -q --setopt=timeout=15 --setopt=retries=1 makecache >/dev/null 2>&1; then
    skip "repositories already resolve; leaving them alone"
else
    log "stock repositories do not resolve; pinning to vault ${CENTOS_STREAM_VERSION}"
    if [ ! -d "${STOCK_REPO_ATTIC}" ]; then
        mkdir -p "${STOCK_REPO_ATTIC}"
        # Moved rather than deleted: a host that turns out to have a working
        # vendor mirror can be put back by hand, and the attic says what was
        # there before this script touched it.
        for repo in /etc/yum.repos.d/*.repo; do
            [ -e "$repo" ] || continue
            case "$repo" in "$REPO_FILE") continue ;; esac
            mv "$repo" "${STOCK_REPO_ATTIC}/"
        done
    fi
    cat > "${REPO_FILE}" <<EOF
# Written by scripts/ecs_host_prepare.sh. CentOS 8 is EOL and the stock
# mirrorlists resolve to nothing; vault still serves ${CENTOS_STREAM_VERSION}
# exactly. Pinning the point release rather than \$releasever is deliberate:
# the host and the native bundle have to agree on a glibc, and "8" would drift.
[vault-baseos]
name=CentOS-${CENTOS_STREAM_VERSION} - BaseOS (vault)
baseurl=${VAULT_BASE}/BaseOS/${ARCH}/os/
gpgcheck=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-centosofficial
enabled=1

[vault-appstream]
name=CentOS-${CENTOS_STREAM_VERSION} - AppStream (vault)
baseurl=${VAULT_BASE}/AppStream/${ARCH}/os/
gpgcheck=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-centosofficial
enabled=1

[vault-extras]
name=CentOS-${CENTOS_STREAM_VERSION} - Extras (vault)
baseurl=${VAULT_BASE}/extras/${ARCH}/os/
gpgcheck=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-centosofficial
enabled=1
EOF
    dnf -q makecache >/dev/null
    log "vault repositories reachable"
fi

# ---------------------------------------------------------------------------
# 2. Packages.
#
# Three groups, and each package is here for a call site:
#
#   control channel   openssh-server  - the transport is ssh; MultiplexedSshTransport
#                                       opens one master per host and scp rides it.
#                     openssh-clients - `ssh-keygen`, and `scp`'s remote half for a
#                                       controller old enough to use the legacy
#                                       protocol. A controller on OpenSSH >= 9 uses
#                                       the sftp subsystem instead, which
#                                       openssh-server carries; installing both
#                                       means the host does not care which.
#
#   backend commands  iptables  - isolate_nodehost/rejoin_nodehost/_remove_fault_rules
#                                 build chains with `-m comment`; the residue scan
#                                 asks `iptables -S` and reports "unscannable" if it
#                                 cannot, so an absent iptables is not a quiet pass.
#                     iproute   - create_network runs `ip route get <peer>` per pair.
#                     python38  - the §11.1 resource agent runs as
#                                 `python3 -m valkey_scale_lab.observability.resource_agent`,
#                                 and HOST_CLOCK_ARGV is `python3 -c ...`.
#                                 CentOS 8's own python3 is 3.6.8 and *cannot*
#                                 import the agent - measured, `SyntaxError: future
#                                 feature annotations is not defined`, because the
#                                 product uses `from __future__ import annotations`.
#                     gawk, coreutils, tar, gzip, procps-ng - named directly by the
#                                 remote scripts (`awk`, `sha256sum`, `readlink`,
#                                 `seq`, `tar -xzf`, ...). Present in the base image;
#                                 listed so a more minimal cloud image is also covered.
#
#   bundle runtime    openssl-libs, libevent, systemd-libs, libstdc++, zlib -
#                                 what the pinned build's three binaries link
#                                 against. See the report §3: the *current*
#                                 Debian-13-built bundle cannot run here at all,
#                                 and these are the CentOS 8.2 sonames a bundle
#                                 rebuilt against this host would need. Runtime
#                                 libraries only - no -devel, no compiler, and no
#                                 valkey/memtier binaries.
#
#   time              chrony    - host_clock records an offset with a bound rather
#                                 than against a threshold, so real skew is expected
#                                 and survivable; a host with no time source at all
#                                 is a different thing and is worth not shipping.
# ---------------------------------------------------------------------------
log "installing packages"
dnf -y -q install \
    openssh-server \
    openssh-clients \
    iptables \
    iproute \
    gawk \
    tar \
    gzip \
    procps-ng \
    openssl-libs \
    libevent \
    systemd-libs \
    libstdc++ \
    zlib \
    chrony \
    >/dev/null

# `coreutils` is requested only when nothing already provides it. The stock
# container image carries `coreutils-single`, which supplies every command the
# remote scripts name and *conflicts* with `coreutils` - asking for the full
# package by name aborts the whole transaction. Measured on a pristine
# centos:centos8.2.2004.
if rpm -q coreutils >/dev/null 2>&1 || rpm -q coreutils-single >/dev/null 2>&1; then
    skip "coreutils already provided by $(rpm -q coreutils coreutils-single 2>/dev/null | grep -v 'not installed' | head -1)"
else
    dnf -y -q install coreutils >/dev/null
fi

# python38 is a module stream, so it needs enabling before the package resolves.
if [ -x /usr/bin/python3.8 ]; then
    skip "python3.8 already installed"
else
    log "enabling the python38 module stream"
    dnf -y -q module enable python38 >/dev/null 2>&1 || true
    dnf -y -q install python38 >/dev/null
fi
# The backend invokes bare `python3`; the module install points the alternative
# at 3.8 already, but this makes the outcome explicit rather than incidental.
if command -v alternatives >/dev/null 2>&1 && [ -x /usr/bin/python3.8 ]; then
    alternatives --set python3 /usr/bin/python3.8 >/dev/null 2>&1 || true
fi
log "python3 is $(python3 -V 2>&1)"

# ---------------------------------------------------------------------------
# 3. sshd.
#
# A marked block at the *top* of sshd_config, not a drop-in and not an append.
# Two measured reasons, both on a pristine centos:centos8.2.2004:
#
#   * CentOS 8.2's OpenSSH 8.0p1 does not implement `Include` at all - it exits
#     with `Bad configuration option: Include`. There is no sshd_config.d.
#   * sshd keeps the *first* value it sees for a keyword, and the stock file
#     already sets `PasswordAuthentication yes` at line 85. An appended block
#     would parse cleanly and change nothing.
#
# The block is delimited by markers and rewritten whole on every run, which is
# what makes this idempotent. Everything the block does not name still comes
# from the stock file below it.
#
# MaxSessions is raised off its stock 10. Past that limit sshd queues rather
# than failing (measured on the simulated fleet to parallelism 32, zero
# failures, latency 11.8 -> 23.0 ms), so this is a latency term and not a
# correctness one; the run's own parallelism is 8 per host, but teardown and
# the evidence pulls burst above it.
# ---------------------------------------------------------------------------
SSHD_CONFIG="/etc/ssh/sshd_config"
SSHD_BEGIN="# >>> valkey-scale-lab (scripts/ecs_host_prepare.sh) >>>"
SSHD_END="# <<< valkey-scale-lab (scripts/ecs_host_prepare.sh) <<<"

[ -f "${SSHD_CONFIG}.pre-valkey-scale-lab" ] || cp -p "${SSHD_CONFIG}" "${SSHD_CONFIG}.pre-valkey-scale-lab"

sshd_remainder="$(mktemp)"
# Everything below the block, minus any block a previous run left. The `sed`
# drops leading blank lines, and it is what makes a second run byte-identical
# rather than merely equivalent: the block is followed by a blank separator, so
# without this each run would recover that separator into the remainder and
# grow the file by one line. Measured - the first two-run idempotency check
# differed in exactly that.
awk -v b="${SSHD_BEGIN}" -v e="${SSHD_END}" \
    '$0==b {skip=1} skip==0 {print} $0==e {skip=0}' "${SSHD_CONFIG}" \
    | sed '/./,$!d' > "${sshd_remainder}"

sshd_candidate="$(mktemp)"
{
    printf '%s\n' "${SSHD_BEGIN}"
    cat <<'EOF'
# Key-only login. The transport runs with BatchMode=yes, so anything that would
# prompt is a hang rather than a refusal.
PermitRootLogin prohibit-password
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
PermitUserEnvironment no
# The controller has no reverse DNS for a fleet host, and a lookup would only
# add latency to every master handshake.
UseDNS no
# One ssh master per host carries every command; sessions multiplex over it.
MaxSessions 64
# Masters for a whole fleet are opened at once at the start of a run.
MaxStartups 30:50:120
EOF
    # `Subsystem` is the one keyword sshd refuses to see twice - measured,
    # `Subsystem 'sftp' already defined` - so unlike everything above it, this
    # cannot simply be restated and left to first-value-wins. It is added only
    # when the stock file defines none, which on CentOS 8.2 it does (line 141).
    # scp on a controller running OpenSSH >= 9 drives transfers over it.
    if grep -qE '^[[:space:]]*Subsystem[[:space:]]+sftp' "${sshd_remainder}"; then
        printf '# Subsystem sftp: already defined below, and sshd refuses a second one.\n'
    else
        printf 'Subsystem sftp /usr/libexec/openssh/sftp-server\n'
    fi
    printf '%s\n\n' "${SSHD_END}"
    cat "${sshd_remainder}"
} > "${sshd_candidate}"

# Validated before it is installed, and with a throwaway host key so that the
# check is about the configuration rather than about whether this host has keys
# yet - a freshly installed host and a finalized image both have none.
probe_key_dir="$(mktemp -d)"
ssh-keygen -q -t ed25519 -N '' -f "${probe_key_dir}/probe" >/dev/null 2>&1
if /usr/sbin/sshd -t -f "${sshd_candidate}" -h "${probe_key_dir}/probe" 2>/dev/null; then
    if cmp -s "${sshd_candidate}" "${SSHD_CONFIG}"; then
        skip "sshd configuration already current"
    else
        install -m 0600 -o root -g root "${sshd_candidate}" "${SSHD_CONFIG}"
        log "installed the valkey-scale-lab block at the top of ${SSHD_CONFIG}"
    fi
else
    warn "the candidate sshd configuration does not validate; ${SSHD_CONFIG} left untouched"
    /usr/sbin/sshd -t -f "${sshd_candidate}" -h "${probe_key_dir}/probe" || true
    rm -rf "${probe_key_dir}" "${sshd_candidate}"
    exit 65
fi
rm -rf "${probe_key_dir}" "${sshd_candidate}" "${sshd_remainder}"

if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    systemctl enable sshd >/dev/null 2>&1 || warn "could not enable sshd"
    log "sshd enabled for boot"
else
    skip "no systemd running here; enable sshd on the real host"
fi

# ---------------------------------------------------------------------------
# 4. firewalld.
#
# The fault actuator installs its own iptables chains and both cleanup paths
# find them by a comment. firewalld owns the packet filter on a host it runs on
# and reloads it out from under anything that did not go through firewalld, so
# a reload mid-run would silently undo a partition the run believes is in
# place. It is not a dependency of anything here, so it is disabled rather than
# configured around.
# ---------------------------------------------------------------------------
if rpm -q firewalld >/dev/null 2>&1; then
    if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
        systemctl disable --now firewalld >/dev/null 2>&1 || true
        systemctl mask firewalld >/dev/null 2>&1 || true
        log "firewalld disabled and masked"
    else
        warn "firewalld is installed but systemd is not running here; disable it on the real host"
    fi
else
    skip "firewalld is not installed"
fi

# ---------------------------------------------------------------------------
# 5. The bundle install root.
#
# Created here so that the first thing a run does on this host is not also the
# first thing that ever wrote to /opt. Mode 0755 and root-owned: the manifest's
# user is root today, and a host whose install root were writable by anyone
# would make the digest check on the archive pointless.
# ---------------------------------------------------------------------------
if [ -d "${NATIVE_INSTALL_ROOT}" ]; then
    skip "${NATIVE_INSTALL_ROOT} already exists"
else
    mkdir -p "${NATIVE_INSTALL_ROOT}"
    chown root:root /opt/valkey-scale-lab "${NATIVE_INSTALL_ROOT}"
    chmod 0755 /opt/valkey-scale-lab "${NATIVE_INSTALL_ROOT}"
    log "created ${NATIVE_INSTALL_ROOT}"
fi

# ---------------------------------------------------------------------------
# 6. Tuning for the density the planner will actually place.
#
# A native run places exactly one nodehost per host and
# `max_logical_nodes_per_nodehost` is 25, so this host will carry 25
# valkey-server processes, each of which asks for its default 10000 maxclients
# plus overhead. None of this is required for the backend to function; all of
# it is required for 25 nodes not to be measuring the host's stock limits
# instead of the cluster.
#
# Written as files first and applied live second, because a container cannot
# write most of these and a real host can. A failure to apply live is not a
# failure to prepare an image.
# ---------------------------------------------------------------------------
if [ "${DO_TUNING}" = "0" ]; then
    skip "tuning skipped by --no-tuning"
else
    cat > "${LIMITS_FILE}" <<'EOF'
# Written by scripts/ecs_host_prepare.sh.
# 25 valkey-server processes per host, each defaulting to maxclients 10000.
# Valkey silently lowers maxclients when it cannot get the descriptors, which
# would make a capacity result a fact about ulimit rather than about Valkey.
*  soft  nofile  1048576
*  hard  nofile  1048576
root soft nofile 1048576
root hard nofile 1048576
EOF
    log "wrote ${LIMITS_FILE}"

    cat > "${SYSCTL_FILE}" <<'EOF'
# Written by scripts/ecs_host_prepare.sh.

# 25 nodes x 10000 maxclients, plus the cluster bus mesh between every pair of
# nodes in the fleet.
fs.file-max = 2097152
fs.nr_open = 1048576

# Valkey's tcp-backlog defaults to 511 and it logs the mismatch when somaxconn
# is lower. CentOS 8 ships 128.
net.core.somaxconn = 4096
net.ipv4.tcp_max_syn_backlog = 8192

# The run's node configs set no `save` directive, so Valkey's built-in save
# policy is active and a background save forks the whole process - which is the
# mechanism roadmap `313cacc9` traced a real failure to. Under the default
# heuristic that fork can be refused on a host holding 25 datasets.
vm.overcommit_memory = 1

# The controller drives its RESP traffic from a small number of hosts and the
# lab has already hit ephemeral-port exhaustion once, on the macOS controller.
net.ipv4.ip_local_port_range = 10240 65535
net.ipv4.tcp_tw_reuse = 1

# The partition actuator installs plain filter rules and needs no connection
# tracking, but a cloud image usually arrives with conntrack loaded by its own
# default rules, and a full table drops packets that look exactly like a
# cluster-bus failure.
net.netfilter.nf_conntrack_max = 1048576
EOF
    log "wrote ${SYSCTL_FILE}"

    if command -v sysctl >/dev/null 2>&1; then
        # Per-key, tolerating refusals: a container refuses most of these and
        # `sysctl -p` would abort on the first one.
        applied=0; refused=0
        while IFS= read -r line; do
            case "$line" in ''|\#*) continue ;; esac
            key="$(printf '%s' "$line" | cut -d= -f1 | tr -d ' ')"
            value="$(printf '%s' "$line" | cut -d= -f2- | tr -d ' ')"
            if sysctl -q -w "${key}=${value}" >/dev/null 2>&1; then
                applied=$((applied + 1))
            else
                refused=$((refused + 1))
            fi
        done < "${SYSCTL_FILE}"
        log "sysctl applied ${applied}, refused ${refused} (refusals are expected in a container)"
    fi

    # Transparent huge pages. Valkey names this one itself, in its own startup
    # log, because THP makes the copy-on-write of a background save expensive
    # and the latency shows up in exactly the tail this lab measures.
    cat > "${THP_UNIT}" <<'EOF'
[Unit]
Description=Disable transparent huge pages for valkey-scale-lab
DefaultDependencies=no
After=sysinit.target local-fs.target
Before=sshd.service

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'echo never > /sys/kernel/mm/transparent_hugepage/enabled || true'
ExecStart=/bin/sh -c 'echo never > /sys/kernel/mm/transparent_hugepage/defrag || true'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
    if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
        systemctl daemon-reload >/dev/null 2>&1 || true
        systemctl enable valkey-scale-lab-thp.service >/dev/null 2>&1 || true
        systemctl start valkey-scale-lab-thp.service >/dev/null 2>&1 || true
        log "transparent huge pages disabled at boot"
    else
        skip "no systemd here; ${THP_UNIT} written for the real host"
    fi

    # cgroup v2. The §11.1 sampler reads `cpu.max`, `memory.max`,
    # `memory.current`, `cpu.stat` and `memory.events` at /sys/fs/cgroup - all
    # cgroup v2 names, all read through `_optional_*` helpers that return None
    # when the file is absent. CentOS 8 boots cgroup v1 by default, so every
    # cgroup field of every resource sample on an unmodified host would be
    # null: not a failure, but a whole column of evidence that the simulated
    # fleet produced and the real one would not.
    if command -v grubby >/dev/null 2>&1; then
        if grubby --info=ALL 2>/dev/null | grep -q 'systemd.unified_cgroup_hierarchy=1'; then
            skip "cgroup v2 already requested on the kernel command line"
        else
            grubby --update-kernel=ALL --args="systemd.unified_cgroup_hierarchy=1" >/dev/null 2>&1 \
                && log "cgroup v2 requested on the kernel command line (needs a reboot)" \
                || warn "grubby could not set the cgroup v2 kernel argument"
        fi
    else
        skip "no grubby here; set systemd.unified_cgroup_hierarchy=1 on the real host for cgroup v2"
    fi
fi

# ---------------------------------------------------------------------------
# 7. Time.
# ---------------------------------------------------------------------------
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    systemctl enable chronyd >/dev/null 2>&1 || true
    log "chronyd enabled for boot"
else
    skip "no systemd here; chronyd is installed and will start on the real host"
fi

# ---------------------------------------------------------------------------
# 8. SELinux.
#
# Left in whatever mode the operator chose - changing it is a security decision
# and not a host-preparation one. What is done is the one thing that is purely
# a labelling repair: /root/.ssh, which the harness or the image bake writes
# into and which sshd refuses to read under a wrong label.
# ---------------------------------------------------------------------------
mkdir -p /root/.ssh && chmod 700 /root/.ssh
if command -v restorecon >/dev/null 2>&1; then
    restorecon -R /root/.ssh >/dev/null 2>&1 || true
    log "relabelled /root/.ssh"
else
    skip "no restorecon here (SELinux tools absent)"
fi

# ---------------------------------------------------------------------------
# 9. Image finalization.
#
# Only under --finalize-image, and last, because it removes the very things
# that make the host usable right now. Run it as the final step of the bake.
# ---------------------------------------------------------------------------
if [ "${DO_FINALIZE}" = "1" ]; then
    log "finalizing for an image bake"
    # The item 1.0 defect, at image scale. Debian's openssh postinst generated
    # host keys during the *image build*, so two hosts from one layer served one
    # fingerprint and the manifest could not tell them apart. sshd-keygen@.service
    # regenerates these at first boot, so removing them here is what makes every
    # instance distinct.
    rm -f /etc/ssh/ssh_host_*
    log "removed ssh host keys; sshd-keygen regenerates them per instance at boot"

    # Nothing run-specific is baked. authorized_keys is the fleet operator's to
    # place, per instance, and a key baked into an image is a key on every host
    # forever.
    rm -f /root/.ssh/authorized_keys
    rm -f /root/.ssh/known_hosts

    # Anything a run left, if this host was used before it was baked.
    rm -rf /tmp/valkey-scale-lab /tmp/vslab-load-lane /tmp/vslab-bundle-* 2>/dev/null || true
    rm -rf "${NATIVE_INSTALL_ROOT:?}"/* 2>/dev/null || true
    log "removed run state, bundles and load-lane directories"

    : > /etc/machine-id
    rm -f /var/lib/dbus/machine-id 2>/dev/null || true
    dnf -q clean all >/dev/null 2>&1 || true
    rm -rf /var/cache/dnf/* 2>/dev/null || true
    log "cleared machine-id and package cache"
fi

log "done. Run ecs_host_verify.sh to check this host against the native backend."
