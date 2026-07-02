# Harness Exception

- stage_id: CML00_CAPABILITY_LOOP_BOOTSTRAP
- failing command: `pytest -q` during previous harness verification
- original harness file: `scripts/audit_small_real_scenario_parity.py`
- defect: The small-real parity harness required P08 failover `data_path_result` to be exactly `SKIPPED_WITH_REASON`. After rerunning the current real `scripts/fault_failover_gate.py`, P08 now produces stronger live data-path evidence with `data_path_result: PASS`. The old assertion converted stronger real evidence into a failure.
- why this is not weakening: The patch requires P08 failover data-path evidence to be `PASS` instead of accepting skipped data-path evidence. Fault sandbox P07 remains `SKIPPED_WITH_REASON` because that wrapper intentionally does not perform a data-path check.
- before behavior: Current P08 real failover gate PASS artifact caused `invalid_real_evidence` in small-real parity audit.
- after behavior: P08 failover must provide real data-path PASS evidence; fake, missing, or failed evidence still fails.
- reviewer decision: APPROVED_AS_STRENGTHENING
