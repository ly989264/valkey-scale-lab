#!/usr/bin/env python3
"""The jail canary: a `shell` worker that reports what it can reach, and stops.

Consumer data, not kernel code. It is a worker in the adapter's sense - the
bundle arrives on stdin, one JSON object matching the worker schema goes out -
but it fixes nothing. It answers `blocked` with what it found, which is a
terminal state the round records, so a jailed round can be proved to have held
without a model, an API key or a change to any tree.
"""

import json
import os
import sys

VIRTUAL = {
    "proc", "sysfs", "devpts", "tmpfs", "mqueue", "cgroup", "cgroup2", "devtmpfs",
    "securityfs", "shm", "overlay", "fuse.snapfuse", "binfmt_misc", "nsfs",
}


def mounts():
    """Every non-virtual mount and whether it is writable: what came in from the host."""
    found = []
    try:
        with open("/proc/mounts") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) < 4 or parts[2] in VIRTUAL:
                    continue
                found.append("%s(%s)" % (parts[1], parts[3].split(",")[0]))
    except OSError as exc:
        return ["unreadable: %s" % exc]
    return found


def main():
    sys.stdin.read()
    reachable = {}
    for path in (
        "/var/run/docker.sock",
        "/run/docker.sock",
        os.path.expanduser("~/.ssh"),
        os.path.expanduser("~/.claude"),
        "/Users",
        "/Users/allgood/.ssh",
        "/Users/allgood/centos_ex",
    ):
        reachable[path] = os.path.exists(path)
    try:
        with open("agent-loop-jail-canary.txt", "w") as handle:
            handle.write("the jail's one mount is writable\n")
        writable = True
    except OSError:
        writable = False
    report = "; ".join(
        [
            "cwd=%s" % os.getcwd(),
            "uname=%s" % " ".join(os.uname()[:3]),
            "reachable=%s" % json.dumps(reachable, sort_keys=True),
            "non-virtual mounts=%s" % ",".join(mounts()),
            "worktree writable=%s" % writable,
        ]
    )
    print(json.dumps({
        "diff_applied": False,
        "test_path": "",
        "mutation_evidence": {"reverted_command": "", "observed_failure_line": ""},
        "status": "blocked",
        "reason": "jail canary, no fix attempted: " + report,
    }))


if __name__ == "__main__":
    main()
