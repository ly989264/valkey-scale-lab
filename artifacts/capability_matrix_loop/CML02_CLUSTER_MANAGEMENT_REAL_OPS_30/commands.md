# CML02 Commands

```bash
PYTHONPATH=/opt/anaconda3/lib/python3.12/site-packages python3 tools/capability_matrix_gate.py previous-harness --stage CML02_CLUSTER_MANAGEMENT_REAL_OPS_30
python3 scripts/valkey_e2e_gate.py --phase P12_SCALE_LADDER_10_30 --config templates/configs/scale_30.yaml --scenario scale_30 --out artifacts/capability_matrix_loop/CML02_CLUSTER_MANAGEMENT_REAL_OPS_30/samples/real_valkey_evidence_30.json --min-nodes 30 --require-data-path --setup-timeout 900 --cleanup-timeout 300
PYTHONPATH=/opt/anaconda3/lib/python3.12/site-packages python3 tools/capability_matrix_gate.py run --stage CML02_CLUSTER_MANAGEMENT_REAL_OPS_30
```
