role: worker
agent_invocation: real_subagent
stage_id: H06_WORKLOAD_BENCHMARK_HARDENING
source_commit_before: 038bf1cf50aa04b1c575352e4f326eeb91886e74
source_commit_after: MISSING

# WORKER_SUMMARY

## Implementation

H06 workload benchmark claims now require C08-strength evidence before `workload_benchmark.real_exact.{30,50,100,200}` can pass:

- same-directory `workload_windows.json`, `metrics_timeseries.jsonl`, and real Valkey 9.1.x `valkey_e2e_evidence.json`;
- required profiles: `smoke`, `uniform`, `hotspot`, `mixed_rw`, `write_heavy`, `read_heavy`;
- required windows: `baseline`, `pre_event`, `event`, `recovery`, `post_recovery`, `all_run`;
- all required QPS, throughput, operation, error, latency, timeout, connection, MOVED/ASK, CLUSTERDOWN, READONLY, and TRYAGAIN metrics;
- at least 648 H06 core metric rows;
- numeric required values with no `MISSING` or `SKIPPED_WITH_REASON` core values for real PASS;
- minimum operations per window;
- observed connection and pipeline evidence;
- full-slot coverage for every non-smoke profile.

The dedicated gate `scripts/m1h/assert_workload_benchmark_strength.py` verifies PASS claims and accepts current blocked claims only when they carry H06 diagnostics and explicit reasons. `scripts/m1h/assert_stage_exit.py` now requires this gate for `H06_WORKLOAD_BENCHMARK_HARDENING`.

## Tests

Added focused tests for:

- valid synthetic H06 exact-scale bundle passing;
- missing profile;
- missing window;
- shallow metric row count;
- missing, string, and skipped metric values;
- low operation count;
- missing connection evidence;
- missing pipeline evidence;
- missing full-slot coverage and fixed hash-tag coverage;
- fixture-only evidence;
- fake or partial artifact markers;
- split-directory evidence that cannot be spliced;
- H06 stage-exit required gate coverage.

Verification:

```text
python3 -m pytest -q tests/m1h/test_gate_framework.py -k 'workload_benchmark or h06'
12 passed, 50 deselected

python3 -m pytest -q tests/m1h/test_gate_framework.py
62 passed

python3 -m pytest -q tests/m1h
62 passed

PYTHONPYCACHEPREFIX=/private/tmp/valkey-scale-lab-pycache-h06 python3 -m compileall -q scripts/m1h tests/m1h/test_gate_framework.py
PASS
```

## Notes

Current repository workload claims should remain `BLOCKED_WITH_REASON` until real exact-scale C08 bundles exist. Gate result JSON, review artifacts, and completion handoffs were not manually edited.
