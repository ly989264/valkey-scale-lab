# Milestone 1 v4 Cache and Admission

V4 supersedes the historical v3 completion result. It keeps the frozen scale
contract but changes the program boundary for real gates.

Each required scale has two ordered checks:

1. `capture` runs the expensive product-owned real cluster lifecycle. Its cache
   key contains the product digest and raw evidence, but not the evaluator.
2. `admission` runs the current semantic evaluator over the preserved capture.
   Its cache key contains product inputs, evaluator inputs, and evidence.

An evaluator repair therefore invalidates every affected admission result while
leaving an unchanged raw cluster capture reusable. `VERIFY` cannot turn an old
admission PASS into a new PASS by reusing a pre-upgrade cache entry.

V4 state lives only under `loop_evidence/meta_runs/milestone1-v4`. V3 state,
event journals, logs, and evidence remain historical and read-only.

The product admission builder is also fail-closed: scenario IDs and operation
IDs must already exist in observed source events and command streams, all 14
scenarios need distinct operation provenance, and lifecycle PASS rows require
positive measured monotonic bounds with matching events.
