# SELF_AUDIT_OF_PREVIOUS_PACKAGE.md

## Finding

The previous hardening package was not hard enough. It described anti-shortcut behavior but did not require Codex to implement fail-closed machine gates before every stage could pass.

## Specific weaknesses fixed in v2

| Previous weakness | v2 fix |
|---|---|
| Natural-language “do not cheat” rules | Required executable `scripts/m1h/*` gates |
| No explicit evidence taxonomy | Mandatory evidence manifest with evidence kinds |
| Fixture fallback not machine-forbidden | `assert_no_fixture_fallback.py` and static forbidden pattern contract |
| Legacy evidence allowed to imply new M1 PASS | `assert_no_legacy_m1_pass.py` and claim ledger rules |
| Core skipped metrics not fail-closed | setup/system/workload/fault contracts disallow skipped core metrics for real PASS |
| Simulated subagents possible | `assert_no_simulated_subagents.py` and blocked-if-no-real-subagent rule |
| Final acceptance could be prose or non-empty checks | `assert_final_milestone1_hardened.py` with required claim matrix |

## Remaining limitation

No Markdown package can mathematically guarantee that an autonomous coding agent will behave correctly. This package instead makes the desired behavior machine-checkable and fail-closed. If Codex follows the package, a false milestone PASS should be blocked by the gates. If Codex ignores the package, the resulting repository can be audited by the absence or failure of these gates.
