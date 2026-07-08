#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema_validator import load_json, validate  # noqa: E402

REQUIRED_KINDS = {"cluster_meet", "cluster_addslots", "cluster_replicate", "cluster_probe", "cleanup"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts-dir")
    parser.add_argument("--analysis")
    parser.add_argument("--report-index")
    parser.add_argument("--fixtures")
    args = parser.parse_args()
    errors: list[str] = []
    schema = load_json(Path("schemas/artifact/command_log_entry.schema.json"))
    summary_schema = load_json(Path("schemas/artifact/command_audit_summary.schema.json"))
    if args.fixtures:
        errors.extend(_check_fixtures(Path(args.fixtures), schema, summary_schema))
    if args.artifacts_dir:
        errors.extend(_check_artifacts(Path(args.artifacts_dir), schema, summary_schema, Path(args.analysis) if args.analysis else None, Path(args.report_index) if args.report_index else None))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("PASS command log schema/nonempty/analysis/report coverage")
    return 0


def _load_jsonl(path: Path, schema: dict, *, allow_empty: bool = False) -> tuple[list[dict], list[str]]:
    errors: list[str] = []
    if not path.exists():
        return [], [f"{path}: missing command_log.jsonl"]
    rows: list[dict] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{path}:{lineno}: invalid JSON: {exc}")
            continue
        if not isinstance(row, dict):
            errors.append(f"{path}:{lineno}: row is not object")
            continue
        errors.extend(f"{path}:{lineno}: {err}" for err in validate(row, schema))
        rows.append(row)
    if not rows and not allow_empty:
        errors.append(f"{path}: command_log.jsonl is empty")
    return rows, errors


def _check_summary(path: Path, schema: dict) -> list[str]:
    if not path.exists():
        return [f"{path}: missing command_audit_summary.json"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{path}: invalid JSON: {exc}"]
    return [f"{path}: {err}" for err in validate(data, schema)]


def _load_summary(path: Path, schema: dict) -> tuple[dict, list[str]]:
    if not path.exists():
        return {}, [f"{path}: missing command_audit_summary.json"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {}, [f"{path}: invalid JSON: {exc}"]
    if not isinstance(data, dict):
        return {}, [f"{path}: summary is not object"]
    return data, [f"{path}: {err}" for err in validate(data, schema)]


def _check_fixtures(root: Path, schema: dict, summary_schema: dict) -> list[str]:
    errors: list[str] = []
    expected = {"success", "failure", "timeout", "retry", "cleanup_residual", "empty"}
    missing = sorted(name for name in expected if not (root / name).exists())
    errors.extend(f"{root}: missing fixture directory {name}" for name in missing)
    for name in sorted(expected - {"empty"}):
        rows, row_errors = _load_jsonl(root / name / "command_log.jsonl", schema)
        errors.extend(row_errors)
        if rows and name == "success":
            kinds = {str(row.get("command_kind")) for row in rows}
            absent = sorted(REQUIRED_KINDS - kinds)
            errors.extend(f"{root/name}: missing required command kinds {absent}" for _ in absent[:1])
        if rows and name == "failure" and not any(row.get("status") == "FAIL" for row in rows):
            errors.append(f"{root/name}: failure fixture lacks FAIL row")
        if rows and name == "timeout" and not any(row.get("status") == "TIMEOUT" for row in rows):
            errors.append(f"{root/name}: timeout fixture lacks TIMEOUT row")
        if rows and name == "retry" and not any(int(row.get("retry_index", 0) or 0) > 0 or row.get("status") == "RETRY" for row in rows):
            errors.append(f"{root/name}: retry fixture lacks retry row")
        summary_path = root / name / "command_audit_summary.json"
        if summary_path.exists():
            summary, summary_errors = _load_summary(summary_path, summary_schema)
            errors.extend(summary_errors)
            if rows:
                errors.extend(_check_summary_consistency(summary_path, summary, rows))
    empty_rows, empty_errors = _load_jsonl(root / "empty" / "command_log.jsonl", schema)
    if empty_rows:
        errors.append(f"{root/'empty'}: empty fixture unexpectedly contains rows")
    if not any("command_log.jsonl is empty" in error for error in empty_errors):
        errors.append(f"{root/'empty'}: empty command log fixture was not rejected by nonempty check")
    return errors


def _check_artifacts(artifacts_dir: Path, schema: dict, summary_schema: dict, analysis_path: Path | None, report_index_path: Path | None) -> list[str]:
    errors: list[str] = []
    blocked = artifacts_dir / "goal_loop" / "M1-S03" / "real_heavy_gate_blocked.json"
    if blocked.exists():
        blocked_data = json.loads(blocked.read_text(encoding="utf-8"))
        if blocked_data.get("status") != "BLOCKED_WITH_REASON":
            errors.append(f"{blocked}: blocked real gate must use BLOCKED_WITH_REASON")
    rows, row_errors = _load_jsonl(artifacts_dir / "command_log.jsonl", schema)
    errors.extend(row_errors)
    summary, summary_errors = _load_summary(artifacts_dir / "command_audit_summary.json", summary_schema)
    errors.extend(summary_errors)
    if rows:
        command_ids = {str(row.get("command_id")) for row in rows}
        statuses = {str(row.get("status")) for row in rows}
        if "PASS" not in statuses:
            errors.append(f"{artifacts_dir}: command log has no PASS rows")
        kinds = {str(row.get("command_kind")) for row in rows}
        absent = sorted(REQUIRED_KINDS - kinds)
        if absent:
            errors.append(f"{artifacts_dir}: missing required command kinds {absent}")
        for row in rows:
            for ref in row.get("trace_refs", []):
                if isinstance(ref, str) and ref.startswith("command_log.jsonl#") and ref.split("#", 1)[1] not in command_ids:
                    errors.append(f"{artifacts_dir}: row {row.get('command_id')} references missing command id {ref}")
        if summary:
            errors.extend(_check_summary_consistency(artifacts_dir / "command_audit_summary.json", summary, rows))
    if analysis_path:
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        audit = analysis.get("command_audit", {})
        if not isinstance(audit, dict) or int(audit.get("total_commands", 0) or 0) <= 0:
            errors.append(f"{analysis_path}: analysis command_audit missing or empty")
    if report_index_path:
        report_index = json.loads(report_index_path.read_text(encoding="utf-8"))
        if "command_audit_report_inputs" not in report_index:
            errors.append(f"{report_index_path}: missing command_audit_report_inputs")
        report_dir = report_index_path.parent
        if not (report_dir / "report.md").exists():
            report_dir = report_index_path.parent / "reports"
        markdown = (report_dir / "report.md").read_text(encoding="utf-8")
        html = (report_dir / "index.html").read_text(encoding="utf-8")
        for heading in ["慢命令 TopN", "失败命令", "重试命令", "命令审计覆盖"]:
            if heading not in markdown or heading not in html:
                errors.append(f"{report_index_path}: report missing Chinese heading {heading}")
    return errors


def _check_summary_consistency(path: Path, summary: dict, rows: list[dict]) -> list[str]:
    errors: list[str] = []
    if int(summary.get("total_commands", -1)) != len(rows):
        errors.append(f"{path}: total_commands does not match command_log row count")
    if int(summary.get("pass_count", -1)) != sum(1 for row in rows if row.get("status") == "PASS"):
        errors.append(f"{path}: pass_count does not match command_log")
    if int(summary.get("failure_count", -1)) != sum(1 for row in rows if row.get("status") == "FAIL"):
        errors.append(f"{path}: failure_count does not match command_log")
    if int(summary.get("timeout_count", -1)) != sum(1 for row in rows if row.get("status") == "TIMEOUT"):
        errors.append(f"{path}: timeout_count does not match command_log")
    if rows and not summary.get("slowest_commands_topN"):
        errors.append(f"{path}: slowest_commands_topN must be non-empty when commands exist")
    command_ids = {str(row.get("command_id")) for row in rows}
    traced_ids: set[str] = set()
    for item in summary.get("operation_traceability", []):
        if not isinstance(item, dict):
            continue
        for ref in item.get("command_log_refs", []):
            if isinstance(ref, str) and ref.startswith("command_log.jsonl#"):
                traced_ids.add(ref.split("#", 1)[1])
    missing_refs = sorted(command_ids - traced_ids)
    if missing_refs:
        errors.append(f"{path}: operation_traceability missing command refs {missing_refs[:5]}")
    return errors


if __name__ == "__main__":
    raise SystemExit(main())
