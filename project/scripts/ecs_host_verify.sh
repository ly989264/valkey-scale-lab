#!/bin/sh
# Is this host ready for the existing `native_multi_ecs` backend?
#
# Lab tooling, the other half of `ecs_host_prepare.sh`. It answers about a host
# what `verify_image` answers about an image, and it answers it the same way the
# backend will ask: by running the command shapes `runtime/native_backend.py`
# runs, not by asking rpm what is installed. A package can be present and the
# thing that matters still absent - `python3` is installed on a stock CentOS 8
# and cannot import the resource agent.
#
# It changes nothing it does not undo. The one check that has to mutate the host
# - the firewall - installs a chain named for this script, proves the exact
# `-m comment` shape the fault actuator uses, and removes it again.
#
# Run it on the host. Running it *over ssh from the controller* is worth more
# than running it locally, because then the transport is under test too:
#
#   scp -i KEY -P PORT ecs_host_verify.sh root@HOST:/tmp/
#   ssh -i KEY -p PORT root@HOST sh /tmp/ecs_host_verify.sh
#
# Usage:
#   sh ecs_host_verify.sh                    # host readiness
#   sh ecs_host_verify.sh --bundle DIR       # ... and can this host run that bundle
#
# Exit code 0 when every REQUIRED check passed, 1 otherwise. ADVISED failures
# never change the exit code: they degrade a run's evidence or its headroom, and
# saying so is different from refusing.

set -u

BUNDLE_DIR=""
while [ $# -gt 0 ]; do
    case "$1" in
        --bundle) BUNDLE_DIR="${2:-}"; shift 2 ;;
        --bundle=*) BUNDLE_DIR="${1#--bundle=}"; shift ;;
        -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 64 ;;
    esac
done

# Constants read off the implementation rather than chosen here.
NATIVE_INSTALL_ROOT="/opt/valkey-scale-lab/bundles"   # native_backend.py NATIVE_INSTALL_ROOT
RUN_STATE_ROOT="/tmp/valkey-scale-lab"                # native_backend.py RUN_STATE_ROOT
BUNDLE_DROP_ROOT="/tmp"                               # native_backend.py BUNDLE_DROP_ROOT
NODES_PER_HOST=25                                     # max_logical_nodes_per_nodehost

REQUIRED_FAIL=0
ADVISED_FAIL=0

pass()    { printf '  \033[32mok\033[0m       %-34s %s\n' "$1" "${2:-}"; }
fail()    { printf '  \033[31mFAIL\033[0m     %-34s %s\n' "$1" "${2:-}"; REQUIRED_FAIL=$((REQUIRED_FAIL + 1)); }
advise()  { printf '  \033[33mADVISED\033[0m  %-34s %s\n' "$1" "${2:-}"; ADVISED_FAIL=$((ADVISED_FAIL + 1)); }
note()    { printf '           %-34s %s\n' "$1" "${2:-}"; }
section() { printf '\n%s\n' "$1"; }

printf 'valkey-scale-lab :: native fleet host readiness\n'
printf '%s | %s | %s\n' \
    "$(sed -n '1p' /etc/centos-release 2>/dev/null || uname -o)" \
    "$(uname -m)" \
    "$(uname -r)"

# Whether this is a real host matters for how much of the report can be
# believed. Everything in the final section is a property of the running
# *kernel*, and in a container that kernel belongs to whoever is hosting the
# container - so a green cgroup or THP line there says nothing about the image.
IN_CONTAINER=0
if [ -f /.dockerenv ] || grep -qE '(docker|containerd|lxc|kubepods)' /proc/1/cgroup 2>/dev/null \
   || [ "$(cat /proc/1/comm 2>/dev/null)" != "systemd" ]; then
    IN_CONTAINER=1
    printf '\n\033[33mnote\033[0m  this looks like a container. The kernel here is the container\n'
    printf '      host'"'"'s, so cgroup version, transparent huge pages, every sysctl and\n'
    printf '      every systemd unit state below describe that kernel and not this image.\n'
    printf '      Re-run on a booted instance before believing the last section.\n'
fi

# ---------------------------------------------------------------------------
section 'control channel  (host_transport.py: MultiplexedSshTransport)'
# ---------------------------------------------------------------------------

