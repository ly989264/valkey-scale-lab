# AGENTS.md — Valkey 9 Ultra-Scale Local Cluster Lab

This repository is built by Codex in a strict phase loop. Codex must treat this file as the controlling instruction source and must read `CODEX_START_HERE.md` before editing code.

## Mission

Build `valkey-scale-lab`: a local-first, Docker-sandboxed test and analysis harness for Valkey 9.1.x cluster behavior at increasing scale. The project must support Mac and Linux, single-host and multi-host operation, virtual AZ placement, real Valkey e2e gates, fault injection, metric collection, analysis, and report generation.

Machine-readable artifacts are the product. Charts, HTML, and markdown reports are only views over versioned artifacts.

## Non-negotiable safety rules

1. Never default to 1000 Valkey nodes. Default development phases are capped at 100 nodes.
2. Never change physical host network configuration.
3. Never modify global firewall, routing, PF, nftables, iptables, host interfaces, or OS network services.
4. Never use `sudo` for network, route, firewall, or interface changes as a default path.
5. Fault injection must be scoped to owned Docker/container namespaces, owned containers, or an explicit sandbox proxy layer.
6. Never kill physical host network interfaces or unrelated host processes.
7. Every started process/container must have deterministic cleanup logic, state files, and ownership labels.
8. Ports, directories, PID files, container names, and run IDs must be deterministic and collision-checked.
9. Fake tests may support early development, but fake-only gates must never be presented as real Valkey evidence.
10. No phase may pass without required artifacts, schema validation, gate logs, and an audit decision.
11. Missing metrics must be encoded as `MISSING` or `SKIPPED_WITH_REASON`; never invent values.
12. Codex must not stop after skeleton work. Continue through all automatic phases until the next phase is blocked by a real gate failure.

## Harness integrity rules

The files below are pre-authored harness controls. Do not weaken them, delete them, bypass them, or edit the lock file to hide changes:

- `codex/phase_manifest.json`
- `codex/gate_lock.json`
- `scripts/*.py`
- `schemas/**/*.json`
- `templates/**/*`
- `docs/codex/**/*`
- `.github/workflows/codex-gates.yml`

If a harness file is truly defective, stop the current phase, write `artifacts/harness_exception/<phase>.md`, and make the smallest fix that strengthens or preserves the original requirement. The phase audit must explicitly cite the defect, patch, and before/after behavior.

## Required phase loop

For each automatic phase, Codex must execute this loop:

1. Determine the next incomplete automatic phase from `codex/phase_manifest.json` and `codex/status/phase_state.json`.
2. Read that phase in `docs/codex/02_PHASES.md` and its manifest entry.
3. Implement only the current phase, preserving previous phase behavior.
4. Run `python3 scripts/codex_gate.py precheck --phase <PHASE_ID>`.
5. Run `python3 scripts/codex_gate.py run --phase <PHASE_ID>`.
6. Inspect the generated gate result and logs under `artifacts/gates/<PHASE_ID>/`.
7. Produce all required artifacts listed in `codex/phase_manifest.json`.
8. Launch a fresh-context reviewer/auditor using `docs/codex/04_AUDITOR.md` and `templates/audit/FRESH_CONTEXT_AUDIT_PROMPT.md`.
9. The auditor must create `audit/<PHASE_ID>/AUDIT.md` and `audit/<PHASE_ID>/audit_decision.json`.
10. Run `python3 scripts/codex_gate.py postcheck --phase <PHASE_ID>`.
11. If any gate, artifact validation, or audit check fails, fix the current phase and repeat from step 4.
12. After postcheck passes, run `python3 scripts/codex_gate.py mark-complete --phase <PHASE_ID>`.
13. Commit and push the phase on the current branch before starting the next phase.

`P14_SCALE_1000_OPTIN_DRYRUN` is not automatic. Do not run it unless the user explicitly opts in and sets the required environment variable stated in the manifest.

## Real Valkey gates

From P03 onward, each capability must have at least one real Valkey e2e proof. A real proof must be produced by the pre-authored wrapper scripts, not by project tests alone:

- `scripts/valkey_e2e_gate.py` for real cluster/workload/metrics/scale scenarios.
- `scripts/fault_safety_gate.py` for sandboxed network/process fault scenarios.
- `scripts/fault_failover_gate.py` for failover scenarios.

A gate is not real if it only asserts mocks, fake Valkey, generated logs, or static files. The wrapper must independently probe live Valkey endpoints and produce evidence with Valkey 9.1.x version data.

## Project interface contract

Codex must implement a Python package importable as `valkey_scale_lab` and a CLI module callable as:

```bash
python3 -m valkey_scale_lab.cli <command> ...
```

The pre-authored gate wrappers call these commands:

```bash
python3 -m valkey_scale_lab.cli gate scenario \
  --phase <PHASE_ID> \
  --scenario <SCENARIO_NAME> \
  --config <CONFIG_PATH> \
  --artifacts-dir <ARTIFACT_DIR> \
  --state-out <STATE_JSON>

python3 -m valkey_scale_lab.cli gate cleanup \
  --state <STATE_JSON> \
  --artifacts-dir <ARTIFACT_DIR> \
  --out <CLEANUP_JSON>

python3 -m valkey_scale_lab.cli fault apply \
  --state <STATE_JSON> \
  --target-logical-id <NODE_LOGICAL_ID> \
  --fault-json <FAULT_JSON> \
  --out <FAULT_APPLY_JSON>

python3 -m valkey_scale_lab.cli fault clear \
  --state <STATE_JSON> \
  --fault-id <FAULT_ID> \
  --out <FAULT_CLEAR_JSON>
```

The `state-out` JSON must contain live endpoint data sufficient for independent probing:

```json
{
  "schema_version": "v1",
  "cluster_id": "run-specific-id",
  "phase_id": "P03_LOCAL_DOCKER_VALKEY",
  "runtime": {"type": "docker", "sandbox_network": true},
  "nodes": [
    {
      "logical_id": "shard-0000-primary",
      "host": "127.0.0.1",
      "client_port": 7000,
      "az_id": "az-a",
      "role": "primary",
      "container_id": "optional",
      "pid": 12345
    }
  ]
}
```

## Implementation boundaries

The preferred runtime is Docker/container namespaces on Mac and Linux. Linux may use container-scoped `NET_ADMIN` inside owned containers for `tc netem`; Mac should use Docker Desktop Linux VM namespaces or a sandbox proxy fallback. Host-level network modification is forbidden.

The CLI, planner, metrics, report engine, and artifacts must be deterministic enough for regression comparison. Non-determinism such as timestamps, run IDs, and random seeds must be explicitly recorded.

