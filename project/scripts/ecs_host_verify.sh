#!/bin/sh
# Is this host ready for the existing `native_multi_ecs` backend?
#
# Lab tooling, the other half of `ecs_host_prepare.sh`. It answers about a host
# what `verify_image` answers about an image, and it answers it the way the
# backend will ask: by running the command shapes `runtime/native_backend.py`
# runs and by driving the product's own modules where it can, rather than asking
# dpkg what is installed. A package can be present and the thing that matters
# still absent.
#
# It changes nothing it does not undo. The two checks that must mutate the host
# - the firewall and a probe process - install something named for this script
# and remove it again.
#
# Run it on the host. Running it *over ssh from the controller* is worth more
# than running it locally, because then the control channel and the session's
# own descriptor limits are under test too:
#
#   scp -i KEY ecs_host_verify.sh vslab@HOST:/tmp/
#   ssh -i KEY vslab@HOST sh /tmp/ecs_host_verify.sh
#
# Usage:
#   sh ecs_host_verify.sh                    # host readiness
#   sh ecs_host_verify.sh --bundle DIR       # ... and can this host run that bundle
#   sh ecs_host_verify.sh --package DIR      # ... and does the resource agent import here
#   sh ecs_host_verify.sh --nodes-per-host N # ... at that density rather than 25
#   sh ecs_host_verify.sh --fleet-nodes N    # ... and can its kernel hold this fleet's
#                                            #     cluster bus (see the tcp_mem check)
#
# Exit code 0 when every REQUIRED check passed, 1 otherwise. ADVISED failures
# never change the exit code: they degrade a run's evidence or its headroom, and
# saying so is different from refusing.

set -u

BUNDLE_DIR=""
PACKAGE_DIR=""
# The density this host is being asked about. It was a constant, which made every
# answer below about a 25-node host whatever the run intended to place.
NODES_PER_HOST=25
# How many nodes the whole cluster will have. Absent by default because this
# script runs on one host and cannot know it; supplied, it is what turns the
# cluster-bus check from a reading into a refusal.
FLEET_NODES=""
while [ $# -gt 0 ]; do
    case "$1" in
        --bundle) BUNDLE_DIR="${2:-}"; shift 2 ;;
        --bundle=*) BUNDLE_DIR="${1#--bundle=}"; shift ;;
        --package) PACKAGE_DIR="${2:-}"; shift 2 ;;
        --package=*) PACKAGE_DIR="${1#--package=}"; shift ;;
        --nodes-per-host) NODES_PER_HOST="${2:-}"; shift 2 ;;
        --nodes-per-host=*) NODES_PER_HOST="${1#--nodes-per-host=}"; shift ;;
        --fleet-nodes) FLEET_NODES="${2:-}"; shift 2 ;;
        --fleet-nodes=*) FLEET_NODES="${1#--fleet-nodes=}"; shift ;;
        -h|--help) sed -n '2,32p' "$0"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 64 ;;
    esac
done
case "${NODES_PER_HOST}" in
    ''|*[!0-9]*|0) echo "--nodes-per-host must be a positive integer" >&2; exit 64 ;;
esac
case "${FLEET_NODES}" in
    '') : ;;
    *[!0-9]*|0) echo "--fleet-nodes must be a positive integer" >&2; exit 64 ;;
esac

# Constants read off the implementation rather than chosen here.
NATIVE_INSTALL_ROOT="/opt/valkey-scale-lab/bundles"   # native_backend.py
RUN_STATE_ROOT="/tmp/valkey-scale-lab"                # native_backend.py
BUNDLE_DROP_ROOT="/tmp"                               # native_backend.py
FDS_PER_NODE=413                                      # measured, native exact-200

REQUIRED_FAIL=0
ADVISED_FAIL=0

pass()    { printf '  \033[32mok\033[0m       %-32s %s\n' "$1" "${2:-}"; }
fail()    { printf '  \033[31mFAIL\033[0m     %-32s %s\n' "$1" "${2:-}"; REQUIRED_FAIL=$((REQUIRED_FAIL + 1)); }
advise()  { printf '  \033[33mADVISED\033[0m  %-32s %s\n' "$1" "${2:-}"; ADVISED_FAIL=$((ADVISED_FAIL + 1)); }
note()    { printf '           %-32s %s\n' "$1" "${2:-}"; }
section() { printf '\n%s\n' "$1"; }

