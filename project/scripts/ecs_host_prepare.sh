#!/bin/sh
# Prepare an Ubuntu 26.04 LTS host to be an M3-B fleet host.
#
# Lab tooling, not product. It imports nothing from `valkey_scale_lab` and the
# product imports nothing from here - the same boundary `docker/simulated-host/`
# keeps. What crosses to the product is a host that answers ssh and carries the
# programs the native backend runs on it; nothing else.
#
# `ecs` names the *role* the roadmap gives these hosts and the backend that
# drives them (`native_multi_ecs`), not a cloud. This was derived and measured
# on Google Compute Engine `c4a-standard-2` instances running the stock
# `ubuntu-26-04-lts` arm64 image. `docs/ecs_host_preparation_report.md` §2 cites
# the file and line in the implementation behind every step; nothing here is
# installed or set because it seemed prudent.
#
# **This script is the definition of the fleet image, and the image is its build
# product.** Run it on a pristine instance, run `ecs_host_verify.sh`, then take
# the snapshot. Never hand-tune the instance you snapshot: a fleet built from a
# hand-tuned image cannot be rebuilt or reviewed, and eight hosts that differ in
# unrecorded ways are an unmeasured variable in exactly the runs whose job is to
# freeze baselines.
#
# What this deliberately does NOT do, because M3-B has to still prove it:
#   * no valkey-server, valkey-cli or memtier_benchmark - `start_nodehost`
#     installs the pinned bundle, and a host that already had them would make
#     that install unfalsifiable. This is the same reason
#     `docker/simulated-host/Dockerfile` *removes* what it inherits.
#   * no run-specific state, no run id, no fleet manifest, and no fleet public
#     key. The image provides the *mechanism* for a durable key (§3) and the
#     operator places the key per instance.
#   * no host keys under `--finalize-image`, so each instance booted from the
#     image generates its own. A fleet whose hosts all present one fingerprint
#     hid a whole class of transport mistake in roadmap item 1.0, and an image
#     bake is where that defect gets manufactured at scale.
#
# Idempotent: every step checks before it acts, and a second run changes
# nothing. Safe to re-run on a host already prepared.
#
# Usage:
#   sudo sh ecs_host_prepare.sh                    # prepare
#   sudo sh ecs_host_prepare.sh --finalize-image   # ... then strip instance identity
#   sudo sh ecs_host_prepare.sh --no-tuning        # skip limits/sysctl/THP/tmp
#   sudo sh ecs_host_prepare.sh --keep-tmpfs       # leave /tmp on tmpfs (see §7)

set -eu

SSHD_DROPIN="/etc/ssh/sshd_config.d/10-valkey-scale-lab.conf"
VSLAB_KEYS_DIR="/etc/ssh/vslab_authorized_keys"
LIMITS_FILE="/etc/security/limits.d/90-valkey-scale-lab.conf"
SYSCTL_FILE="/etc/sysctl.d/90-valkey-scale-lab.conf"
SYSTEMD_DROPIN_DIR="/etc/systemd/system.conf.d"
SYSTEMD_DROPIN="${SYSTEMD_DROPIN_DIR}/90-valkey-scale-lab.conf"
SSH_UNIT_DROPIN_DIR="/etc/systemd/system/ssh.service.d"
SSH_UNIT_DROPIN="${SSH_UNIT_DROPIN_DIR}/90-valkey-scale-lab.conf"
THP_UNIT="/etc/systemd/system/valkey-scale-lab-thp.service"

# `NATIVE_INSTALL_ROOT` in runtime/native_backend.py. The bundle unpacks under
# it and `valkey-server` is executed from there, so it has to exist, be ours,
# and be on a filesystem that permits exec.
NATIVE_INSTALL_ROOT="/opt/valkey-scale-lab/bundles"

DO_TUNING=1
DO_FINALIZE=0
KEEP_TMPFS=0

for arg in "$@"; do
    case "$arg" in
        --no-tuning) DO_TUNING=0 ;;
        --finalize-image) DO_FINALIZE=1 ;;
        --keep-tmpfs) KEEP_TMPFS=1 ;;
        -h|--help) sed -n '2,45p' "$0"; exit 0 ;;
        *) echo "unknown argument: $arg" >&2; exit 64 ;;
    esac