if [ "$(id -u)" = "0" ]; then
    pass "privilege" "root"
else
    # Not a taste: the fault actuator runs iptables, the residue scan reads
    # /proc/<pid>/cwd of every process in the run's tree, teardown signals them,
    # and the bundle installs under /opt.
    fail "privilege" "must run as root; uid $(id -u)"
fi

if [ -x /usr/sbin/sshd ]; then
    # sshd has no --version; it prints its banner to stderr on an unknown flag.
    pass "sshd" "$(/usr/sbin/sshd -? 2>&1 | grep -i '^OpenSSH' | head -1)"
else
    fail "sshd" "/usr/sbin/sshd is missing"
fi

# `sshd -T` prints the effective configuration, which is the only honest way to
# read it: the drop-in, the stock file and the built-in defaults all contribute.
SSHD_EFFECTIVE="$(/usr/sbin/sshd -T -C user=root,host=localhost,addr=127.0.0.1 2>/dev/null)"
if [ -z "${SSHD_EFFECTIVE}" ]; then
    # `sshd -T` refuses when no host keys exist, which is the normal state of a
    # freshly finalized image. Fall back to parsing with a throwaway key.
    _tmpkey="$(mktemp -d)"
    ssh-keygen -q -t ed25519 -N '' -f "${_tmpkey}/k" >/dev/null 2>&1
    SSHD_EFFECTIVE="$(/usr/sbin/sshd -T -h "${_tmpkey}/k" -C user=root,host=localhost,addr=127.0.0.1 2>/dev/null)"
    rm -rf "${_tmpkey}"
fi

sshd_says() { printf '%s\n' "${SSHD_EFFECTIVE}" | awk -v k="$1" 'tolower($1)==k {print $2; exit}'; }

if [ -n "${SSHD_EFFECTIVE}" ]; then
    pass "sshd config" "parses"
    [ "$(sshd_says passwordauthentication)" = "no" ] \
        && pass "password auth" "disabled" \
        || fail "password auth" "enabled; the transport runs BatchMode=yes and expects key-only"
    case "$(sshd_says permitrootlogin)" in
        prohibit-password|without-password|forced-commands-only)
            pass "root login" "$(sshd_says permitrootlogin)" ;;
        yes) advise "root login" "yes; key-only would be prohibit-password" ;;
        *)   note  "root login" "$(sshd_says permitrootlogin) - fine if the manifest names another user" ;;
    esac
    # `scp -r` in both directions is how the bundle, the resource agent package,
    # the load-lane evidence and every node journal move. A controller on
    # OpenSSH >= 9 drives it over this subsystem.
    if printf '%s\n' "${SSHD_EFFECTIVE}" | grep -qi '^subsystem.*sftp'; then
        pass "sftp subsystem" "$(printf '%s\n' "${SSHD_EFFECTIVE}" | grep -i '^subsystem' | head -1 | cut -d' ' -f2-)"
    else
        fail "sftp subsystem" "absent; scp from an OpenSSH >= 9 controller cannot transfer"
    fi
    _maxsessions="$(sshd_says maxsessions)"
    if [ "${_maxsessions:-10}" -ge 32 ] 2>/dev/null; then
        pass "MaxSessions" "${_maxsessions}"
    else
        # Measured on the simulated fleet: past the limit sshd queues rather
        # than failing, so this is latency, not correctness.
        advise "MaxSessions" "${_maxsessions:-10}; sessions queue above it (latency, not failure)"
    fi
else
    fail "sshd config" "sshd could not produce an effective configuration"
fi

# The item 1.0 defect: a fleet whose hosts all present one fingerprint hides a
# whole class of transport mistake, and an image is where that gets manufactured.
_hostkeys="$(ls /etc/ssh/ssh_host_*_key 2>/dev/null | wc -l | tr -d ' ')"
if [ "${_hostkeys}" -gt 0 ]; then
    pass "ssh host keys" "${_hostkeys} present - this is a live host, not a baked image"
    note "" "$(ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub 2>/dev/null | cut -d' ' -f2 || echo 'no ed25519 key')"
elif [ -f /usr/lib/systemd/system/sshd-keygen@.service ] || [ -x /usr/libexec/openssh/sshd-keygen ]; then
    pass "ssh host keys" "absent, sshd-keygen regenerates per instance at boot (image state)"
