# P29 Harness Exception

## Defect

`scripts/assert_quant_completeness.py` only checked for coarse artifact presence and a few runtime claim flags. P29 could have passed with JSONL rows missing strict fields, `MISSING` metrics without reasons, incomplete workload windows, absent provenance hashes, or a coverage ledger that incorrectly marked matrix rows as complete.

`scripts/valkey_e2e_gate.py` wrote the real evidence and cleanup artifacts after runtime telemetry generation, so P29's telemetry completeness report could not include final hashes for those wrapper-produced source artifacts.

## Patch

`scripts/assert_quant_completeness.py` now has a P29 strict validation path that checks event and metric JSONL line by line, requires `stage_id`, `coverage_id`, `scale`, and `node_count`, rejects forbidden null/NaN/Infinity/undefined placeholder values, verifies `MISSING` metric reasons, validates canonical workload windows and event-id links, requires source coverage and provenance hashes, checks cleanup/evidence status, and rejects any P29 coverage ledger row that is not `PENDING`.

`scripts/valkey_e2e_gate.py` now refreshes P29 telemetry completeness report hashes after writing `valkey_e2e_evidence.json` and after cleanup has produced `cleanup_report.json`. It also encodes probe `null` values as reasoned `MISSING` objects so real evidence cannot carry forbidden missing-data placeholders.

## Before/After

Before: P29 could pass with shallow telemetry artifacts that looked present but were not strict, traceable, or fail-closed.

After: P29 cannot pass unless the real 6-node collector proof produces complete strict telemetry artifacts with source hashes, reasoned missing data, cleanup PASS, no forbidden `null` probe values, and no large-scale matrix coverage claim.