done

log()  { printf '[prepare] %s\n' "$*"; }
skip() { printf '[prepare] .. %s\n' "$*"; }
warn() { printf '[prepare] !! %s\n' "$*" >&2; }

# `systemctl is-enabled` exits non-zero for `masked` and `disabled` while still
# printing the state, so the obvious `$(systemctl is-enabled x || echo y)` ends
# up holding two words and never compares equal. Measured: three steps of this
# script reported themselves as changing a host they had already changed.
unit_state() { systemctl is-enabled "$1" 2>/dev/null | head -1; }

[ "$(id -u)" = "0" ] || { echo "this must run as root (use sudo)" >&2; exit 77; }

. /etc/os-release 2>/dev/null || true
log "host is ${PRETTY_NAME:-unknown} on $(uname -m), kernel $(uname -r)"
case "${VERSION_ID:-}" in
    26.04) ;;
    *) warn "this was derived and measured on Ubuntu 26.04 LTS; continuing anyway" ;;
esac

# ---------------------------------------------------------------------------
# 1. Packages.
#
# Far shorter than it looks, because the stock cloud image already carries all
# twenty-one commands the backend's remote scripts name - measured on a stock
# GCE `ubuntu-26-04-lts` instance, where `ip`, `iptables`, `python3`, `awk`,
# `sha256sum`, `tar` and the rest are all present. The bare `ubuntu:26.04`
# container image is *not* the same thing and lacks five of them, so the list is
# stated in full rather than assumed: a minimal or hardened image must still end
# up with these.
#
#   openssh-server  - the transport is ssh; MultiplexedSshTransport opens one
#                     master per host and scp rides it over the sftp subsystem.
#   openssh-client  - ssh-keygen, and scp's remote half for an older controller.
#   iptables        - isolate_nodehost / rejoin_nodehost / _remove_fault_rules
#                     build chains with `-m comment`; the residue scan asks
#                     `iptables -S` and reports "unscannable" if it cannot, so an
#                     absent iptables is not a quiet pass.
#   iproute2        - create_network runs `ip route get <peer>` for every pair.
#   python3         - the §11.1 resource agent runs as `python3 -m
#                     valkey_scale_lab.observability.resource_agent`, and
#                     HOST_CLOCK_ARGV is `python3 -c ...`. Measured on this
#                     image: 3.14.4, and the agent imports and runs on it.
#   libevent-*      - the only libraries the pinned bundle needs and this image
#                     lacks. Measured against the real bundle on a real instance:
#                     valkey-server and valkey-cli link and run with nothing
#                     added at all, and memtier_benchmark alone reports four
#                     unresolved `libevent*-2.1.so.7`. All four sub-packages are
#                     named because `libevent-2.1-7t64` alone supplies only
#                     `libevent` and `libevent_core` - measured, which still left
#                     memtier with three unresolved sonames. These are the same
#                     four the pinned image's runtime stage installs.
#   chrony          - host_clock records an offset with a bound rather than
#                     against a threshold, so real skew is expected and
#                     survivable; a host with no time source is a different
#                     thing and is worth not shipping.
#
# The remaining four are already satisfied on this image and are named so that a
# more minimal one is also covered; apt treats them as no-ops here.
# ---------------------------------------------------------------------------
export DEBIAN_FRONTEND=noninteractive

PACKAGES="openssh-server openssh-client iptables iproute2 python3 chrony
          libevent-2.1-7t64 libevent-extra-2.1-7t64 libevent-pthreads-2.1-7t64
          libevent-openssl-2.1-7t64 libssl3t64 libsystemd0 zlib1g libstdc++6"

missing=""
for pkg in ${PACKAGES}; do
    dpkg-query -W -f='${Status}' "${pkg}" 2>/dev/null | grep -q "ok installed" || missing="${missing} ${pkg}"
done
if [ -z "${missing}" ]; then
    skip "all required packages already installed"
else
    log "installing:${missing}"
    apt-get update -qq
    # shellcheck disable=SC2086
    apt-get install -y -qq --no-install-recommends ${missing}
fi
log "python3 is $(python3 -V 2>&1)"

