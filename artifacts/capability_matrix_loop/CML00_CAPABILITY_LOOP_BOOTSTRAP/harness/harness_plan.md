# Harness Plan

CML00 creates the supplemental loop harness and validates it with a dedicated runner. The harness is additive and does not modify existing P00-P13 gate files.

Negative tests are enforced by `tools/capability_matrix_gate.py make_negative_cases()` and cover missing artifact, fake real Valkey evidence, skip-as-pass, missing cleanup, report source without checksum, and old artifact reuse.
