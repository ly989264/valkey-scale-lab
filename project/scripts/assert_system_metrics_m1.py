#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REQUIRED_PROCESS = {
    "process_pid",
    "process_uptime",
    "cpu_user_percent",
    "cpu_system_percent",
    "rss_bytes",
    "vms_bytes",
    "fd_count",
    "thread_count",
    "tcp_connection_count",
    "client_connection_count",
    "restart_count",
    "log_error_count",
}
REQUIRED_NETWORK = {
    "rx_bytes",
    "tx_bytes",
    "rx_packets",
    "tx_packets",
    "tcp_retransmits",
    "cluster_bus_connections",
}
REQUIRED_VALKEY = {
    "connected_clients",
    "blocked_clients",
    "used_memory",
    "used_memory_rss",
    "mem_fragmentation_ratio",
    "instantaneous_ops_per_sec",
    "total_commands_processed",
    "total_net_input_bytes",
    "total_net_output_bytes",
    "rejected_connections",
    "expired_keys",
    "evicted_keys",
    "keyspace_hits",
    "keyspace_misses",
    "master_repl_offset",
    "slave_repl_offset",
    "replication_lag",
    "cluster_state",
    "cluster_known_nodes",
    "cluster_slots_assigned",
    "cluster_slots_ok",
    "cluster_slots_fail",
}
REQUIRED = REQUIRED_PROCESS | REQUIRED_NETWORK | REQUIRED_VALKEY


def main() -> int:
    parser = argparse.ArgumentParser(description="Assert M1-S07 system metrics artifact coverage.")
    parser.add_argument("--artifacts-dir", action="append", required=True, help="Artifact directory containing system_metrics_timeseries.jsonl.")
    parser.add_argument("--require-report", action="store_true", help="Require rendered report files to contain system resource sections.")
    args = parser.parse_args()
    failures: list[str] = []
    checked = 0
    for raw_dir in args.artifacts_dir:
        directory = Path(raw_dir)
        rows = _read_rows(directory / "system_metrics_timeseries.jsonl")
        report = _read_json(directory / "system_metrics_report.json")
        if not rows:
            failures.append(f"{directory}: system_metrics_timeseries.jsonl is empty or absent")
            continue
        checked += 1
        metric_names = {str(row.get("metric_name")) for row in rows}
        missing_required = sorted(REQUIRED - metric_names)
        if missing_required:
            failures.append(f"{directory}: missing required system metric rows: {', '.join(missing_required)}")
        node_ids = {
            str((row.get("labels", {}) if isinstance(row.get("labels"), dict) else {}).get("logical_node_id", row.get("source_id", "")))
            for row in rows
        }
        if not node_ids or "MISSING" in node_ids or "" in node_ids:
            failures.append(f"{directory}: every row must carry logical_node_id/source_id")
        windows = {
            str((row.get("labels", {}) if isinstance(row.get("labels"), dict) else {}).get("lifecycle_window", ""))
            for row in rows
        }
        if not windows or "" in windows:
            failures.append(f"{directory}: every row must carry lifecycle_window")
        missing_rows = [row for row in rows if row.get("metric_value") == "MISSING"]
        missing_without_reason = [row.get("metric_name", "MISSING") for row in missing_rows if not row.get("missing_reason")]
        if missing_without_reason:
            failures.append(f"{directory}: MISSING rows lack reasons: {', '.join(str(item) for item in missing_without_reason[:10])}")
        coverage = report.get("coverage", {}) if isinstance(report, dict) else {}
        if not coverage.get("rows_by_window") or not coverage.get("rows_by_node"):
            failures.append(f"{directory}: system_metrics_report lacks rows_by_window/rows_by_node aggregation")
        if args.require_report:
            _assert_rendered_report(directory, failures)
    if checked == 0:
        failures.append("no system metrics artifact directories were checked")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print(f"PASS: checked {checked} system metrics artifact director{'y' if checked == 1 else 'ies'}")
    return 0


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _assert_rendered_report(directory: Path, failures: list[str]) -> None:
    html_path = directory / "report" / "index.html"
    md_path = directory / "report" / "report.md"
    if not html_path.exists() or "系统资源趋势" not in html_path.read_text(encoding="utf-8"):
        failures.append(f"{directory}: rendered HTML report does not display 系统资源趋势")
    if not md_path.exists() or "系统异常节点 TopN" not in md_path.read_text(encoding="utf-8"):
        failures.append(f"{directory}: rendered Markdown report does not display 系统异常节点 TopN")


if __name__ == "__main__":
    raise SystemExit(main())
