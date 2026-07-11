# CML01 Commands

```bash
PYTHONPATH=/opt/anaconda3/lib/python3.12/site-packages python3 tools/capability_matrix_gate.py previous-harness --stage CML01_UNIFIED_OBSERVATION_AND_ARTIFACT_MODEL
python3 scripts/valkey_e2e_gate.py --phase P03_LOCAL_DOCKER_VALKEY --config artifacts/capability_matrix_loop/CML01_UNIFIED_OBSERVATION_AND_ARTIFACT_MODEL/samples/config_6node.yaml --scenario cluster_smoke --out artifacts/capability_matrix_loop/CML01_UNIFIED_OBSERVATION_AND_ARTIFACT_MODEL/samples/real_valkey_evidence.json --min-nodes 6 --require-data-path --setup-timeout 300 --cleanup-timeout 120
PYTHONPATH=/opt/anaconda3/lib/python3.12/site-packages python3 tools/capability_matrix_gate.py run --stage CML01_UNIFIED_OBSERVATION_AND_ARTIFACT_MODEL
```
