# Requirements/Harness Design Response

CML01 harness is frozen around seven new schemas and `tools/capability_matrix_gate.py` validation. The positive path requires operation, fault, metrics, workload, analysis, report index, and capability matrix artifacts. The negative path intentionally mutates the positive artifacts to prove rejection of empty metrics, zero-filled missing metrics, checksum-free reports, old artifact reuse, and fake real-Valkey evidence.