. /etc/os-release 2>/dev/null || true
printf 'valkey-scale-lab :: native fleet host readiness\n'
printf '%s | %s | kernel %s | %s\n' "${PRETTY_NAME:-unknown}" "$(uname -m)" "$(uname -r)" "$(id -un)@$(hostname)"

IN_CONTAINER=0
if [ -f /.dockerenv ] || [ ! -d /run/systemd/system ]; then
    IN_CONTAINER=1
    printf '\n\033[33mnote\033[0m  no systemd here, so this looks like a container. The kernel is the\n'
    printf '      container host'"'"'s: cgroup version, huge pages, every sysctl and every\n'
    printf '      unit state below describe that kernel, not this image.\n'
fi

SUDO=""
if [ "$(id -u)" = "0" ]; then
    SUDO=""
elif sudo -n true 2>/dev/null; then
    SUDO="sudo -n"
fi

# ---------------------------------------------------------------------------
section 'control channel  (host_transport.py: MultiplexedSshTransport)'
# ---------------------------------------------------------------------------

# `sudo` appears nowhere in `runtime/` - measured by grep over the whole
# package. The backend runs every command as the manifest user directly, and
# those commands write under /opt, install iptables chains, read
# `/proc/<pid>/cwd` for processes it does not own, and signal them. So the
# manifest user has to be root. A sudo account would need the product to prepend
# `sudo`, which would change the argv of every command-log row the equivalence
# diff compares field by field.
if [ "$(id -u)" = "0" ]; then
    pass "runs as the fleet user" "root"
else
    fail "runs as the fleet user" "$(id -un) is not root; the backend never uses sudo, so every privileged step would fail"
    note "" "run this over ssh as the user the fleet manifest names"
fi