# ---------------------------------------------------------------------------
# 2. sshd.
#
# A real drop-in, unlike the CentOS 8 predecessor of this script: this image's
# sshd_config carries `Include /etc/ssh/sshd_config.d/*.conf` at line 24, and
# OpenSSH is 10.2p1. The `10-` prefix matters - sshd keeps the *first* value it
# sees for a keyword and the cloud image ships `50-cloudimg-settings.conf` and
# `60-cloudimg-settings.conf`, so this file must sort ahead of them to be the
# effective one. It names only the keywords it means to own; everything else
# still comes from the image.
#
# `Subsystem` is deliberately absent: sshd refuses a second definition of it
# outright, and the image already declares the sftp subsystem that an
# OpenSSH >= 9 controller's `scp` drives its transfers over.
#
# MaxSessions is raised off its stock 10. Past that limit sshd queues rather
# than failing - measured on the simulated fleet to parallelism 32, zero
# failures, latency 11.8 -> 23.0 ms - so this is a latency term and not a
# correctness one; the run's own parallelism is 8 per host, but teardown and the
# evidence pulls burst above it.
# ---------------------------------------------------------------------------
if ! grep -qE '^[[:space:]]*Include[[:space:]]+/etc/ssh/sshd_config\.d/\*\.conf' /etc/ssh/sshd_config; then
    warn "sshd_config has no Include for /etc/ssh/sshd_config.d; this image is not the one this was derived on"
    exit 65
fi

mkdir -p "${VSLAB_KEYS_DIR}"
chown root:root "${VSLAB_KEYS_DIR}"
chmod 755 "${VSLAB_KEYS_DIR}"

sshd_candidate="$(mktemp)"
cat > "${sshd_candidate}" <<EOF
# Written by scripts/ecs_host_prepare.sh. Sorts before the image's own
# 50-/60-cloudimg drop-ins, and sshd keeps the first value it sees.

# Two authorized-keys files, and the second one is the point.
#
# On GCE, google-guest-agent owns ~/.ssh/authorized_keys and rewrites it from
# instance metadata. Measured on a real instance: a key appended there by hand
# authenticated once and was revoked within minutes, with the agent's own
# journal showing "Updating keys for user ...". The fleet manifest carries a
# *static* key and MultiplexedSshTransport runs with BatchMode=yes, so a key
# that disappears mid-run does not degrade - it fails every host at once.
#
# So the agent keeps its file, and the fleet gets one nothing rewrites.
# Console SSH and \`gcloud compute ssh\` keep working unchanged. Proven on a
# real instance by emptying the agent's file completely and logging in again.
#
# The image ships the *mechanism* and no key: a fleet key baked into an image is
# a key on every host forever.
AuthorizedKeysFile .ssh/authorized_keys ${VSLAB_KEYS_DIR}/%u

# The transport runs BatchMode=yes, so anything that would prompt is a hang
# rather than a refusal.
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitUserEnvironment no
# The controller has no reverse DNS for a fleet host, and a lookup would only
# add latency to every master handshake.
UseDNS no
# One ssh master per host carries every command; sessions multiplex over it.
MaxSessions 64
# Masters for a whole fleet are opened at once at the start of a run.
MaxStartups 30:50:120
EOF

install -m 0644 -o root -g root "${sshd_candidate}" "${SSHD_DROPIN}.candidate"
if sshd -t -f /etc/ssh/sshd_config 2>/dev/null; then
    : # current config is fine; test the candidate by swapping it in below
fi
mv "${SSHD_DROPIN}.candidate" "${SSHD_DROPIN}.new"
# Validated before it is adopted. A broken sshd config on a remote host with no
# console is unrecoverable, so the new file is only moved into place after the
# whole configuration parses with it present.
old_backup=""
if [ -f "${SSHD_DROPIN}" ]; then
    old_backup="$(mktemp)"
    cp "${SSHD_DROPIN}" "${old_backup}"
fi
mv "${SSHD_DROPIN}.new" "${SSHD_DROPIN}"
if sshd -t -f /etc/ssh/sshd_config; then
    log "sshd drop-in installed and the configuration validates"
