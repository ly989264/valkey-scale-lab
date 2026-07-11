# Agent Response

## Identity
- role: requirements_harness_architect
- stage_id: CML00_CAPABILITY_LOOP_BOOTSTRAP
- fresh_context: YES

## Inputs Read
| path | sha256 | used_for |
|---|---:|---|
| codex/capability_loop_prompt/04_CAPABILITY_STAGE_PLAN.md | 5063f62b03bacae367928cf2c94175a38b533b951305a3ef533bb45706005565 | CML00 scope and validation standards |
| codex/capability_loop_prompt/03_HARNESS_POLICY.md | b60640879d907ded6279c149637b3181b63689df2f715524f6d962eec576727f | negative tests and freeze policy |
| docs/codex/03_HARNESS_AND_GATES.md | b3149efc2200404e08661e627dbc007934a944fc01e7489e0daf1d1d26d42762 | previous harness evidence model |

## Findings
- CML00 should add a supplemental harness without touching existing P00-P13 harness.
- Current gate must reject missing artifacts, fake Valkey evidence, skip-as-pass, cleanup gaps, report sources without checksums, and old artifact reuse.

## Proposed Changes
| file | action | reason | harness_or_impl |
|---|---|---|---|
| codex/capability_matrix_loop/stage_manifest.json | add | stage list and CML00 required artifacts | harness |
| schemas/capability_matrix_loop/*.json | add | schema-first artifacts | harness |
| tools/capability_matrix_gate.py | add | executable CML gate runner | harness |
| tests/capability_loop/test_capability_matrix_gate.py | add | negative and policy tests | harness |

## Validation Plan
```bash
python3 -m compileall -q tools tests/capability_loop
pytest -q tests/capability_loop/test_capability_matrix_gate.py
python3 tools/capability_matrix_gate.py run --stage CML00_CAPABILITY_LOOP_BOOTSTRAP
```

## Risks
| risk | mitigation | blocks_stage |
|---|---|---|
| Stage result is generated after current gate | current gate skips post-gate artifacts; fresh review validates them | no |

## Machine Summary
```json
{"decision":"PROCEED","stage_id":"CML00_CAPABILITY_LOOP_BOOTSTRAP","role":"requirements_harness_architect","harness_files":["codex/capability_matrix_loop/stage_manifest.json","tools/capability_matrix_gate.py"],"implementation_files":[],"required_artifacts":["reports/capability_matrix_baseline.json"],"validation_commands":["python3 tools/capability_matrix_gate.py run --stage CML00_CAPABILITY_LOOP_BOOTSTRAP"]}
```
