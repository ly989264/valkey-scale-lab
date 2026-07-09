# 05_EVIDENCE_MANIFEST_AND_CLAIM_LEDGER.md

## Evidence manifest

The hardening loop must maintain:

```text
runs/m1-hardening/evidence_manifest.json
```

This is generated from repository artifacts, not manually edited. It lists every claim used for stage and milestone acceptance.

## Claim ledger

Each claim must include:

```json
{
  "claim_id": "setup_telemetry.real_exact.200",
  "capability": "setup_telemetry",
  "scale": 200,
  "required_for_milestone_pass": true,
  "evidence_kind": "REAL_EXACT_SCALE",
  "source_artifacts": ["..."],
  "m1_format_version": "v1",
  "generated_after_stage": "H03",
  "semantic_checks": {
    "schema_valid": true,
    "no_fixture_path": true,
    "no_legacy_only": true,
    "core_metrics_numeric": true
  },
  "status": "PASS"
}
```

## No manual claim edits

If Codex needs to change claims, it must change the manifest builder and tests, not hand-edit the manifest.
