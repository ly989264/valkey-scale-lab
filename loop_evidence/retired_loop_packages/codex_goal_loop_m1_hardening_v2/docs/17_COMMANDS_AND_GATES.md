# 17_COMMANDS_AND_GATES.md

## Common commands every stage must run

```text
python3 -m compileall -q scripts src tests
python3 -m pytest -q tests/unit tests/integration
python3 scripts/m1h/assert_no_fixture_fallback.py
python3 scripts/m1h/assert_no_legacy_m1_pass.py
python3 scripts/m1h/assert_no_simulated_subagents.py --stage <stage_id>
python3 scripts/m1h/assert_stage_exit.py --stage <stage_id>
```

If a command cannot run due to platform/resource limits, the stage must produce `BLOCKED_WITH_REASON`; it may not mark PASS unless the stage contract explicitly allows blocked as the correct outcome.

## Stage-specific gates

Stage files list additional gates. Those gates are required.
