# 12_REPORT_QUALITY_CONTRACT.md

## Report is not proof

A Chinese offline report proves only that rendering works. It does not prove source evidence quality.

## Report input gate

`assert_report_input_quality.py` must fail the report stage if:

- the report source is fixture-only while milestone PASS is claimed;
- setup input has skipped core metrics for a real run;
- workload input has insufficient profiles/windows/metrics;
- fault input is fake/PARTIAL but rendered as real;
- command audit input lacks required command kinds;
- system metrics input lacks required lifecycle windows;
- report index claims `status: PASS` while source quality is blocked.

## Offline requirement

The report must remain offline:

```json
{"artifact_only": true, "llm_used": false, "external_urls_allowed": false, "cdn_allowed": false, "online_chart_service_allowed": false}
```