else
    warn "sshd rejected the configuration; rolling back"
    if [ -n "${old_backup}" ]; then cp "${old_backup}" "${SSHD_DROPIN}"; else rm -f "${SSHD_DROPIN}"; fi
    rm -f "${sshd_candidate}" "${old_backup}"
    exit 65
fi
rm -f "${sshd_candidate}" "${old_backup}"

# This image socket-activates ssh: `ssh.socket` is enabled and `ssh.service` is
# disabled, with Accept=no, so systemd holds the listener and starts the daemon
# on the first connection. Enabling `ssh` here would be wrong and enabling
# `ssh.socket` is already done by the image; what matters is that the daemon
# re-reads this drop-in, which a reload does.
if [ -d /run/systemd/system ]; then
    systemctl reload ssh 2>/dev/null || systemctl restart ssh.socket 2>/dev/null || true
    log "sshd reloaded"
else
    skip "no systemd running here; reload sshd on the real host"
fi

# ---------------------------------------------------------------------------
# 2b. The fleet user is root, and this only checks that it can still log in.
#
# `sudo` appears nowhere in `runtime/` - measured by grep over the whole package.
# The backend runs every command as the manifest user directly, and those
# commands write under /opt, install iptables chains, read `/proc/<pid>/cwd` for
# processes it does not own, and signal them. So the manifest's
# `control_endpoint.user` has to be root; a sudo account would need the product
# to prepend `sudo`, which would change the argv of every row in the command log
# that the equivalence diff compares field by field.
#
# That is also what the simulated fleet does, and its Dockerfile states the same
# reasoning: "root is what this harness offers because the partition actuator
# needs NET_ADMIN and adding a sudo path would be surface with nothing behind
# it." Keeping the real fleet on root keeps M3-B to one changed variable.
#
# No user is created here and no key is placed. The operator drops the fleet
# public key at ${VSLAB_KEYS_DIR}/root, which §2's AuthorizedKeysFile already
# reads and which google-guest-agent does not manage.
_root_login="$(sshd -T 2>/dev/null | awk 'tolower($1)=="permitrootlogin"{print $2}')"
case "${_root_login}" in
    prohibit-password|without-password|forced-commands-only|yes)
        log "key-based root login is permitted (PermitRootLogin ${_root_login})" ;;
    "")
        warn "could not read PermitRootLogin; the fleet user must be able to log in as root" ;;
    *)
        warn "PermitRootLogin is ${_root_login}; the manifest user must be root and could not log in" ;;
esac

# ---------------------------------------------------------------------------
# 3. ufw.
#
# The fault actuator installs its own iptables chains and both cleanup paths
# find them by a comment. ufw owns the packet filter on a host it runs on and
# reloads it out from under anything that did not go through ufw, so a reload
# mid-run would silently undo a partition the run believes is in place. It is
# not a dependency of anything here, and on GCE the network boundary that
# matters is the VPC firewall rather than a host one.
# ---------------------------------------------------------------------------
if [ -d /run/systemd/system ] && systemctl list-unit-files ufw.service >/dev/null 2>&1; then
    case "$(unit_state ufw)" in
        masked) _ufw_done=1 ;;
        *) _ufw_done=0 ;;
    esac
    if [ "${_ufw_done}" = "1" ] && ! systemctl is-active --quiet ufw 2>/dev/null; then
        skip "ufw already disabled and masked"
    else
        command -v ufw >/dev/null 2>&1 && ufw --force disable >/dev/null 2>&1 || true
        systemctl disable --now ufw >/dev/null 2>&1 || true
        systemctl mask ufw >/dev/null 2>&1 || true
        log "ufw disabled and masked"
    fi
else
    skip "ufw not present"
fi

