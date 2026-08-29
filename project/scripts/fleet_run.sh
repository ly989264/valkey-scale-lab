#!/bin/sh
# Take one exact-1280 run on the operator's fleet, unattended, in the order that
# has already failed once for every line here.
#
# Lab tooling. It runs nothing the operator could not run by hand and implements
# no policy: it calls `ecs_host_verify.sh`, `native_bringup_smoke.py`,
# `native_cleanup_proof.py` and the Gate, in the order
# `docs/m4_paid_run_checklist.md` §4 derived, and stops at the first one that
# refuses. What it adds is that the order is executed rather than remembered, and
# that the launch is detached the one way that survives the session that started
# it.
#
# **Run it on a controller inside the fleet's own network.** Transport measured
# 5.1 ms median in-VPC against 110-116 ms from a workstation, which across an
# exact-200's 3037 command rows is 15.5 s against about 5.6 minutes; at 1280
# nodes it is the difference between a run and a timeout. This script cannot
# check that and does not pretend to.
#
# Usage:
#   sh scripts/fleet_run.sh preflight --config PATH
#   sh scripts/fleet_run.sh start     --config PATH     # preflight, then launch
#   sh scripts/fleet_run.sh watch
#   sh scripts/fleet_run.sh abort
#
# `start` is the whole procedure. `preflight` is it without the launch, for a
# fleet you have just built and want to check before paying for anything.
#
# Exit codes: 0 success, 1 a step refused, 64 a usage error.

set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="${ROOT}/artifacts/fleet-runs"
MARKER="${STATE_DIR}/launched_at"
LAUNCH_LOG="${STATE_DIR}/launch.log"
TEST_ID="real.ecs.full-flow-1280"
# Word-split on purpose, so each option reaches ssh separately.
SSH_OPTS="-o ConnectTimeout=15 -o BatchMode=yes"
NODES=1280

die()  { echo "fleet_run: $*" >&2; exit 1; }
usage() { sed -n '2,30p' "$0"; exit 64; }
step() { printf '\n=== %s\n' "$*"; }

# Everything the run needs is already stated in the configuration, so it is read
# from there rather than passed again: a second copy of the density or the fleet
# id is a second thing that can disagree with the run.
config_field() {
    PYTHONPATH="${ROOT}/src" python3 - "$1" "$2" <<'PY'
import sys
from valkey_scale_lab.config.validation import load_effective_config
config = load_effective_config(sys.argv[1])
runtime = config["runtime"]
field = sys.argv[2]
if field == "inventory":
    print(runtime["host_inventory_path"])
elif field == "bundle":
    print(runtime["native_bundle_dir"])
elif field == "density":
    print(runtime["max_logical_nodes_per_nodehost"])
elif field == "nodes":
    cluster = config["cluster"]
    print(int(cluster["shards"]) * (1 + int(cluster["replicas_per_shard"])))
else:
    raise SystemExit(f"unknown field {field}")
PY
}

# The manifest is the one thing that crosses from the fleet to the product, so it
# is also what says which hosts to check and how to reach them.
inventory_field() {
    python3 - "$1" "$2" <<'PY'
import json, sys
manifest = json.load(open(sys.argv[1]))
what = sys.argv[2]
if what == "fleet_id":
    print(manifest["fleet_id"])
    raise SystemExit(0)
for host in manifest["hosts"]:
    control = host["control_endpoint"]
    print("\t".join([
        host["host_id"],
        control["address"],
        str(control.get("port", 22)),
        control["user"],
        control["private_key_path"],
        control["known_hosts_path"],
    ]))
PY
}