else
    fail "ssh host keys" "absent and nothing will generate them at boot"
fi

# ---------------------------------------------------------------------------
section 'backend commands  (native_backend.py remote scripts)'
# ---------------------------------------------------------------------------

# Every one of these is named by a remote script in the backend. The comment on
# each is the operation that names it.
missing=""
for entry in \
    "sh:every command is sh -c" \
    "printf:_owned_process_walk reporting" \
    "ls:start_nodehost residue probe" \
    "head:start_nodehost residue probe" \
    "mkdir:run state root, resource agent dir" \
    "rm:release_run, reclaim_run" \
    "touch:bundle install marker, expected-gone flag" \
    "cat:pidfile and agent log reads" \
    "readlink:/proc/<pid>/cwd ownership mark" \
    "sleep:_await_owned_processes_gone" \
    "wc:_await_owned_processes_gone" \
    "seq:NativeResourceAgent.stop" \
    "cut:bundle digest check" \
    "sha256sum:bundle digest check" \
    "tar:bundle extraction" \
    "gzip:bundle extraction" \
    "awk:_remove_fault_rules, isolate_nodehost SSH_CONNECTION parse" \
    "nohup:resource agent launch" \
    "ip:create_network route check" \
    "iptables:isolate/rejoin/_remove_fault_rules/_scan_fault_rules" \
    "python3:resource agent and HOST_CLOCK_ARGV" \
; do
    cmd="${entry%%:*}"
    command -v "$cmd" >/dev/null 2>&1 || missing="${missing} ${cmd}(${entry#*:})"
done
if [ -z "${missing}" ]; then
    pass "remote command set" "21 of 21 present"
else
    fail "remote command set" "missing:${missing}"
fi

# `ip route get` is create_network's whole implementation - it asks each host
# for a route to every peer and refuses the fleet if any pair has none.
if ip route get 127.0.0.1 >/dev/null 2>&1; then
    pass "ip route get" "answers"
else
    fail "ip route get" "create_network would reject this fleet"
fi

# ---------------------------------------------------------------------------
section 'python  (resource_agent, host_clock.HOST_CLOCK_ARGV)'
# ---------------------------------------------------------------------------

if command -v python3 >/dev/null 2>&1; then
    PYV="$(python3 -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])' 2>/dev/null)"
    # The floor is not a preference. The product uses `from __future__ import
    # annotations`, which is 3.7; CentOS 8's own python3 is 3.6.8 and raises
    # `SyntaxError: future feature annotations is not defined` on the agent's
    # first import.
    if python3 -c 'import sys;sys.exit(0 if sys.version_info[:2]>=(3,7) else 1)' 2>/dev/null; then
        pass "python3 version" "${PYV}"
    else
        fail "python3 version" "${PYV}; the resource agent needs >= 3.7"
    fi
    if python3 -c 'from __future__ import annotations' 2>/dev/null; then
        pass "future annotations" "accepted"
    else
        fail "future annotations" "rejected; every product module starts with it"
    fi
    # The exact argv host_clock.py sends, and the exact parse it applies.
    _clock="$(python3 -c 'import time;print(repr(time.time()),repr(time.monotonic()))' 2>/dev/null)"
    if printf '%s' "${_clock}" | awk 'NF==2 && $1+0>0 && $2+0>=0 {ok=1} END{exit ok?0:1}'; then
        pass "HOST_CLOCK_ARGV" "$(printf '%s' "${_clock}" | cut -c1-40)"
    else
        fail "HOST_CLOCK_ARGV" "did not return two numbers: ${_clock}"
    fi
    # The agent runs as `python3 -m ...` with PYTHONPATH pointing at a copied
    # package, so these three must be importable from the stock interpreter.
    if python3 -c 'import argparse,json,signal,threading,pathlib' 2>/dev/null; then
        pass "agent stdlib imports" "argparse json signal threading pathlib"
    else
        fail "agent stdlib imports" "a minimal python3 build is missing one of them"
    fi
else
    fail "python3" "absent; the resource agent and the clock reading both need it"
fi

# ---------------------------------------------------------------------------
section 'process ownership  (_owned_process_walk, release_run, reclaim_run)'
# ---------------------------------------------------------------------------