# ---------------------------------------------------------------------------
# 4. Unattended upgrades.
#
# A measurement fleet is not a production fleet. An exact-200 run takes ~26
# minutes and the lab's results are latency tails, formation dwell and failover
# RTO; a package upgrade landing mid-run - worse, one that restarts sshd, which
# is the run's only control channel - is an unrecorded variable in exactly the
# numbers being measured. Disabled rather than rescheduled, because a window
# that merely moves is still a window.
# ---------------------------------------------------------------------------
if [ -d /run/systemd/system ]; then
    changed=0
    for unit in unattended-upgrades.service apt-daily.timer apt-daily-upgrade.timer; do
        if systemctl list-unit-files "${unit}" >/dev/null 2>&1; then
            [ "$(unit_state "${unit}")" = "masked" ] && continue
            systemctl disable --now "${unit}" >/dev/null 2>&1 || true
            systemctl mask "${unit}" >/dev/null 2>&1 || true
            changed=1
        fi
    done
    [ "${changed}" = "1" ] && log "unattended upgrades and apt timers disabled" \
                           || skip "unattended upgrades already disabled"
else
    skip "no systemd here; disable unattended-upgrades on the real host"
fi

# ---------------------------------------------------------------------------
# 5. The bundle install root.
#
# Created here so that the first thing a run does on this host is not also the
# first thing that ever wrote to /opt. Root-owned 0755: a host whose install
# root were writable by anyone would make the digest check on the archive
# pointless.
# ---------------------------------------------------------------------------
if [ -d "${NATIVE_INSTALL_ROOT}" ]; then
    skip "${NATIVE_INSTALL_ROOT} already exists"
else
    mkdir -p "${NATIVE_INSTALL_ROOT}"
    chown root:root /opt/valkey-scale-lab "${NATIVE_INSTALL_ROOT}"
    chmod 755 /opt/valkey-scale-lab "${NATIVE_INSTALL_ROOT}"
    log "created ${NATIVE_INSTALL_ROOT}"
fi

if [ "${DO_TUNING}" = "0" ]; then
    skip "tuning skipped by --no-tuning"
else

# ---------------------------------------------------------------------------
# 6. Descriptor limits.
#
# A native run places exactly one nodehost per host and
# `max_logical_nodes_per_nodehost` is 25, so this host carries 25 valkey-server
# processes, each of which asks for its default 10000 maxclients plus overhead.
# Measured in a real native exact-200 run: 413 open descriptors per node, about
# 10,300 per host, on top of ~5,000 cluster-bus sockets from the 199-peer mesh.
#
# The stock image gives an ssh session **1024** soft - measured. Valkey silently
# lowers maxclients when it cannot get the descriptors it wants, which would
# make a capacity result a fact about ulimit rather than about Valkey.
#
# Set in three places because three of them apply, and which one binds depends
# on how the process was started: PAM limits for an ssh login (which is how
# `start_all.sh` runs), the systemd manager default, and ssh.service's own
# limit, since this image socket-activates sshd and a service's LimitNOFILE
# caps what its children can raise themselves to.
# ---------------------------------------------------------------------------
    cat > "${LIMITS_FILE}" <<'EOF'
# Written by scripts/ecs_host_prepare.sh.
# 25 valkey-server processes per host, each defaulting to maxclients 10000.
*     soft  nofile  1048576
*     hard  nofile  1048576
root  soft  nofile  1048576
root  hard  nofile  1048576
EOF
    log "wrote ${LIMITS_FILE}"

    mkdir -p "${SYSTEMD_DROPIN_DIR}"
    cat > "${SYSTEMD_DROPIN}" <<'EOF'
# Written by scripts/ecs_host_prepare.sh.
[Manager]
DefaultLimitNOFILE=1048576:1048576
EOF
    mkdir -p "${SSH_UNIT_DROPIN_DIR}"
    cat > "${SSH_UNIT_DROPIN}" <<'EOF'
# Written by scripts/ecs_host_prepare.sh.
# This image socket-activates sshd, so a login session is a child of
# ssh.service and inherits its limit as a ceiling.
[Service]
LimitNOFILE=1048576
EOF
    log "wrote the systemd manager and ssh.service descriptor limits"

