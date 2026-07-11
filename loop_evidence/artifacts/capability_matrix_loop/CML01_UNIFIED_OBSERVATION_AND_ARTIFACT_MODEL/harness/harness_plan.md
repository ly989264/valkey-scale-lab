# CML01 Harness Plan

1. Keep previous P00-P13 harness validation as the first gate.
2. Freeze CML01 schemas for operation, fault, metrics, workload, analysis, report index, and capability matrix artifacts.
3. Require a fresh real Valkey data-path sample from `scripts/valkey_e2e_gate.py`.
4. Validate checksum-backed report provenance and reject empty metrics, zero-filled missing values, fake real evidence, and old artifact reuse.
