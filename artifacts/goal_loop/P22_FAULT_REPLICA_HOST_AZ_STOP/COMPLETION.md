# COMPLETION - P22_FAULT_REPLICA_HOST_AZ_STOP

## Stage result

- Stage ID: P22_FAULT_REPLICA_HOST_AZ_STOP
- Review decision path: artifacts/goal_loop/P22_FAULT_REPLICA_HOST_AZ_STOP/REVIEW.md
- Audit decision path: audit/P22_FAULT_REPLICA_HOST_AZ_STOP/audit_decision.json

## Final commands

| Command | Result | Evidence |
|---|---:|---|
| python3 scripts/codex_gate.py postcheck --phase P22_FAULT_REPLICA_HOST_AZ_STOP | PASS | Main-agent run after review PASS |
| python3 scripts/codex_gate.py mark-complete --phase P22_FAULT_REPLICA_HOST_AZ_STOP | PASS | `MARKED_COMPLETE P22_FAULT_REPLICA_HOST_AZ_STOP` |
| git status --short | PASS | Intentional P22 files only before commit |
| git commit | PENDING | Filled by the stage commit containing this artifact |
| git push | PENDING | Filled by the push of the stage commit |

## Commit

- Commit hash: stage commit containing this file
- Commit message: P22_FAULT_REPLICA_HOST_AZ_STOP: add real replica host AZ stop faults

## Artifacts

- Phase artifacts: artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/
- Goal-loop artifacts: artifacts/goal_loop/P22_FAULT_REPLICA_HOST_AZ_STOP/
- Audit artifacts: audit/P22_FAULT_REPLICA_HOST_AZ_STOP/
- Gate result: artifacts/gates/P22_FAULT_REPLICA_HOST_AZ_STOP/gate_result.json

## Next stage

- Next stage ID: P23_FAULT_NETWORK_DELAY_LOSS_FLAP
- Handoff: P23 should build on P22's owned-runtime fault lifecycle, workload windows, topology snapshots, and cleanup verification, while adding sandboxed delay/loss/flap behavior without host network mutation.
