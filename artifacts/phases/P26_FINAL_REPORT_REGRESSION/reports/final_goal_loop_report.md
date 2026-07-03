# P26 Final Goal Loop Report

Status: PASS

All report values in this package derive from JSON/JSONL artifacts. Logs and rendered Markdown/CSV/HTML views are not metric sources.

## Coverage

- Management rows: 11/11
- Failover rungs: 30, 50, 100, 200
- Fault rows: 12/12
- Workload impact rows: 49

## Safety Boundaries

- P14_SCALE_1000_OPTIN_DRYRUN remains non-automatic.
- Default automatic max nodes remains 100.
- P21's 200-node failover evidence is a bounded exception and is consumed as an artifact only.
- P26 did not rerun P17-P25 source scenarios.

## Source Artifacts

- `artifacts/phases/P04_CLUSTER_MANAGEMENT_OPS/management_ops_report.json` sha256 `3457e2b2e04b8ced543708158b2d10041f4aab6765963992df905f69aa3eef74`
- `artifacts/phases/P16_QUANT_TELEMETRY_UNIFICATION/quant_summary.json` sha256 `fe3f1efeb997792aaa5546e6ae9b9fbc0fa6e220f33fdf9f5906af0c438cffa7`
- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/management_ops_matrix.json` sha256 `9a92705dfa7db9abff8a1eb95e52d80b3a7234d1c73c0b8ba82b2a27b3c31b6e`
- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/management_operation_results.jsonl` sha256 `dbf854ec59eaabfc2ff25a0365a2415f054d7e6b163d55fa1718a7cd4a55159b`
- `artifacts/phases/P18_MANAGEMENT_RESHARD_REBALANCE/management_ops_matrix.json` sha256 `0f883c728eecad29afa7fdde41641027ab5c6144149d2355d1061ab495d1d00d`
- `artifacts/phases/P18_MANAGEMENT_RESHARD_REBALANCE/management_operation_results.jsonl` sha256 `7fba1f1b9c2a65a4e9bbe388d4d0c706a252c250e5e94fd65db9e2679e616558`
- `artifacts/phases/P19_MANAGEMENT_ROLLING_RESTART/management_ops_matrix.json` sha256 `153d12ccc953fcd2f85e416aaa1ab5dbb5d029e5b45ee65746aa53d124db53e2`
- `artifacts/phases/P19_MANAGEMENT_ROLLING_RESTART/management_operation_results.jsonl` sha256 `0b329388810316f14d83b91b50dc6e86045b0be14101c2f09dd67f1216598cf0`
- `artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/failover_latency_curve.json` sha256 `7e6d459beb96587f54bf92f3802a169cf694605f8499efa73098c612b947f1a7`
- `artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/failover_latency_samples.jsonl` sha256 `0f5533b1ca9c25c546712adf08adfc6ad765f59987454856c5d7c9c473c96063`
- `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/failover_latency_curve_combined_30_50_100_200.json` sha256 `c84f9b2fa84a38a12ac4938f456dd5f2003e4e58d565d346a6f245025325aba7`
- `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/failover_latency_samples_200.jsonl` sha256 `92a1b4d9b56a43a545772ff027232c12f98241938c065ffd1aee3b1068f59b1c`
- `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/fault_results.jsonl` sha256 `3474d92134af840ae3dad289a69ff050264acb7da8f23f0c31a32597511d526c`
- `artifacts/phases/P23_FAULT_NETWORK_DELAY_LOSS_FLAP/fault_results.jsonl` sha256 `dc5424ec71676893c54984a325234234c992f91ff3159074afc0eb22400b6953`
- `artifacts/phases/P23_FAULT_NETWORK_DELAY_LOSS_FLAP/network_fault_report.json` sha256 `bc0b902f9be75f8b91537e8fc07e957a8b6d1cadcf46d327d104f29009f470f3`
- `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/fault_results.jsonl` sha256 `e3f58df91ea8917a344fc958a7d5db2b37587e3077abbb236a684a0ae04e7204`
- `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/partition_report.json` sha256 `d4a36e27201e61bf4b346edee8c261238149beb2129e621de94a14c0e1a23e46`
- `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/split_brain_report.json` sha256 `db07e41bec06b019e51928d33d0a94d80cbc238467e0e0ca3ca2e6a1ae9b186a`
- `artifacts/phases/P25_FAULT_WORKLOAD_IMPACT_ANALYSIS/missing_data_summary.json` sha256 `dab96b59dbc1c3b577e869b90927d8716cb46ed4e344a568ec01c9e26e633949`
- `artifacts/phases/P25_FAULT_WORKLOAD_IMPACT_ANALYSIS/workload_impact_cross_stage.json` sha256 `a503f3dfcc4bb839f34103851d76595711102a9cad5166e15d2cda64a010f011`