run_preflight() {
    config="$1"
    [ -f "${config}" ] || die "no such configuration: ${config}"
    inventory="${ROOT}/$(config_field "${config}" inventory)"
    bundle="${ROOT}/$(config_field "${config}" bundle)"
    density="$(config_field "${config}" density)"
    fleet_nodes="$(config_field "${config}" nodes)"
    [ -f "${inventory}" ] || die "no fleet manifest at ${inventory} - write one with scripts/make_fleet_manifest.py"
    [ -d "${bundle}" ] || die "no native bundle at ${bundle} - build one with scripts/build_native_bundle.py on a host of this fleet's architecture"
    fleet_id="$(inventory_field "${inventory}" fleet_id)"
    echo "fleet ${fleet_id}, ${fleet_nodes} nodes, ${density} per host, manifest ${inventory}"

    # 1. Every host, checked the way the backend will ask, over the control
    #    channel the run will use - so the session's own descriptor limits and
    #    the transport are under test too, which running it locally would not do.
    #    `--fleet-nodes` is what turns the cluster-bus memory reading into a
    #    refusal; without it a host that was never prepared passes and the run
    #    dies four minutes in.
    step "host readiness, ${density} nodes each in a ${fleet_nodes}-node fleet"
    inventory_field "${inventory}" hosts | while IFS="$(printf '\t')" read -r host_id address port user key known; do
        printf -- '--- %s (%s)\n' "${host_id}" "${address}"
        # `ConnectTimeout` and `BatchMode` together, because unattended is the
        # whole point: without the first an unreachable host hangs this forever,
        # and without the second a host whose key is not accepted stops to ask
        # for a password nobody is there to type.
        if ! scp -q ${SSH_OPTS} -i "${key}" -o "UserKnownHostsFile=${known}" -P "${port}" \
                "${ROOT}/scripts/ecs_host_verify.sh" "${user}@${address}:/tmp/ecs_host_verify.sh"; then
            echo "  unreachable, or the check would not copy" >&2
            echo "${host_id}" >> "${STATE_DIR}/.preflight_failures"
            continue
        fi
        if ! ssh ${SSH_OPTS} -i "${key}" -o "UserKnownHostsFile=${known}" -p "${port}" "${user}@${address}" \
                sh /tmp/ecs_host_verify.sh --nodes-per-host "${density}" --fleet-nodes "${fleet_nodes}"; then
            echo "${host_id}" >> "${STATE_DIR}/.preflight_failures"
        fi
    done
    if [ -s "${STATE_DIR}/.preflight_failures" ]; then
        echo >&2
        echo "hosts that failed a REQUIRED check:" >&2
        sort -u "${STATE_DIR}/.preflight_failures" >&2
        rm -f "${STATE_DIR}/.preflight_failures"
        die "fix those hosts before spending a run"
    fi
    rm -f "${STATE_DIR}/.preflight_failures"

    # 2. The seam, driven end to end against this fleet before any cluster
    #    exists. A first failure with this unrun leaves a dozen unexercised
    #    command shapes in its search space.
    step "bring-up smoke against ${fleet_id}"
    PYTHONPATH="${ROOT}/src" python3 "${ROOT}/scripts/native_bringup_smoke.py" --fleet-id "${fleet_id}" \
        || die "the bring-up smoke did not answer clean"

    # 3. Reclaim, proven at the density of the run it stands behind. "Cleanup
    #    works" at the default two processes a host is not evidence about a run
    #    that places forty, and a two-hour run that strands 1280 processes on a
    #    fleet is the failure this ordering exists to prevent.
    step "cleanup proof at ${density} nodes a host"
    PYTHONPATH="${ROOT}/src" python3 "${ROOT}/scripts/native_cleanup_proof.py" release \
        --fleet-id "${fleet_id}" --nodes-per-host "${density}" \
        || die "reclaim did not clear the fleet at this density"

    step "preflight clean"
}

run_start() {
    config="$1"
    run_preflight "${config}"

    # The Gate rather than `ecs_gate.py` directly, so that an unattended run and
    # `./gate milestone m4` go through one door and leave the same evidence. The
    # entry carries `--operator-opt-in` and `--cost-acknowledged` in its own argv;
    # naming it here is the operator action those flags stand for.
    step "launching ${TEST_ID}"
    date -u +%Y-%m-%dT%H:%M:%SZ > "${MARKER}"
    # `setsid nohup ... < /dev/null &`, all four parts. A run launched without
    # them dies with the ssh session that started it, mid-flight, and leaves its
    # processes running on every host - measured, and the reason this wrapper
    # exists at all.
    setsid nohup "${ROOT}/gate" test "${TEST_ID}" \
        --param "nodes=${NODES}" --param "config=${config}" \
        >> "${LAUNCH_LOG}" 2>&1 < /dev/null &
    echo "$!" > "${STATE_DIR}/launcher.pid"
    echo "launched, launcher pid $(cat "${STATE_DIR}/launcher.pid")"
    echo "log: ${LAUNCH_LOG}"
    echo
    echo "Watch it with: sh scripts/fleet_run.sh watch"
    echo "Stop it with:  sh scripts/fleet_run.sh abort"
}