# The finding that cost this exercise two lockouts, made into a check.
# google-guest-agent manages the accounts *it* provisions from instance metadata
# and de-provisions them when their keys expire, taking their privileges with
# them. Its own journal: "Removing user ly989264." followed by
# "removed by root from group google-sudoers". A fleet whose manifest names such
# an account can lose every host's control channel mid-run, and BatchMode=yes
# turns that into eight simultaneous failures rather than a degradation.
if [ -d /run/systemd/system ] && systemctl list-unit-files google-guest-agent.service >/dev/null 2>&1; then
    if grep -qs "vslab_authorized_keys" /etc/ssh/sshd_config.d/*.conf 2>/dev/null; then
        pass "key is agent-independent" "sshd reads a root-owned AuthorizedKeysFile the agent does not rewrite"
    else
        fail "key is agent-independent" "only ~/.ssh/authorized_keys is configured, and the guest agent rewrites it"
    fi
    if [ "$(id -u)" = "0" ] && [ -s "/etc/ssh/vslab_authorized_keys/root" ]; then
        pass "fleet key is placed" "/etc/ssh/vslab_authorized_keys/root"
    elif [ "$(id -u)" = "0" ]; then
        advise "fleet key is placed" "no key at /etc/ssh/vslab_authorized_keys/root; this is image state, not fleet state"
    fi
else
    note "guest agent" "not present; account and key management are the operator's"
fi

if [ -x /usr/sbin/sshd ]; then
    pass "sshd" "$(/usr/sbin/sshd -V 2>&1 | head -1)"
else
    fail "sshd" "/usr/sbin/sshd is missing"
fi

SSHD_EFFECTIVE="$(${SUDO} sshd -T -C user=root,host=localhost,addr=127.0.0.1 2>/dev/null)"
sshd_says() { printf '%s\n' "${SSHD_EFFECTIVE}" | awk -v k="$1" 'tolower($1)==k {print $2; exit}'; }

if [ -n "${SSHD_EFFECTIVE}" ]; then
    pass "sshd config" "parses"
    [ "$(sshd_says passwordauthentication)" = "no" ] \
        && pass "password auth" "disabled" \
        || fail "password auth" "enabled; the transport runs BatchMode=yes and expects key-only"
    if printf '%s\n' "${SSHD_EFFECTIVE}" | grep -qi '^subsystem.*sftp'; then
        pass "sftp subsystem" "$(printf '%s\n' "${SSHD_EFFECTIVE}" | grep -i '^subsystem' | head -1 | cut -d' ' -f2-)"
    else
        fail "sftp subsystem" "absent; scp from an OpenSSH >= 9 controller cannot transfer"
    fi
    _maxsessions="$(sshd_says maxsessions)"
    if [ "${_maxsessions:-10}" -ge 32 ] 2>/dev/null; then
        pass "MaxSessions" "${_maxsessions}"
    else
        advise "MaxSessions" "${_maxsessions:-10}; sessions queue above it (latency, not failure)"
    fi
else
    note "sshd config" "needs privilege to read the effective configuration; skipped"
fi

# The item 1.0 defect: a fleet whose hosts all present one fingerprint hides a
# whole class of transport mistake, and an image is where that gets manufactured.
_hostkeys="$(ls /etc/ssh/ssh_host_*_key 2>/dev/null | wc -l | tr -d ' ')"
if [ "${_hostkeys}" -gt 0 ]; then
    pass "ssh host keys" "${_hostkeys} present - a live host, not a baked image"
elif [ -f /etc/cloud/cloud.cfg ]; then
    pass "ssh host keys" "absent; cloud-init regenerates them per instance at boot (image state)"
else
    fail "ssh host keys" "absent and nothing will generate them at boot"
fi

# ---------------------------------------------------------------------------
section 'backend commands  (native_backend.py remote scripts)'
# ---------------------------------------------------------------------------

missing=""
for entry in \
    "sh:every command is sh -c" "printf:_owned_process_walk" "ls:start_nodehost probe" \
    "head:start_nodehost probe" "mkdir:run state root" "rm:release_run" \
    "touch:install marker" "cat:pidfile reads" "readlink:/proc/<pid>/cwd mark" \
    "sleep:_await_owned_processes_gone" "wc:_await_owned_processes_gone" \
    "seq:NativeResourceAgent.stop" "cut:bundle digest check" "sha256sum:bundle digest check" \
    "tar:bundle extraction" "gzip:bundle extraction" "awk:_remove_fault_rules" \
    "nohup:resource agent launch" "ip:create_network route check" \
    "iptables:isolate/rejoin/scan fault rules" "python3:resource agent and HOST_CLOCK_ARGV" \
; do
    cmd="${entry%%:*}"
    command -v "$cmd" >/dev/null 2>&1 || missing="${missing} ${cmd}(${entry#*:})"
done
[ -z "${missing}" ] && pass "remote command set" "21 of 21 present" \
                    || fail "remote command set" "missing:${missing}"

ip route get 127.0.0.1 >/dev/null 2>&1 \
    && pass "ip route get" "answers (create_network's whole implementation)" \
    || fail "ip route get" "create_network would reject this fleet"

# ---------------------------------------------------------------------------
section 'python  (resource_agent, host_clock.HOST_CLOCK_ARGV)'
# ---------------------------------------------------------------------------

if command -v python3 >/dev/null 2>&1; then
    PYV="$(python3 -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])' 2>/dev/null)"
    # The floor is not a preference: every product module opens with
    # `from __future__ import annotations`, which is 3.7.
    if python3 -c 'import sys;sys.exit(0 if sys.version_info[:2]>=(3,7) else 1)' 2>/dev/null; then
        pass "python3 version" "${PYV}"
    else
        fail "python3 version" "${PYV}; the resource agent needs >= 3.7"
    fi
    _clock="$(python3 -c 'import time;print(repr(time.time()),repr(time.monotonic()))' 2>/dev/null)"
    if printf '%s' "${_clock}" | awk 'NF==2 && $1+0>0 && $2+0>=0 {ok=1} END{exit ok?0:1}'; then
        pass "HOST_CLOCK_ARGV" "$(printf '%s' "${_clock}" | cut -c1-38)"
    else
        fail "HOST_CLOCK_ARGV" "did not return two numbers: ${_clock}"
    fi
else
    fail "python3" "absent; the resource agent and the clock reading both need it"
fi

if [ -n "${PACKAGE_DIR}" ] && [ -d "${PACKAGE_DIR}" ]; then
    if PYTHONPATH="${PACKAGE_DIR}" python3 -c 'import valkey_scale_lab.observability.resource_agent' 2>/dev/null; then
        pass "resource agent imports" "on python ${PYV}"
    else
        fail "resource agent imports" "$(PYTHONPATH=${PACKAGE_DIR} python3 -c 'import valkey_scale_lab.observability.resource_agent' 2>&1 | tail -1 | cut -c1-90)"
    fi
    # The §11.1 sampler, run for real. How many cgroup fields it can populate is
    # an evidence-shape fact, not a health check: a container is a delegated
    # child cgroup and fills all six, while a VM's sampler reads the *root*
    # cgroup, which exposes the cpu files and not the memory ones. Measured on
    # a real GCE instance: 2 of 6. The simulated baselines carry six.
    _cg="$(PYTHONPATH="${PACKAGE_DIR}" python3 -c '
from valkey_scale_lab.observability.resources import LocalResourceSampler
s = LocalResourceSampler(sampler_id="verify", processes=[])
cg = s.host_sample().get("cgroup", {})
pop = sorted(k for k, v in cg.items() if v is not None)
print("%d/%d %s" % (len(pop), len(cg), ",".join(pop)))
' 2>/dev/null)"
    if [ -n "${_cg}" ]; then
        pass "sampler reads this host" "cgroup fields populated ${_cg}"
        case "${_cg}" in
            6/6*) ;;
            *) note "" "the simulated baselines carry 6/6; declare this delta before freezing real ones" ;;
        esac
    else
        fail "sampler reads this host" "LocalResourceSampler.host_sample() failed"
    fi
else
    note "resource agent" "pass --package DIR (the src/ tree) to test the import and the sampler"
fi

# ---------------------------------------------------------------------------
section 'process ownership  (_owned_process_walk, release_run, reclaim_run)'
# ---------------------------------------------------------------------------

# The ownership mark is the process working directory, because Valkey rewrites
# its process title and the run root is nowhere in a live node's argv.
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
            printf "%s\n" "$pid"
        done
    )"
    if printf '%s\n' "${_found}" | grep -qx "${_probe_pid}"; then
        pass "/proc cwd walk" "found the planted process by its working directory"
    else
        fail "/proc cwd walk" "planted pid ${_probe_pid} not found; teardown would leave it running"
    fi
    kill -KILL "${_probe_pid}" 2>/dev/null; wait "${_probe_pid}" 2>/dev/null
    rm -rf "${_probe_root}"
else
    fail "/proc cwd walk" "could not create ${_probe_root}"
fi

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
if ! ${SUDO} iptables -S >/dev/null 2>&1; then
    # The residue scan reports "unscannable" here rather than "nothing found",
    # deliberately - so this is a real gap, not a quiet pass.
    fail "iptables -S" "not permitted or absent; the residue scan reports unscannable"
else
    pass "iptables -S" "$(${SUDO} iptables --version 2>/dev/null | head -1)"
    # `-m comment` is not decoration: a chain name is capped at 28 characters
    # and a run id is 42, so the ownership mark lives in the comment and both
    # cleanup paths find rules by it.
    if ${SUDO} iptables -N "${_chain}" 2>/dev/null \
        && ${SUDO} iptables -A "${_chain}" -p tcp --dport 22 -j RETURN 2>/dev/null \
        && ${SUDO} iptables -A "${_chain}" -j DROP 2>/dev/null \
        && ${SUDO} iptables -I INPUT 1 -m comment --comment "${_tag}" -j "${_chain}" 2>/dev/null \
        && ${SUDO} iptables -C INPUT -m comment --comment "${_tag}" -j "${_chain}" 2>/dev/null
    then
        pass "isolate_nodehost shape" "chain + comment-marked jump installed and confirmed"
        if ${SUDO} iptables -S 2>/dev/null | awk -v t="${_tag}" 'index($0,t)>0 && $1=="-A"{n++} END{exit n?0:1}'; then
            pass "run mark is findable" "iptables -S prints the comment"
        else
            fail "run mark is findable" "iptables -S does not print comments; cleanup could not find its rules"
        fi
    else
        fail "isolate_nodehost shape" "could not install the chain and comment-marked jump"
    fi
    ${SUDO} iptables -D INPUT -m comment --comment "${_tag}" -j "${_chain}" 2>/dev/null
    ${SUDO} iptables -F "${_chain}" 2>/dev/null
    ${SUDO} iptables -X "${_chain}" 2>/dev/null
    if ${SUDO} iptables -S 2>/dev/null | grep -q "${_tag}"; then
        fail "verify cleaned up" "left rules tagged ${_tag} behind"
    else
        pass "rejoin_nodehost shape" "chain and jump removed, nothing left tagged"
    fi
fi

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
section 'recursive transfer  (send_bundle, NativeResourceAgent.start)'
# ---------------------------------------------------------------------------
#
# A recursive upload is how `send_bundle` and the resource agent's package copy
# both move, and it is the transport shape most likely to be refused by an old
# host. It cannot be tested with the host's *own* scp: the controller runs
# OpenSSH >= 9, whose scp drives transfers over the sftp protocol, so a local
# scp test would measure the wrong client. This asks the sftp-server itself,
# over one SFTP INIT exchange, whether it advertises the extension scp's sftp
# mode uses to canonicalize a path that does not exist yet.
#
# Measured: CentOS 8.2 / OpenSSH 8.0p1 advertises 6 extensions and not this one,
# and `scp -r` there fails with `path canonicalization failed`; Debian 13 /
# OpenSSH 10.0p2 advertises 11 including it, and accepts.
_sftp_server="$(printf '%s\n' "${SSHD_EFFECTIVE}" | awk 'tolower($1)=="subsystem" && $2=="sftp" {print $3; exit}')"
[ -n "${_sftp_server:-}" ] || _sftp_server=/usr/lib/openssh/sftp-server
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
    note "sftp-server" "not found at ${_sftp_server}; skipped"
fi

# ---------------------------------------------------------------------------
section 'filesystem  (NATIVE_INSTALL_ROOT, RUN_STATE_ROOT, BUNDLE_DROP_ROOT)'
# ---------------------------------------------------------------------------

check_dir_exec() {
    _label="$1"; _dir="$2"
    ${SUDO} mkdir -p "${_dir}" 2>/dev/null || mkdir -p "${_dir}" 2>/dev/null
    if [ ! -d "${_dir}" ]; then
        fail "${_label}" "${_dir} does not exist and $(id -un) cannot create it"
        return
    fi
    _probe="${_dir}/.vslab-exec-probe-$$"
    if ! (printf '#!/bin/sh\nexit 0\n' > "${_probe}") 2>/dev/null; then
        fail "${_label}" "${_dir} is not writable by $(id -un)"
        return
    fi
    chmod 0755 "${_probe}" 2>/dev/null
    if "${_probe}" 2>/dev/null; then
        pass "${_label}" "${_dir} writable and exec"
    else
        fail "${_label}" "${_dir} is writable but noexec"
    fi
    rm -f "${_probe}"
}
check_dir_exec "bundle install root" "${NATIVE_INSTALL_ROOT}"
check_dir_exec "run state root"      "${RUN_STATE_ROOT}"
check_dir_exec "bundle drop root"    "${BUNDLE_DROP_ROOT}"
rmdir "${RUN_STATE_ROOT}" 2>/dev/null || true

# `RUN_STATE_ROOT` and `BUNDLE_DROP_ROOT` are both under /tmp, so every node's
# data directory, RDB and journal land there. On tmpfs that is RAM, held in page
# cache and counted against the very MemAvailable the §11.1 sampler reports - so
# the run's memory evidence would conflate dataset storage with process
# footprint. The simulated baselines were taken with /tmp on disk.
_tmpfs="$(findmnt -no FSTYPE /tmp 2>/dev/null || df -PT /tmp 2>/dev/null | awk 'NR==2{print $2}')"
if [ "${_tmpfs}" = "tmpfs" ]; then
    advise "/tmp filesystem" "tmpfs; ${NODES_PER_HOST} datasets, RDBs and journals would live in RAM and skew the sampler"
else
    pass "/tmp filesystem" "${_tmpfs:-unknown}"
fi
_avail_mb="$(df -Pm /tmp 2>/dev/null | awk 'NR==2{print $4}')"
if [ -n "${_avail_mb}" ] && [ "${_avail_mb}" -ge 8192 ] 2>/dev/null; then
    pass "space under /tmp" "${_avail_mb} MB free"
else
    advise "space under /tmp" "${_avail_mb:-unknown} MB free for ${NODES_PER_HOST} datasets, RDBs and journals"
fi

# ---------------------------------------------------------------------------
section 'bundle ABI  (what the pinned build must link against here)'
# ---------------------------------------------------------------------------

note "glibc" "$(ldd --version 2>/dev/null | head -1 | awk '{print $NF}')"
for soname in libssl libcrypto libsystemd libstdc++ libz libevent libevent_core libevent_extra libevent_pthreads libevent_openssl; do
    _found="$(ls -1 /usr/lib/*/${soname}.so.* /lib/*/${soname}.so.* /usr/lib/*/${soname}-*.so.* 2>/dev/null | sed 's#.*/##' | sort -u | tr '\n' ' ')"
    [ -n "${_found}" ] && pass "${soname}" "${_found}" \
                       || fail "${soname}" "absent; a bundle linking it could not start"
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
            # `ldd` reports both halves: a soname the host lacks, and a symbol
            # version its libraries are too old to supply. Both stop the binary
            # at exec.
            _ldd="$(ldd "${_path}" 2>&1)"
            if [ "$(printf '%s\n' "${_ldd}" | grep -c 'not found')" -eq 0 ]; then
                if "${_path}" --version >/dev/null 2>&1; then
                    pass "${binary}" "$("${_path}" --version 2>&1 | head -1 | cut -c1-52)"
                else
                    fail "${binary}" "links resolve but it will not execute here"
                fi
            else
                fail "${binary}" "unresolved:"
                printf '%s\n' "${_ldd}" | grep 'not found' | sed 's/^[[:space:]]*/             /' | sort -u | head -12
            fi
        done
        # The one check verify_native_bundle declines to make, because under
        # Docker the preflight starts a server and asks it, while a bundle
        # verifier only hashes bytes on the controller. On a host it can be made.
        _vs="${BUNDLE_DIR}/bin/valkey-server"; [ -f "${_vs}" ] || _vs="${BUNDLE_DIR}/valkey-server"
        _vc="${BUNDLE_DIR}/bin/valkey-cli";    [ -f "${_vc}" ] || _vc="${BUNDLE_DIR}/valkey-cli"
        if [ -x "${_vs}" ] && [ -x "${_vc}" ] && "${_vs}" --version >/dev/null 2>&1; then
            _t="$(mktemp -d)"
            if "${_vs}" --port 7999 --bind 127.0.0.1 --protected-mode no --cluster-enabled yes \
                        --dir "${_t}" --daemonize yes >/dev/null 2>&1; then
                sleep 1
                if "${_vc}" -p 7999 CLUSTER MYSLOTS 2>/dev/null | grep -q node-id; then
                    pass "CLUSTER MYSLOTS" "the patched command answers on this host"
                else
                    fail "CLUSTER MYSLOTS" "the pinned patch is absent or the server did not answer"
                fi
                "${_vc}" -p 7999 SHUTDOWN NOSAVE >/dev/null 2>&1
            fi
            rm -rf "${_t}"
        fi
    fi
