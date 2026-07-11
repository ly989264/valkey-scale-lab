# C04 Exact-scale requirements

The gate must create required exact-scale claim ids:

```text
setup_telemetry.real_exact.30
setup_telemetry.real_exact.50
setup_telemetry.real_exact.100
setup_telemetry.real_exact.200
command_audit.real_exact.50
command_audit.real_exact.100
command_audit.real_exact.200
management_matrix.real_exact.50
management_matrix.real_exact.100
management_matrix.real_exact.200
workload_benchmark.real_exact.30
workload_benchmark.real_exact.50
workload_benchmark.real_exact.100
workload_benchmark.real_exact.200
fault_timeline.real_exact.50
fault_timeline.real_exact.100
fault_timeline.real_exact.200
system_metrics.real_exact.30
system_metrics.real_exact.50
system_metrics.real_exact.100
system_metrics.real_exact.200
report.real_exact.30
report.real_exact.50
report.real_exact.100
report.real_exact.200
cleanup.real_exact.30
cleanup.real_exact.50
cleanup.real_exact.100
cleanup.real_exact.200
```

If a claim is not meaningful, it must be explicitly marked non-required with rationale; it must not be omitted.
