# 03_HARNESS_AND_GATES.md — Harness and Gate Model

## 1. Gate hierarchy

A phase gate has four layers:

```text
+--------------------------+
| postcheck                |
| schema + audit + logs    |
+------------+-------------+
             |
             v
+--------------------------+
| gate runner              |
| exact manifest commands  |
+------------+-------------+
             |
             v
+--------------------------+
| project behavior         |
| CLI, tests, runtime      |
+------------+-------------+
             |
             v
+--------------------------+
| real evidence            |
| Valkey probe/artifacts   |
+--------------------------+
```

Codex may implement project behavior. Codex must not replace gate runner or postcheck with weaker logic.

## 2. Gate result is not enough

`artifacts/gates/<PHASE_ID>/gate_result.json` is necessary but insufficient. Postcheck also verifies:

- every manifest gate was executed by name;
- command text exactly matches the manifest;
- every required gate exited 0;
- stdout/stderr logs exist;
- log checksums match the gate result;
- required artifacts exist;
- JSON/JSONL artifacts validate against schemas;
- real phases include real Valkey evidence;
- audit decision is fresh-context and PASS;
- audit cites the exact gate result path, checksum, and artifacts.

## 3. Real Valkey e2e proof

A real proof must include live network probing from a pre-authored script. Project tests alone do not count.

Required real evidence fields:

```json
{
  "schema_version": "v1",
  "artifact_type": "valkey_e2e_evidence",
  "phase_id": "P03_LOCAL_DOCKER_VALKEY",
  "real_valkey": true,
  "valkey_version_prefix_required": "9.1.",
  "probe_result": "PASS",
  "nodes_observed": 6,
  "cluster_state_observed": "ok",
  "data_path_result": "PASS"
}
```

The wrapper must independently issue commands such as `PING`, `INFO`, `CLUSTER INFO`, `CLUSTER NODES`, and for data-path scenarios `SET`/`GET` with MOVED/ASK retry support.

## 4. Audit proof

A phase audit must be done from a fresh context. The auditor must not trust the implementation agent's narrative. The auditor reads only repository state, diffs, gate logs, and artifacts.

Audit files:

```text
audit/<PHASE_ID>/AUDIT.md
audit/<PHASE_ID>/audit_decision.json
```

Postcheck requires both files. `AUDIT.md` must contain:

```text
Decision: PASS
Fresh Context: YES
Gate Result: artifacts/gates/<PHASE_ID>/gate_result.json
Observed Gate Result SHA256: <sha256>
```

`audit_decision.json` must validate against `schemas/artifact/audit_decision.schema.json`.

## 5. Baseline and regression gates

From P09 onward, artifact regression checks must compare current outputs against either:

- a committed baseline under `baselines/`, or
- an explicit `NO_BASELINE_YET` artifact status for the first run.

A missing baseline cannot be called PASS without the explicit first-run marker.

## 6. CI

CI must at minimum run:

```bash
python3 scripts/codex_gate.py precheck --all
python3 scripts/safety_scan.py
python3 -m compileall -q scripts
```

Once P03 is complete, CI or a separate required workflow must run at least one real Valkey e2e smoke gate in an environment that supports Docker. Heavy scale gates may use manual or scheduled workflows, but phase completion still requires their local gate results.

