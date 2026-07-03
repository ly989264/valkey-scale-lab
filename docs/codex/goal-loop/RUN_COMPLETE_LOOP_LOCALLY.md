# Run the Complete Goal Loop Locally

This runbook is for the automatic P15-P26 goal loop.

1. Check the next stage:

```bash
python3 scripts/codex_gate.py next
```

2. For the current stage, run:

```bash
python3 scripts/codex_gate.py precheck --phase <STAGE_ID>
python3 scripts/codex_gate.py run --phase <STAGE_ID>
```

3. For P26 final reports, the generation command is:

```bash
python3 -m valkey_scale_lab.cli report \
  --kind final-goal-loop \
  --input artifacts/phases \
  --out-dir artifacts/phases/P26_FINAL_REPORT_REGRESSION \
  --phase P26_FINAL_REPORT_REGRESSION
```

P26 consumes JSON and JSONL artifacts from P04 and P16-P25. It does not rerun P17-P25 source scenarios, does not run P14, and does not use logs or rendered views as metric sources.

4. Review final outputs in:

```text
artifacts/phases/P26_FINAL_REPORT_REGRESSION/final_report_index.json
artifacts/phases/P26_FINAL_REPORT_REGRESSION/reports/
artifacts/phases/P26_FINAL_REPORT_REGRESSION/exports/
artifacts/phases/P26_FINAL_REPORT_REGRESSION/regression/
```

5. After fresh-context review passes, the main agent runs postcheck and mark-complete. P14 remains opt-in and non-automatic.
