# L08_30_50_100_FAULT_FAILOVER_SCENARIOS Stage Design

Design timestamp: 2026-06-30T15:18:00Z

## Objective

Extend large-cluster fault/failover evidence beyond the existing six-node P08 primary-stop proof. L08 must cover 30, 50, and 100 real Valkey rungs with wrapper-produced fault/failover artifacts, explicit workload windows, cleanup proof, metric coverage, and report views over source artifacts.

## Design Inputs

- `requirements_analyst`: APPROVED. Key gap is no committed 30/50/100 fault or failover evidence; existing wrapper and schemas do not yet produce or enforce L08 artifacts.
- `harness_architect`: APPROVED. Proposed strict L08 audit schema, workload-window schema, deterministic artifact tests, wrapper contract tests, real gate commands, coverage integration, and CI gate.
- `risk_auditor`: APPROVED. Highest-risk item is current `node_stop` behavior for `docker_process` scale rungs: stopping the shared nodehost container is too broad and would invalidate single-primary failover evidence.

## Harness Strategy

1. Add strict artifact contracts that do not weaken historical P07/P08 schemas:
   - `schemas/artifact/workload_window_report.schema.json`
   - `schemas/artifact/fault_failover_scale.schema.json`
2. Add deterministic L08 audit harness first:
   - synthetic complete 30/50/100 bundles pass;
   - missing workload windows fail;
   - unsafe host-network or shared-nodehost stop semantics fail;
   - fake/small-real/P08 evidence cannot count as 30/50/100 coverage;
   - P14/1000 real evidence is rejected.
3. Add a machine-readable audit producer:
   - `scripts/audit_fault_failover_scale.py`
   - reads JSON source artifacts only;
   - emits `artifacts/loop_engineering/reports/fault_failover_scale.json`;
   - exits nonzero on blocking findings.
4. Add runtime/wrapper support:
   - process-runtime `node_stop` must terminate only the selected logical node PID inside the owned nodehost container;
   - wrapper must accept scale scenarios and named `--fault-report`, `--workload-window-report`, and `--cleanup-report` outputs;
   - wrapper must record fault apply/clear latency, failover latency, promotion, before/during/after observations, workload windows, safety checks, and cleanup residual count.
5. Add coverage/report integration:
   - coverage matrix can mark 30/50/100 fault, failover, and workload surfaces covered only from `fault_failover_scale.json` and source artifacts;
   - 1000 dry-run remains `real_valkey_coverage=false`.
6. Run resource preflight and real gates only after harness and wrapper implementation are ready. Resource failure for any required rung is BLOCKED, not PASS.

## Canonical L08 Source Artifacts

For each `N in {30, 50, 100}`:

- `resource_preflight_fault_<N>.json`
- `fault_report_<N>.json`
- `failover_report_<N>.json`
- `workload_window_report_<N>.json`
- `valkey_e2e_evidence_fault_<N>.json`
- `cleanup_report_fault_<N>.json`

The audit output `fault_failover_scale.json` is derived from those source artifacts and records source paths and hashes.

## Required Metrics

- fault apply latency;
- fault clear latency;
- promotion observed;
- failover latency ms;
- cluster state before, during, after promotion, and after clear;
- nodes observed before, during, after promotion, and after clear;
- availability window values;
- workload operation counts, errors, timeouts, and latency summaries before/during/after;
- split-brain indicators or explicit `MISSING` reason;
- cleanup residual count.

## Safety Boundaries

- No host network, firewall, routing, PF, nftables, iptables, host interface, or OS network service mutation.
- No `sudo` path for network/route/firewall/interface changes.
- No broad host process kill, `killall`, `pkill -f`, or unrelated container/process kill.
- `docker_process` primary stop must use owned state (`nodehost_container_name`, logical `pid`, `logical_id`) and must not `docker stop` a shared nodehost container.
- P14 and 1000-node real fault/failover execution are forbidden in this stage.

## Expected Initial Failures

Before implementation, the proposed L08 harness should fail because:

- no `fault_failover_scale.json` exists;
- no `workload_window_report.schema.json` or `fault_failover_scale.schema.json` exists;
- current `fault_failover_gate.py` lacks scale scenario and named artifact arguments;
- current process-runtime `node_stop` is not scoped tightly enough for shared nodehost containers;
- coverage matrix has no 30/50/100 fault/failover source artifacts.

## Acceptance

L08 can pass only after previous harness remains green, deterministic L08 harness passes, real 30/50/100 wrapper evidence or BLOCKED resource evidence is produced according to contract, Phase F agents approve, anti-regression passes, stage result is written, and the stage is committed and pushed.