else
    note "bundle check" "pass --bundle DIR to test the binaries a run would install"
fi

# ---------------------------------------------------------------------------
section 'headroom and evidence quality  (advised, never fatal)'
# ---------------------------------------------------------------------------

case "$(stat -fc %T /sys/fs/cgroup 2>/dev/null)" in
    cgroup2fs) pass  "cgroup version" "v2" ;;
    *)         advise "cgroup version" "not v2; the sampler reads v2 filenames and would record nulls" ;;
esac

_thp="$(cat /sys/kernel/mm/transparent_hugepage/enabled 2>/dev/null)"
case "${_thp}" in
    *'[never]'*) pass   "transparent huge pages" "never" ;;
    '')          note   "transparent huge pages" "not exposed here" ;;
    *)           advise "transparent huge pages" "${_thp}; Valkey names this itself and it lands in the latency tail" ;;
esac

# Measured as the *session* sees it, which is what start_all.sh inherits.
_want_fd=$((NODES_PER_HOST * FDS_PER_NODE))
_soft="$(ulimit -Sn)"; _hard="$(ulimit -Hn)"
if [ "${_soft}" = "unlimited" ] || [ "${_soft:-0}" -ge 262144 ] 2>/dev/null; then
    pass "open files (this session)" "soft ${_soft} / hard ${_hard}"