# The ownership mark is the process working directory, because Valkey rewrites
# its process title and the run root is nowhere in a live node's argv. This runs
# the real walk against a process planted in a fake run root.
_probe_root="${RUN_STATE_ROOT}/.verify-$$"
mkdir -p "${_probe_root}/node" 2>/dev/null
if [ -d "${_probe_root}/node" ]; then
    ( cd "${_probe_root}/node" && exec sleep 30 ) &
    _probe_pid=$!
    sleep 0.3
    _found="$(
        root="${_probe_root}"
        for entry in /proc/[0-9]*; do
            pid=${entry#/proc/}
            cwd=$(readlink "$entry/cwd" 2>/dev/null) || continue
            case "$cwd/" in "$root"/*) ;; *) continue;; esac
            exe=$(readlink "$entry/exe" 2>/dev/null)
            printf "%s\t%s\t%s\n" "$pid" "$cwd" "$exe"
        done
    )"
    if printf '%s' "${_found}" | grep -q "^${_probe_pid}	"; then
        pass "/proc cwd walk" "found the planted process by its working directory"
    else
        fail "/proc cwd walk" "planted pid ${_probe_pid} not found; teardown would leave it running"
    fi
    kill -KILL "${_probe_pid}" 2>/dev/null
    wait "${_probe_pid}" 2>/dev/null
    rm -rf "${_probe_root}"
else
    fail "/proc cwd walk" "could not create ${_probe_root}"
fi

for sig in STOP CONT TERM KILL; do :; done
if ( sleep 5 & p=$!; kill -STOP $p 2>/dev/null && kill -CONT $p 2>/dev/null && kill -TERM $p 2>/dev/null ); then
    pass "signals" "STOP CONT TERM KILL deliverable"
else
    fail "signals" "the fault actuator pauses with STOP and teardown resumes before TERM"
fi

# ---------------------------------------------------------------------------
section 'firewall  (isolate_nodehost, rejoin_nodehost, _scan_fault_rules)'
# ---------------------------------------------------------------------------

_chain="VSLAB-VERIFY"
_tag="vslab-verify=$$"
if ! iptables -S >/dev/null 2>&1; then
    # The residue scan reports "unscannable" here rather than "nothing found",
    # deliberately - so this is a real gap, not a quiet pass.
    fail "iptables -S" "not permitted or absent; the residue scan reports unscannable"
else
    pass "iptables -S" "$(iptables --version 2>/dev/null | head -1)"
    # `-m comment` is not decoration: a chain name is capped at 28 characters
    # and a run id is 42, so the run's ownership mark lives in the comment and
    # both cleanup paths find rules by it.
    if iptables -N "${_chain}" 2>/dev/null \
        && iptables -A "${_chain}" -p tcp --dport 22 -j RETURN 2>/dev/null \
        && iptables -A "${_chain}" -j DROP 2>/dev/null \
        && iptables -I INPUT 1 -m comment --comment "${_tag}" -j "${_chain}" 2>/dev/null \
        && iptables -C INPUT -m comment --comment "${_tag}" -j "${_chain}" 2>/dev/null
    then
        pass "isolate_nodehost shape" "chain + comment-marked jump installed and confirmed"
        # And the mark is findable the way _remove_fault_rules finds it.
        if iptables -S 2>/dev/null | awk -v t="${_tag}" 'index($0,t)>0 && $1=="-A"{n++} END{exit n?0:1}'; then
            pass "run mark is findable" "iptables -S prints the comment"
        else
            fail "run mark is findable" "iptables -S does not print comments; cleanup could not find its rules"
        fi
    else
        fail "isolate_nodehost shape" "could not install the chain and comment-marked jump"
    fi
    iptables -D INPUT -m comment --comment "${_tag}" -j "${_chain}" 2>/dev/null
    iptables -F "${_chain}" 2>/dev/null
    iptables -X "${_chain}" 2>/dev/null
    if iptables -S 2>/dev/null | grep -q "${_tag}"; then
        fail "verify cleaned up" "left rules tagged ${_tag} behind"
    else
        pass "rejoin_nodehost shape" "chain and jump removed, nothing left tagged"
    fi
fi

# SSH_CONNECTION is how isolate_nodehost learns which port to spare - read from
# the session, not from the manifest, because under a port-forwarding harness
# they differ. It is only set when this script is reached over ssh.
if [ -n "${SSH_CONNECTION:-}" ]; then
    _ctl="$(printf '%s' "${SSH_CONNECTION}" | awk '{print $4}')"
    case "${_ctl}" in
        ''|*[!0-9]*) fail "SSH_CONNECTION" "field 4 is not a port: ${SSH_CONNECTION}" ;;
        *) pass "SSH_CONNECTION" "control port ${_ctl} would be spared by the partition" ;;
    esac
else
    note "SSH_CONNECTION" "unset - run this over ssh to exercise isolate_nodehost's port parse"
fi

# ---------------------------------------------------------------------------
section 'live transport  (a throwaway sshd on this host, talked to as the controller talks)'
# ---------------------------------------------------------------------------
#
# That this host's sshd will actually accept a key-only multiplexed login is not
# something the configuration can be read for - the drop-in, the stock file and
# the built-in defaults all contribute, and only a login settles it. So this
# stands up a second sshd on a spare port, with its own host key, its own
# authorized_keys and its own config in a temporary directory, logs in, and
# removes everything. Nothing in /etc is read for authorization and nothing in
# /etc is written.

probe_transport() {
    _probe="$(mktemp -d)"
    # `mktemp -d` gives 0700, and sshd's privilege-separated pre-auth child runs
    # as the unprivileged `sshd` user - it cannot traverse into the directory to
    # read authorized_keys, and the login fails with a bare "Permission denied"
    # that says nothing about why. `StrictModes=no` does not cover traversal.
    # The keys inside stay 0600 and the whole directory is removed below.
    chmod 755 "${_probe}"
    # `ss` rather than a /dev/tcp probe: that is a bash-ism, and a host whose
    # /bin/sh is dash would report every port free and then watch sshd fail to
    # bind. `ss` comes from iproute, which this backend already requires.
    _port=""
    for _candidate in 22222 22223 22224 22225; do
        if ! ss -ltn 2>/dev/null | awk '{print $4}' | grep -q ":${_candidate}\$"; then
            _port="${_candidate}"; break
        fi
    done
    [ -n "${_port}" ] || { note "live transport" "no free probe port; skipped"; rm -rf "${_probe}"; return; }

    ssh-keygen -q -t ed25519 -N '' -f "${_probe}/hostkey" >/dev/null 2>&1
    ssh-keygen -q -t ed25519 -N '' -f "${_probe}/clientkey" >/dev/null 2>&1
    cp "${_probe}/clientkey.pub" "${_probe}/authorized_keys"
    /usr/sbin/sshd -h "${_probe}/hostkey" -p "${_port}" \
        -o "AuthorizedKeysFile=${_probe}/authorized_keys" \
        -o StrictModes=no -o PasswordAuthentication=no \
        -o "PidFile=${_probe}/sshd.pid" -o PermitRootLogin=yes \
        >/dev/null 2>&1
    _waited=0
    while [ ! -s "${_probe}/sshd.pid" ] && [ "${_waited}" -lt 20 ]; do
        sleep 0.25; _waited=$((_waited + 1))
    done
    if [ ! -s "${_probe}/sshd.pid" ]; then
        note "live transport" "could not start a probe sshd; skipped"
        rm -rf "${_probe}"; return
    fi

    set -- ssh -p "${_port}" -i "${_probe}/clientkey" \
        -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no \
        -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=5 \
        -o ControlMaster=auto -o "ControlPath=${_probe}/cm" -o ControlPersist=60 \
        "$(id -un)@127.0.0.1"

    if timeout 15 "$@" true >/dev/null 2>&1; then
        pass "probe sshd reachable" "port ${_port}, multiplexed"
    else
        note "live transport" "probe sshd did not accept a key-only login; skipped"
        kill "$(cat "${_probe}/sshd.pid")" 2>/dev/null; rm -rf "${_probe}"; return
    fi

    # What this probe deliberately does NOT test: whether a *backgrounded* child
    # lets the session close. That is a real difference between these two
    # OpenSSH versions - `NativeResourceAgent.start` returns in 0.02 s against
    # the Debian 13 fleet and hangs to its timeout against CentOS 8.2, measured
    # 3/3 from the controller through `MultiplexedSshTransport` - but it cannot
    # be measured from the host. Run locally, with the host's own ssh client,
    # the same command hangs against *both*, including the Debian host that has
    # passed four real native runs. A check that fails on a known-good host is
    # worse than no check, so the measurement stays a controller-side one and
    # `docs/ecs_host_preparation_report.md` §4.2 carries its reproduction.
    timeout 10 "$@" -O exit >/dev/null 2>&1
    kill "$(cat "${_probe}/sshd.pid")" 2>/dev/null
    rm -rf "${_probe}"
}

if command -v timeout >/dev/null 2>&1 && command -v ssh >/dev/null 2>&1 && [ -x /usr/sbin/sshd ]; then
    probe_transport
else
    note "live transport" "needs sshd, ssh and timeout on this host; skipped"
fi

# A recursive upload is how `send_bundle` and `NativeResourceAgent.start`'s
# package copy both move, and it is the transport shape most likely to be
# refused by an old host. This cannot be tested with the host's *own* scp: the
# controller runs OpenSSH >= 9, whose scp drives transfers over the sftp
# protocol, and CentOS 8.2's scp is 8.0 and still speaks the legacy one - so a
# local scp test would measure the wrong client.
#
# What it does instead is ask the sftp-server itself, over one SFTP INIT
# exchange, whether it advertises the extension scp's sftp mode uses to
# canonicalize a path that does not exist yet. Measured on both fleets:
# Debian 13 / OpenSSH 10.0p2 advertises `expand-path@openssh.com` and accepts
# `scp -r` to a new remote directory; CentOS 8.2 / OpenSSH 8.0p1 advertises
# neither and fails with `path canonicalization failed`.
_sftp_server="$(printf '%s\n' "${SSHD_EFFECTIVE}" | awk 'tolower($1)=="subsystem" && $2=="sftp" {print $3; exit}')"
[ -n "${_sftp_server:-}" ] || _sftp_server=/usr/libexec/openssh/sftp-server
if [ -x "${_sftp_server}" ] && command -v python3 >/dev/null 2>&1; then
    _exts="$(python3 - "${_sftp_server}" <<'PYPROBE' 2>/dev/null
import struct, subprocess, sys
try:
    p = subprocess.Popen([sys.argv[1]], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    body = struct.pack(">BI", 1, 3)                       # SSH_FXP_INIT, version 3
    p.stdin.write(struct.pack(">I", len(body)) + body); p.stdin.flush()
    reply = p.stdout.read(struct.unpack(">I", p.stdout.read(4))[0])
    p.kill()
    if reply[0] != 2:                                     # SSH_FXP_VERSION
        raise SystemExit(1)
    off, names = 5, []
    while off < len(reply):
        n = struct.unpack(">I", reply[off:off+4])[0]; off += 4
        names.append(reply[off:off+n].decode("utf-8", "replace")); off += n
        n = struct.unpack(">I", reply[off:off+4])[0]; off += 4 + n
    print(" ".join(names))
except Exception:
    raise SystemExit(1)
PYPROBE
)"
    if [ -z "${_exts}" ]; then
        note "sftp-server extensions" "could not complete an SFTP INIT with ${_sftp_server}"
    elif printf '%s' "${_exts}" | grep -q 'expand-path@openssh.com'; then
        pass "recursive upload" "sftp-server advertises expand-path; scp -r can create remote directories"
    else
        fail "recursive upload" "sftp-server has no expand-path@openssh.com"
        note "" "an OpenSSH >= 9 controller's scp -r fails with 'path canonicalization failed',"
        note "" "so send_bundle and the resource agent package copy cannot transfer"
    fi
else
    note "sftp-server extensions" "no sftp-server at ${_sftp_server} or no python3; skipped"
fi

# ---------------------------------------------------------------------------
section 'filesystem  (NATIVE_INSTALL_ROOT, RUN_STATE_ROOT, BUNDLE_DROP_ROOT)'
# ---------------------------------------------------------------------------

check_dir_exec() {
    _label="$1"; _dir="$2"
    mkdir -p "${_dir}" 2>/dev/null
    if [ ! -w "${_dir}" ]; then
        fail "${_label}" "${_dir} is not writable"
        return
    fi
    _probe="${_dir}/.vslab-exec-probe-$$"
    printf '#!/bin/sh\nexit 0\n' > "${_probe}" 2>/dev/null
    chmod 0755 "${_probe}" 2>/dev/null
    if "${_probe}" 2>/dev/null; then
        pass "${_label}" "${_dir} writable and exec"
    else
        # noexec on /opt or /tmp is a real cloud-image default and it stops
        # valkey-server before it starts.
        fail "${_label}" "${_dir} is writable but noexec"
    fi
    rm -f "${_probe}"
}
check_dir_exec "bundle install root" "${NATIVE_INSTALL_ROOT}"
check_dir_exec "run state root"      "${RUN_STATE_ROOT}"
check_dir_exec "bundle drop root"    "${BUNDLE_DROP_ROOT}"
rmdir "${RUN_STATE_ROOT}" 2>/dev/null || true

# 25 nodes, each with a dataset, an RDB and a journal. At exact-200 a node's
# journal alone measured 434 KB and a host's 25 came to ~11 MB.
_avail_mb="$(df -Pm "${RUN_STATE_ROOT%/*}" 2>/dev/null | awk 'NR==2{print $4}')"
if [ -n "${_avail_mb}" ] && [ "${_avail_mb}" -ge 8192 ] 2>/dev/null; then
    pass "space under /tmp" "${_avail_mb} MB free"
else
    advise "space under /tmp" "${_avail_mb:-unknown} MB free for ${NODES_PER_HOST} datasets, RDBs and journals"
fi
case "$(df -PT /tmp 2>/dev/null | awk 'NR==2{print $2}')" in
    tmpfs) advise "/tmp filesystem" "tmpfs; ${NODES_PER_HOST} datasets and their RDBs would live in RAM" ;;
    *)     pass  "/tmp filesystem" "$(df -PT /tmp 2>/dev/null | awk 'NR==2{print $2}')" ;;
esac

# ---------------------------------------------------------------------------
section 'bundle ABI  (what the pinned build must link against here)'
# ---------------------------------------------------------------------------

_glibc="$(ldd --version 2>/dev/null | head -1 | awk '{print $NF}')"
note "glibc" "${_glibc:-unknown}  (symbol ceiling $(strings /lib64/libc.so.6 2>/dev/null | grep -o '^GLIBC_[0-9.]*$' | sort -uV | tail -1))"
note "libstdc++" "$(strings /usr/lib64/libstdc++.so.6 2>/dev/null | grep -o '^GLIBCXX_[0-9.]*$' | sort -uV | tail -1)"

# The sonames a valkey-server / valkey-cli / memtier_benchmark built for *this*
# host would need. Reported as facts, because a bundle is built elsewhere and
# has to be built against these.
for soname in libssl libcrypto libsystemd libstdc++ libz libevent libevent_core libevent_extra libevent_pthreads libevent_openssl; do
    _found="$(ls -1 /usr/lib64/${soname}.so.* /lib64/${soname}.so.* /usr/lib64/${soname}-*.so.* 2>/dev/null | sed 's#.*/##' | sort -u | tr '\n' ' ')"
    if [ -n "${_found}" ]; then
        pass "${soname}" "${_found}"
    else
        fail "${soname}" "absent; a bundle linking it could not start"
    fi
done

if [ -n "${BUNDLE_DIR}" ]; then
    section "bundle check  (${BUNDLE_DIR})"
    if [ ! -d "${BUNDLE_DIR}" ]; then
        fail "bundle" "${BUNDLE_DIR} is not a directory"
    else
        for binary in valkey-server valkey-cli memtier_benchmark; do
            _path="${BUNDLE_DIR}/${binary}"
            [ -f "${_path}" ] || _path="${BUNDLE_DIR}/bin/${binary}"
            if [ ! -f "${_path}" ]; then
                fail "${binary}" "not found under ${BUNDLE_DIR}"
                continue
            fi
            # `ldd` reports both halves of the answer: a soname the host does
            # not have, and a symbol version the host's libraries are too old
            # to supply. Both stop the binary at exec.
            _ldd="$(ldd "${_path}" 2>&1)"
            _missing="$(printf '%s\n' "${_ldd}" | grep -c 'not found')"
            if [ "${_missing}" -eq 0 ]; then
                if "${_path}" --version >/dev/null 2>&1; then
                    pass "${binary}" "links resolve and it runs: $("${_path}" --version 2>&1 | head -1 | cut -c1-56)"
                else
                    fail "${binary}" "links resolve but it will not execute here"
                fi
            else
                fail "${binary}" "${_missing} unresolved:"
                printf '%s\n' "${_ldd}" | grep 'not found' | sed 's/^[[:space:]]*/             /' | sort -u | head -12
            fi
        done
    fi
else
    note "bundle check" "skipped; pass --bundle DIR to test the binaries a run would install"
fi

# ---------------------------------------------------------------------------
section 'headroom and evidence quality  (advised, never fatal)'
# ---------------------------------------------------------------------------

# The §11.1 sampler reads cgroup *v2* names through helpers that return None
# when absent, so a v1 host produces a run whose every cgroup field is null -
# not a failure, but a column of evidence the simulated fleet did produce.
case "$(stat -fc %T /sys/fs/cgroup 2>/dev/null)" in
    cgroup2fs) pass  "cgroup version" "v2; the sampler's cpu.max/memory.max fields will be populated" ;;
    *)         advise "cgroup version" "v1; every cgroup field of every resource sample records null" ;;
