# CML10 Commands

- PYTHONPATH=/opt/anaconda3/lib/python3.12/site-packages python3 tools/capability_matrix_gate.py previous-harness --stage CML10_SCALE_REPLAY_50
- PYTHONPATH=/opt/anaconda3/lib/python3.12/site-packages python3 tools/capability_matrix_gate.py run --stage CML10_SCALE_REPLAY_50
- PYTHONPATH=/opt/anaconda3/lib/python3.12/site-packages python3 -m pytest tests/capability_loop/test_capability_matrix_gate.py -q
