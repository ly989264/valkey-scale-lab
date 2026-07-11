# CML04 Commands

```bash
PYTHONPATH=/opt/anaconda3/lib/python3.12/site-packages python3 tools/capability_matrix_gate.py previous-harness --stage CML04_NETWORK_PARTITION_AND_AZ_FAULTS_30
python3 scripts/fault_safety_gate.py --phase P07_FAULT_INJECTION_SANDBOX --config templates/configs/scale_30.yaml --out artifacts/capability_matrix_loop/CML04_NETWORK_PARTITION_AND_AZ_FAULTS_30/samples/real_valkey_evidence_network_30.json --fault-report artifacts/capability_matrix_loop/CML04_NETWORK_PARTITION_AND_AZ_FAULTS_30/samples/network_fault_report_30.json --min-nodes 30
PYTHONPATH=/opt/anaconda3/lib/python3.12/site-packages python3 tools/capability_matrix_gate.py run --stage CML04_NETWORK_PARTITION_AND_AZ_FAULTS_30
```