# What is actually running. `scripts/ecs_gate.py` execv's into the CLI, so
# nothing matches the wrapper's name once a run starts and a watcher grepping for
# it reports "finished" immediately.
gate_pids() {
    pgrep -f 'valkey_scale_lab.cli gate execute' 2>/dev/null || true
}

run_watch() {
    [ -f "${MARKER}" ] || die "no run has been launched from here"
    echo "launched at $(cat "${MARKER}")"
    pids="$(gate_pids)"
    if [ -n "${pids}" ]; then
        echo "running: valkey_scale_lab.cli gate execute [$(echo "${pids}" | tr '\n' ' ')]"
    else
        echo "no 'valkey_scale_lab.cli gate execute' process; the run has ended"
    fi
    echo
    echo "--- last 40 lines of ${LAUNCH_LOG}"
    tail -40 "${LAUNCH_LOG}" 2>/dev/null || echo "(no log yet)"
    echo
    # Said rather than promised: a run that failed early collects no node
    # journals and writes no lifecycle timeline, so the report a failing run
    # leaves is thinner than a passing one's and this is not a defect in the
    # wrapper.
    echo "The run renders its own report into <artifacts-dir>/runtime/report/ when it finishes,"
    echo "pass or fail. Look under ${ROOT}/artifacts/gate-runs/ for the newest invocation."
}

run_abort() {
    [ -f "${MARKER}" ] || die "no run has been launched from here"
    pids="$(gate_pids)"
    if [ -n "${pids}" ]; then
        # Named exactly, never `pkill -f` on a pattern: a pattern broad enough to
        # match the run also matches the shell that is running this, and killing
        # your own launcher mid-reclaim is how a fleet was left populated once.
        echo "killing: ${pids}"
        for pid in ${pids}; do kill -9 "${pid}" 2>/dev/null || true; done
    else
        echo "nothing to kill"
    fi
    # Immediately, and this ordering is the whole point. The cluster bus is
    # peer-to-peer, so killing the controller relieves nothing: the nodes carry
    # on gossiping and the heaviest link-freeing was sampled *after* the
    # controller died. Kill and reclaim is one move.
    found=0
    for state in "${ROOT}"/artifacts/gate-runs/*/*/runtime/state.json; do
        [ -f "${state}" ] || continue
        [ "${state}" -nt "${MARKER}" ] || continue
        found=1
        echo "reclaiming from ${state}"
        PYTHONPATH="${ROOT}/src" python3 -m valkey_scale_lab.cli gate cleanup --state "${state}" \
            || echo "WARNING: cleanup from ${state} did not finish; run it again by hand" >&2
    done
    [ "${found}" -eq 1 ] || echo "no run state written since launch - the run had not started placing nodes"
}

[ $# -ge 1 ] || usage
command="$1"; shift
config=""
while [ $# -gt 0 ]; do
    case "$1" in
        --config) config="${2:-}"; shift 2 ;;
        --config=*) config="${1#--config=}"; shift ;;
        -h|--help) usage ;;
        *) echo "unknown argument: $1" >&2; usage ;;
    esac
done
mkdir -p "${STATE_DIR}"
rm -f "${STATE_DIR}/.preflight_failures"

case "${command}" in
    preflight) [ -n "${config}" ] || die "preflight needs --config"; run_preflight "${config}" ;;
    start)     [ -n "${config}" ] || die "start needs --config";     run_start "${config}" ;;
    watch)     run_watch ;;
    abort)     run_abort ;;
    *) echo "unknown command: ${command}" >&2; usage ;;
esac