# ---------------------------------------------------------------------------
# 7. /tmp.
#
# `RUN_STATE_ROOT` is /tmp/valkey-scale-lab and `BUNDLE_DROP_ROOT` is /tmp, so
# every node's data directory, its RDB, its journal, the copied resource-agent
# package and the 14 MB bundle archive all land under /tmp. This image mounts
# /tmp as **tmpfs** - measured, 3.9 G on a 7.9 GiB instance, which is RAM.
#
# That is not a capacity problem so much as a measurement one. `node_memory_
# limit_mb` is 64 and 25 nodes cap out at 1.6 GB of dataset, which fits; but it
# would be held in page cache and counted against the very `MemAvailable` the
# §11.1 sampler reports, so the run's own memory evidence would conflate dataset
# storage with process footprint. The frozen simulated baselines were taken with
# /tmp on a container's overlay filesystem, i.e. on disk.
#
# Masking tmp.mount returns /tmp to an ordinary directory on the root
# filesystem - 36 G here against 3.9 G of RAM - and is reversible with a single
# `systemctl unmask`. Use --keep-tmpfs to decline.
# ---------------------------------------------------------------------------
    if [ "${KEEP_TMPFS}" = "1" ]; then
        skip "/tmp left as-is by --keep-tmpfs"
    elif [ ! -d /run/systemd/system ]; then
        skip "no systemd here; mask tmp.mount on the real host to take /tmp off tmpfs"
    elif [ "$(unit_state tmp.mount)" = "masked" ]; then
        # Masked is the durable state; whether /tmp is *still* tmpfs right now
        # only says whether this host has rebooted since, which is not something
        # to re-mask over.
        if [ "$(findmnt -no FSTYPE /tmp 2>/dev/null || echo none)" = "tmpfs" ]; then
            skip "tmp.mount already masked; /tmp is still tmpfs until this host reboots"
        else
            skip "tmp.mount already masked and /tmp is on disk"
        fi
    else
        systemctl mask tmp.mount >/dev/null 2>&1 || true
        log "masked tmp.mount; /tmp moves to the root filesystem at next boot"
    fi

# ---------------------------------------------------------------------------
# 8. Kernel parameters.
#
# Written as a file first and applied live second: a container refuses most of
# these and a real host does not, and a failure to apply live is not a failure
# to prepare an image.
# ---------------------------------------------------------------------------
    cat > "${SYSCTL_FILE}" <<'EOF'
# Written by scripts/ecs_host_prepare.sh.

# 25 nodes x 10000 maxclients, plus the cluster-bus mesh between every pair of
# nodes in the fleet - measured at ~5,000 bus sockets per host at exact-200.
fs.file-max = 2097152
fs.nr_open = 1048576

# Valkey's tcp-backlog defaults to 511 and it logs the mismatch when somaxconn
# is lower. This image already ships 4096; stated so a different one is covered.
net.core.somaxconn = 4096
net.ipv4.tcp_max_syn_backlog = 8192

# The run's node configs set no `save` directive, so Valkey's built-in save
# policy is active and a background save forks the whole process - the mechanism
# roadmap `313cacc9` traced a real failure to. Measured on a stock instance:
# vm.overcommit_memory is 0 and valkey-server itself prints
# "WARNING Memory overcommit must be enabled!" on startup.
vm.overcommit_memory = 1

# Each node dials every peer on the cluster bus. The stock range is 32768-60999.
net.ipv4.ip_local_port_range = 10240 65535
net.ipv4.tcp_tw_reuse = 1

# The partition actuator installs plain filter rules and needs no connection
# tracking, but a full conntrack table drops packets that look exactly like a
# cluster-bus failure. Stock here is 262144.
net.netfilter.nf_conntrack_max = 1048576
EOF
    log "wrote ${SYSCTL_FILE}"

    applied=0; refused=0
    while IFS= read -r line; do
        case "$line" in ''|\#*) continue ;; esac
        key="$(printf '%s' "$line" | cut -d= -f1 | tr -d ' ')"
        # Trimmed at the ends only. `tr -d ' '` would collapse the *two* values
        # of net.ipv4.ip_local_port_range into one number and the kernel refuses
        # it - measured, that was this loop's one refusal on a real host.
        value="$(printf '%s' "$line" | sed 's/^[^=]*=[[:space:]]*//; s/[[:space:]]*$//')"
        if sysctl -q -w "${key}=${value}" >/dev/null 2>&1; then
            applied=$((applied + 1))
        else
            refused=$((refused + 1))
        fi
    done < "${SYSCTL_FILE}"
    log "sysctl applied ${applied}, refused ${refused}"

