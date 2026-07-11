# Harness Extension: P46_REPOSITORY_LAYOUT_MIGRATION

## Limitation

The completed harness had no maintenance stage or repository-layout contract. The user-required two-directory migration therefore could not be represented, audited, or completed without extending protected controls. Pre-migration `precheck --all` also exposed ten existing schema entries whose lock digests no longer matched the current clean-branch schema bytes. Those schemas were not changed for P46; retaining stale digests would make the lock reject the repository it is meant to protect.

## Minimal strengthening change

- Add one non-runtime P46 stage dedicated to repository layout and evidence integrity.
- Add a fail-closed validator, two artifact schemas, validator tests, and the authoritative P46 stage document.
- Keep GitHub workflows at repository root, change only shell-step working directories to `project/`, and lock both workflows through the project-relative `.github` compatibility link.
- Preserve logical `artifacts/...` references when active scripts traverse compatibility symlinks; path display/provenance helpers now prefer lexical project-relative paths before canonical fallback.
- Refresh all lock entries from the final active control bytes, including the ten pre-existing stale schema digests, without changing those schema files.
- Add the P46 validator, schemas, stage document, both workflows, and the finalized manifest to the lock set.
- Preserve the pre-strengthening schemas as read-only versioned snapshots and add an exact historical-compatibility registry. Compatibility is available only after current-schema failure and exact artifact SHA-256, historical-schema SHA-256, and producing gate-manifest SHA-256 matches. Negative tests prove any mutation fails closed.
- Treat the P46 manifest addition to immutable P40 provenance as an exact post-P40 extension binding; no wildcard manifest or source-hash exception is permitted.
- Bind the immutable pre-P46 provenance/report commit mismatch by exact provenance JSON and HTML SHA-256 values so final-audit compatibility cannot apply to regenerated or modified reports.
- Strengthen the layout report PASS contract with standard JSON Schema `if`/`then` constraints plus an independent semantic validator for cross-field equality. Recompute aggregate and every per-root baseline digest/count, and run end-to-end negative layout cases in temporary trees.

## Before and after

Before: moving directories would either break hard-coded harness paths or occur outside review/postcheck controls.

After: the migration has explicit immutable-baseline and layout artifacts, schemas, fail-closed gates, version-aware immutable evidence validation, a fresh review, postcheck, and mark-complete. Active controls resolve from `project/`; historical evidence remains byte-for-byte under `loop_evidence/`. Existing safety, real-evidence, and artifact requirements are unchanged or strengthened.