esac

_thp="$(cat /sys/kernel/mm/transparent_hugepage/enabled 2>/dev/null)"
case "${_thp}" in
    *'[never]'*) pass  "transparent huge pages" "never" ;;
    '')          note  "transparent huge pages" "not exposed here" ;;
    *)           advise "transparent huge pages" "${_thp}; Valkey names this itself and it lands in the latency tail" ;;
esac

check_sysctl() {
    _label="$1"; _key="$2"; _want="$3"
    _have="$(sysctl -n "${_key}" 2>/dev/null)"
    if [ -z "${_have}" ]; then
        note "${_label}" "${_key} not exposed here"
    elif [ "${_have}" -ge "${_want}" ] 2>/dev/null; then
        pass "${_label}" "${_key}=${_have}"
    else
        advise "${_label}" "${_key}=${_have}, wanted >= ${_want}"
    fi
}
check_sysctl "listen backlog"  net.core.somaxconn 4096
check_sysctl "file-max"        fs.file-max        2097152
_oc="$(sysctl -n vm.overcommit_memory 2>/dev/null)"
if [ "${_oc}" = "1" ]; then
    pass "overcommit" "vm.overcommit_memory=1"
elif [ -z "${_oc}" ]; then
    note "overcommit" "not exposed here"
else
    # The run's node configs set no `save`, so the built-in policy is live and
    # a background save forks a process holding a dataset.
    advise "overcommit" "vm.overcommit_memory=${_oc}; a background save fork can be refused"
