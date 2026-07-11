# valkey-scale-lab

`valkey-scale-lab` is a local-first harness for Valkey 9.1.x cluster experiments. The milestone1 loop targets real local clusters up to 200 nodes, management operations, sandboxed faults, failover measurement, metrics collection, analysis, and offline report generation from versioned artifacts.

## Milestone1 Scope

Current milestone1 work is organized under `codex_goal_loop_m1/` and runs stages `M1-S01` through `M1-S09`.

In scope:

- local Docker/process-backed Valkey cluster runs on Mac/Linux;
- real small, 30, 50, 100, and bounded 200 node runs after resource preflight;
- run-scoped artifacts under `runs/<run_id>/artifacts|logs|reports|state`;
- schema-validated metadata, metrics, timelines, management/fault artifacts, analysis, and reports;
- offline report generation from local artifacts only.

Out of scope for milestone1:

- ECS multi-host native runtime;
- 500, 1000, or 2000 real-node execution;
- long stability soak stages;
- reports that depend on external services, network access, or LLMs.

## Quick Start

Create a run directory and metadata:

```bash
python3 -m valkey_scale_lab.cli run init --run-id m1-local
```

This creates:

```text
runs/m1-local/artifacts/
runs/m1-local/logs/
runs/m1-local/reports/
runs/m1-local/state/run_metadata.json
runs/m1-local/state/run_manifest.json
```

Validate a config and create a plan:

```bash
python3 -m valkey_scale_lab.cli config validate --config config/example.yaml --out runs/m1-local/artifacts/config_validation_report.json
python3 -m valkey_scale_lab.cli plan --config config/example.yaml --out runs/m1-local/artifacts/cluster_plan.json --dry-run
```

Run a supported gate scenario with explicit run-scoped outputs:

```bash
python3 -m valkey_scale_lab.cli gate scenario \
  --phase P03_LOCAL_DOCKER_VALKEY \
  --scenario cluster_smoke \
  --config config/example.yaml \
  --artifacts-dir runs/m1-local/artifacts \
  --state-out runs/m1-local/state/run_state.json
```

Cleanup:

```bash
python3 -m valkey_scale_lab.cli gate cleanup \
  --state runs/m1-local/state/run_state.json \
  --artifacts-dir runs/m1-local/artifacts \
  --out runs/m1-local/state/cleanup_report.json
```

## Reports

Analysis and reports read schema artifacts. New milestone1 paths prefer `run_manifest.json`; legacy explicit artifact directories remain supported for compatibility.

```bash
python3 -m valkey_scale_lab.cli analyze --input runs/m1-local --out runs/m1-local/artifacts/analysis_summary.json
python3 -m valkey_scale_lab.cli report \
  --analysis runs/m1-local/artifacts/analysis_summary.json \
  --out-dir runs/m1-local/reports \
  --index-out runs/m1-local/reports/report_index.json
```

The report index records references back to `state/run_metadata.json` and `state/run_manifest.json`.

## Harness Gates

Milestone1 stages use strong gates. M1-S01 includes:

```bash
python3 scripts/assert_run_metadata_contract.py
```

Common checks:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/vslab-pyc python3 -m compileall -q scripts src
python3 -m pytest -q tests/unit tests/integration
```

If real Docker/Valkey resources are unavailable, gates must emit `BLOCKED_WITH_REASON`; fake real evidence is not allowed.