# ---------------------------------------------------------------------------
# 9. Transparent huge pages.
#
# Valkey names this one itself, in its own startup log, because THP makes the
# copy-on-write of a background save expensive and the latency shows up in
# exactly the tail this lab measures. Measured stock on this image: `madvise`.
# ---------------------------------------------------------------------------
    cat > "${THP_UNIT}" <<'EOF'
[Unit]
Description=Disable transparent huge pages for valkey-scale-lab
DefaultDependencies=no
After=sysinit.target local-fs.target
Before=ssh.service

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'echo never > /sys/kernel/mm/transparent_hugepage/enabled || true'
ExecStart=/bin/sh -c 'echo never > /sys/kernel/mm/transparent_hugepage/defrag || true'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
    if [ -d /run/systemd/system ]; then
        systemctl daemon-reload >/dev/null 2>&1 || true
        systemctl enable valkey-scale-lab-thp.service >/dev/null 2>&1 || true
        systemctl start valkey-scale-lab-thp.service >/dev/null 2>&1 || true
        log "transparent huge pages disabled, now and at boot"
    else
        skip "no systemd here; ${THP_UNIT} written for the real host"
    fi

# cgroup v2 needs nothing on this image - it is already the default, which the
# CentOS predecessor of this script had to request with a kernel argument and a
# reboot. Verified rather than set, so that an image which is not v2 is noticed.
    case "$(stat -fc %T /sys/fs/cgroup 2>/dev/null)" in
        cgroup2fs) log "cgroup v2 already active" ;;
        *) warn "cgroup is not v2; the §11.1 sampler reads v2 filenames and would record nulls" ;;
    esac
fi

# ---------------------------------------------------------------------------
# 10. Time.
# ---------------------------------------------------------------------------
if [ -d /run/systemd/system ]; then
    systemctl enable chrony >/dev/null 2>&1 || systemctl enable chronyd >/dev/null 2>&1 || true
    systemctl start chrony >/dev/null 2>&1 || systemctl start chronyd >/dev/null 2>&1 || true
    log "chrony enabled"
else
    skip "no systemd here; chrony is installed and will start on the real host"
fi

# ---------------------------------------------------------------------------
# 11. Image finalization.
#
# Only under --finalize-image, and last, because it removes the very things that
# make this host usable right now. Run it as the final step of the bake, then
# stop the instance and create the image from its disk.
# ---------------------------------------------------------------------------
if [ "${DO_FINALIZE}" = "1" ]; then
    log "finalizing for an image bake"

    # The roadmap item 1.0 defect, at image scale: two simulated hosts once
    # served one fingerprint because their keys were generated during the image
    # build. cloud-init regenerates these on first boot when they are absent.
    rm -f /etc/ssh/ssh_host_*
    log "removed ssh host keys; cloud-init regenerates them per instance at boot"

    # No fleet key is baked. The mechanism is baked; the key is the operator's,
    # per instance.
    rm -f "${VSLAB_KEYS_DIR}"/* 2>/dev/null || true
    log "cleared ${VSLAB_KEYS_DIR} (the mechanism stays, no key ships)"

    # Anything a run left, if this host was used before it was baked.
    rm -rf /tmp/valkey-scale-lab /tmp/vslab-load-lane 2>/dev/null || true
    rm -rf /tmp/vslab-bundle-* 2>/dev/null || true
    rm -rf "${NATIVE_INSTALL_ROOT:?}"/* 2>/dev/null || true
    log "removed run state, bundles and load-lane directories"

    cloud-init clean --logs >/dev/null 2>&1 || true
    : > /etc/machine-id
    rm -f /var/lib/dbus/machine-id 2>/dev/null || true
    apt-get clean >/dev/null 2>&1 || true
    rm -rf /var/lib/apt/lists/* 2>/dev/null || true
    find /var/log -type f -exec truncate -s 0 {} \; 2>/dev/null || true
    rm -f /root/.ssh/known_hosts /home/*/.ssh/known_hosts 2>/dev/null || true
    log "cleared cloud-init state, machine-id, apt cache and logs"
    log "now stop the instance and create the image from its disk"
fi

log "done. Run ecs_host_verify.sh to check this host against the native backend."
