# CML03 Commands

```bash
PYTHONPATH=/opt/anaconda3/lib/python3.12/site-packages python3 tools/capability_matrix_gate.py previous-harness --stage CML03_PROCESS_AND_NODEHOST_FAULTS_30
python3 scripts/fault_failover_gate.py --phase P12_SCALE_LADDER_10_30 --scenario scale_30_fault_failover --config templates/configs/scale_30.yaml --out artifacts/capability_matrix_loop/CML03_PROCESS_AND_NODEHOST_FAULTS_30/samples/real_valkey_evidence_fault_30.json --failover-report artifacts/capability_matrix_loop/CML03_PROCESS_AND_NODEHOST_FAULTS_30/samples/failover_report_30.json --fault-report artifacts/capability_matrix_loop/CML03_PROCESS_AND_NODEHOST_FAULTS_30/samples/fault_report_30.json --workload-window-report artifacts/capability_matrix_loop/CML03_PROCESS_AND_NODEHOST_FAULTS_30/samples/workload_window_report_30.json --cleanup-report artifacts/capability_matrix_loop/CML03_PROCESS_AND_NODEHOST_FAULTS_30/samples/cleanup_report_fault_30.json --require-data-path --min-nodes 30 --wait-after-fault 90 --failover-node-timeout-ms 15000
PYTHONPATH=/opt/anaconda3/lib/python3.12/site-packages python3 tools/capability_matrix_gate.py run --stage CML03_PROCESS_AND_NODEHOST_FAULTS_30
```