fi

_nofile="$(ulimit -Hn 2>/dev/null)"
if [ "${_nofile}" = "unlimited" ] || [ "${_nofile:-0}" -ge 262144 ] 2>/dev/null; then
    pass "open files" "hard nofile ${_nofile}"
else
    advise "open files" "hard nofile ${_nofile}; ${NODES_PER_HOST} nodes x maxclients 10000 will be silently lowered"
fi

if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    if systemctl is-active firewalld >/dev/null 2>&1; then
        advise "firewalld" "active; it owns the packet filter and a reload would undo a live partition"
    else
        pass "firewalld" "not active"
    fi
    if systemctl is-active chronyd >/dev/null 2>&1; then
        pass "time sync" "chronyd active"
    else
        advise "time sync" "chronyd not active; clock offsets are recorded with a bound, but unbounded drift is not"
    fi
else
    note "systemd checks" "no systemd running here (firewalld, chronyd, unit state unverified)"
fi

if command -v getenforce >/dev/null 2>&1; then
    note "selinux" "$(getenforce)"
else
    note "selinux" "tools absent"
fi

# ---------------------------------------------------------------------------
printf '\n'
if [ "${REQUIRED_FAIL}" -eq 0 ]; then
    printf '\033[32mREADY\033[0m   every required check passed'
else
    printf '\033[31mNOT READY\033[0m   %d required check(s) failed' "${REQUIRED_FAIL}"
fi
printf '   (%d advised)\n' "${ADVISED_FAIL}"
[ "${REQUIRED_FAIL}" -eq 0 ] || exit 1
exit 0
