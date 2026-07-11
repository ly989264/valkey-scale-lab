# Previous Harness Failure

Stage: CML00_CAPABILITY_LOOP_BOOTSTRAP

## Failing command

`python3 tools/capability_matrix_gate.py previous-harness --stage CML00_CAPABILITY_LOOP_BOOTSTRAP`

## Classification

existing_harness_artifact_staleness

## Evidence

All completed P00-P13 postchecks fail because `artifacts/gates/<PHASE>/gate_result.json` records manifest sha `87fa9952002f6f606dd10984fd6700d4eb577c7388cb755ece52e4688c2adad4`, while the current committed `codex/phase_manifest.json` sha is `5f96e9eb5697dba41d9bf0f1d0d5a585b71b7687b3a51c9fcafdb13b6073d7a8`. P13 also reports a gate command mismatch.

## Safety decision

Do not modify or weaken old harness. Repair path is to rerun the affected phases through `scripts/codex_gate.py run --phase <PHASE>` and refresh the fresh-context audit files so postcheck validates current gate logs and checksums.