else
    advise "open files (this session)" "soft ${_soft}: ${NODES_PER_HOST} nodes need ~${_want_fd} and each wants 10032; Valkey lowers maxclients silently"
fi

check_sysctl() {
    _have="$(sysctl -n "$2" 2>/dev/null)"
    if [ -z "${_have}" ]; then note "$1" "$2 not exposed here"
    elif [ "${_have}" -ge "$3" ] 2>/dev/null; then pass "$1" "$2=${_have}"
    else advise "$1" "$2=${_have}, wanted >= $3"; fi
}
check_sysctl "listen backlog" net.core.somaxconn 4096
check_sysctl "file-max"       fs.file-max        2097152

# The cluster bus is a full mesh, so what a host's kernel must hold is quadratic
# in the *fleet* and only linear in this host's density - which is why every
# density experiment missed it and why one host cannot answer it alone. Each of
# this host's nodes keeps a link to every other node in the cluster and a link is
# two sockets, so the host carries `2 * nodes_per_host * (fleet_nodes - 1)` of
# them, each charged at least the kernel's own 4 KiB + 4 KiB. Measured
# 2026-08-17 at 107 nodes on each of twelve hosts: 273,706 sockets and at least
# 2.09 GiB, against a stock ceiling on an 8 GB host of 93963/125285/187926 pages
# - 734 MiB. The first real 1280-node attempt died exactly there, with 370 kernel
# "TCP: out of memory" messages beginning four minutes in and cluster formation
# taking 152 `ConnectionRefusedError` in 0-1 ms on CLUSTER MEET.
#
# `ecs_host_prepare.sh` writes 393216/786432/1048576 - 1.5/3/4 GiB - and that is
# a ceiling rather than an allocation. But the fleet boots from whatever its
# provider's startup mechanism holds, not from the committed script, so the value
# has to be read back off the host rather than assumed to have been applied. That
# is this check.
_tcp_mem="$(sysctl -n net.ipv4.tcp_mem 2>/dev/null)"
if [ -z "${_tcp_mem}" ]; then
    note "cluster bus memory" "net.ipv4.tcp_mem not exposed here"
