# C07 Command audit contract

For real management/setup claims, `command_log.jsonl` and `command_audit_summary.json` must satisfy:

- non-empty command log;
- schema-valid rows;
- no placeholder commands such as `["valkey-cli", "cluster", "create_cluster"]` for real claims;
- required command kinds observed where applicable: `cluster_meet`, `cluster_addslots`, `cluster_replicate`, `cluster_probe`, `cleanup`;
- operation traceability from management rows to command ids;
- stdout/stderr refs or hashes exist;
- retry/failure/timeout summaries exist.

An old empty `management_command_log.jsonl` invalidates the corresponding real management claim.
