# CML12 Commands

- PYTHONPATH=/opt/anaconda3/lib/python3.12/site-packages python3 tools/capability_matrix_gate.py previous-harness --stage CML12_FUTURE_SCALE_200_500_1000_SUPPORT
- PYTHONPATH=/opt/anaconda3/lib/python3.12/site-packages python3 tools/capability_matrix_gate.py run --stage CML12_FUTURE_SCALE_200_500_1000_SUPPORT
- PYTHONPATH=/opt/anaconda3/lib/python3.12/site-packages python3 -m pytest tests/capability_loop/test_capability_matrix_gate.py -q