elif [ -z "${FLEET_NODES}" ]; then
    note "cluster bus memory" "net.ipv4.tcp_mem=${_tcp_mem}; pass --fleet-nodes to have it checked"
else
    # Defaulted, because a kernel that prints something other than three fields
    # would otherwise reach the arithmetic below with an empty value.
    _have_pages="$(printf '%s\n' "${_tcp_mem}" | awk '{print $3}')"
    case "${_have_pages}" in ''|*[!0-9]*) _have_pages=0 ;; esac
    # Integer arithmetic only: this runs under /bin/sh on a fleet host.
    _want_pages="$(awk -v n="${NODES_PER_HOST}" -v f="${FLEET_NODES}" \
        'BEGIN { if (f < 2) { print 0 } else { print int((2 * n * (f - 1) * 8192 + 4095) / 4096) } }')"
    _have_mib=$((_have_pages / 256))
    _want_mib=$((_want_pages / 256))
    if [ "${_have_pages:-0}" -ge "${_want_pages}" ] 2>/dev/null; then
        pass "cluster bus memory" "tcp_mem max ${_have_pages} pages (${_have_mib} MiB) >= ${_want_pages} (${_want_mib} MiB)"
    else
        fail "cluster bus memory" "tcp_mem max ${_have_pages} pages (${_have_mib} MiB); ${NODES_PER_HOST} nodes in a ${FLEET_NODES}-node fleet need >= ${_want_pages} (${_want_mib} MiB)"
    fi
fi
_oc="$(sysctl -n vm.overcommit_memory 2>/dev/null)"
case "${_oc}" in
    1) pass "overcommit" "vm.overcommit_memory=1" ;;
    "") note "overcommit" "not exposed here" ;;
    *) advise "overcommit" "vm.overcommit_memory=${_oc}; valkey-server warns about this itself on startup" ;;
esac

if [ -d /run/systemd/system ]; then
    for unit in ufw unattended-upgrades; do
        if ! systemctl list-unit-files "${unit}.service" >/dev/null 2>&1; then
            note "${unit}" "not installed"
        elif systemctl is-active --quiet "${unit}" 2>/dev/null; then
            advise "${unit}" "active; it can change the packet filter or the packages under a running gate"
        else
            pass "${unit}" "not active"
        fi
    done
    if systemctl is-active --quiet chrony 2>/dev/null || systemctl is-active --quiet chronyd 2>/dev/null \
       || systemctl is-active --quiet systemd-timesyncd 2>/dev/null; then
        pass "time sync" "active"
    else
        advise "time sync" "no time source active; offsets are recorded with a bound, unbounded drift is not"
    fi
else
    note "systemd checks" "no systemd running here"
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
