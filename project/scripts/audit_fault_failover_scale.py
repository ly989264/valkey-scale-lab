#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = {
    30: {
        "phase_id": "P12_SCALE_LADDER_10_30",
        "scenario": "scale_30_fault_failover",
        "dir": "artifacts/phases/P12_SCALE_LADDER_10_30",
    },
    50: {
        "phase_id": "P13_SCALE_LADDER_50_100",
        "scenario": "scale_50_fault_failover",
        "dir": "artifacts/phases/P13_SCALE_LADDER_50_100",
    },
    100: {
        "phase_id": "P13_SCALE_LADDER_50_100",
        "scenario": "scale_100_fault_failover",
        "dir": "artifacts/phases/P13_SCALE_LADDER_50_100",
    },
}
P14_ID = "P14_SCALE_1000_OPTIN_DRYRUN"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return path.as_posix()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def nested(payload: Any, *keys: str) -> Any:
    current = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


class Auditor:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.findings: list[dict[str, Any]] = []
        self.seq = 0

    def finding(self, *, node_count: int | None, category: str, description: str, evidence: list[str], blocking: bool = True, severity: str = "high") -> None:
        self.seq += 1
        self.findings.append(
            {
                "id": f"L08-FF-{self.seq:04d}",
                "node_count": node_count,
                "category": category,
                "severity": severity,
                "blocking": blocking,
                "description": description,
                "evidence": evidence,
            }
        )

    def source_record(self, role: str, path: Path, payload: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "role": role,
            "path": rel(self.root, path),
            "exists": path.exists(),
            "sha256": sha256_file(path) if path.exists() else "MISSING",
            "artifact_type": payload.get("artifact_type") if isinstance(payload, dict) else "MISSING",
            "status": payload.get("status") if isinstance(payload, dict) else "MISSING",
        }

    def check(self, condition: bool, *, node_count: int, category: str, description: str, evidence: list[str]) -> None:
        if not condition:
            self.finding(node_count=node_count, category=category, description=description, evidence=evidence)

    def metric(self, name: str, *, surface: str, unit: str, source_artifact: Path, pointer: str, value: Any, status: str = "MEASURED", reason: str = "") -> dict[str, Any]:
        if status != "MEASURED" and not reason:
            self.finding(
                node_count=None,
                category="missing_reason_absent",
                description=f"Missing/skipped metric lacks reason: {name}",
                evidence=[rel(self.root, source_artifact)],
            )
        return {
            "name": name,
            "surface": surface,
            "unit": unit,
            "source_artifact": rel(self.root, source_artifact),
            "source_pointer": pointer,
            "status": status,
            "value": value,
            "reason": reason,
        }

    def audit_rung(self, node_count: int) -> dict[str, Any]:
        spec = CANONICAL[node_count]
        base = self.root / spec["dir"]
        paths = {
            "resource_preflight": base / f"resource_preflight_fault_{node_count}.json",
            "fault_report": base / f"fault_report_{node_count}.json",
            "failover_report": base / f"failover_report_{node_count}.json",
            "workload_window_report": base / f"workload_window_report_{node_count}.json",
            "valkey_e2e_evidence": base / f"valkey_e2e_evidence_fault_{node_count}.json",
            "cleanup_report": base / f"cleanup_report_fault_{node_count}.json",
        }
        payloads = {role: load_json(path) for role, path in paths.items()}
        before_count = len(self.findings)
        metrics: list[dict[str, Any]] = []

        for role, path in paths.items():
            if payloads[role] is None:
                self.finding(
                    node_count=node_count,
                    category="missing_l08_artifact",
                    description=f"Missing required L08 {role} artifact for {node_count} nodes",
                    evidence=[rel(self.root, path)],
                )

        preflight = payloads["resource_preflight"] or {}
        self.check(
            preflight.get("status") == "PASS" and preflight.get("can_run") is True,
            node_count=node_count,
            category="resource_preflight_blocked",
            description="Resource preflight must pass before accepting real L08 fault/failover evidence",
            evidence=[rel(self.root, paths["resource_preflight"]), str(preflight.get("status")), str(preflight.get("can_run"))],
        )

        evidence = payloads["valkey_e2e_evidence"] or {}
        versions = evidence.get("valkey_versions") if isinstance(evidence.get("valkey_versions"), list) else []
        self.check(evidence.get("producer", {}).get("name") == "scripts/fault_failover_gate.py", node_count=node_count, category="invalid_real_evidence", description="Evidence producer must be scripts/fault_failover_gate.py", evidence=[rel(self.root, paths["valkey_e2e_evidence"]), str(evidence.get("producer"))])
        self.check(evidence.get("real_valkey") is True, node_count=node_count, category="invalid_real_evidence", description="Evidence must be real Valkey", evidence=[rel(self.root, paths["valkey_e2e_evidence"])])
        self.check(evidence.get("status") == "PASS" and evidence.get("probe_result") == "PASS", node_count=node_count, category="invalid_real_evidence", description="Evidence status and probe_result must PASS", evidence=[rel(self.root, paths["valkey_e2e_evidence"]), str(evidence.get("status")), str(evidence.get("probe_result"))])
        self.check(all(str(v).startswith("9.1.") for v in versions) and bool(versions), node_count=node_count, category="invalid_real_evidence", description="Evidence must contain Valkey 9.1.x versions", evidence=[rel(self.root, paths["valkey_e2e_evidence"]), json.dumps(versions)])
        self.check(evidence.get("nodes_observed_before") == node_count, node_count=node_count, category="invalid_real_evidence", description="Evidence must record exact before-fault node count", evidence=[rel(self.root, paths["valkey_e2e_evidence"]), str(evidence.get("nodes_observed_before"))])
        self.check(evidence.get("nodes_observed") in {node_count, node_count - 1}, node_count=node_count, category="invalid_real_evidence", description="Evidence must record expected after-fault observed nodes", evidence=[rel(self.root, paths["valkey_e2e_evidence"]), str(evidence.get("nodes_observed"))])
        self.check(evidence.get("nodes_observed_after_clear") == node_count, node_count=node_count, category="invalid_real_evidence", description="Evidence must record exact after-clear node count", evidence=[rel(self.root, paths["valkey_e2e_evidence"]), str(evidence.get("nodes_observed_after_clear"))])
        self.check(evidence.get("cluster_state_observed") == "ok", node_count=node_count, category="invalid_real_evidence", description="Recovered cluster state must be ok", evidence=[rel(self.root, paths["valkey_e2e_evidence"]), str(evidence.get("cluster_state_observed"))])
        self.check(evidence.get("data_path_result") == "PASS", node_count=node_count, category="data_path_invalid", description="Evidence must record PASS data-path proof for failed-primary-slot workload", evidence=[rel(self.root, paths["valkey_e2e_evidence"]), str(evidence.get("data_path_result"))])
        self.check(nested(evidence, "cleanup", "status") == "PASS", node_count=node_count, category="cleanup_invalid", description="Evidence cleanup status must PASS", evidence=[rel(self.root, paths["valkey_e2e_evidence"]), str(nested(evidence, "cleanup", "status"))])
        observations = evidence.get("observations") if isinstance(evidence.get("observations"), dict) else {}
        required_observations = {
            "before_fault": {node_count},
            "during_fault": {node_count, node_count - 1},
            "after_promotion": {node_count, node_count - 1},
            "after_clear": {node_count},
        }
        for name, allowed_counts in required_observations.items():
            observation = observations.get(name) if isinstance(observations.get(name), dict) else {}
            self.check(isinstance(observation.get("nodes_observed"), int) and observation.get("nodes_observed") in allowed_counts, node_count=node_count, category="observation_invalid", description=f"Observation {name} must record expected node count", evidence=[rel(self.root, paths["valkey_e2e_evidence"]), name, str(observation.get("nodes_observed"))])
            if name in {"before_fault", "after_promotion", "after_clear"}:
                self.check(observation.get("cluster_state") == "ok", node_count=node_count, category="observation_invalid", description=f"Observation {name} must record cluster_state ok", evidence=[rel(self.root, paths["valkey_e2e_evidence"]), name, str(observation.get("cluster_state"))])

        fault = payloads["fault_report"] or {}
        safety = fault.get("safety_checks") if isinstance(fault.get("safety_checks"), dict) else {}
        self.check(fault.get("status") == "PASS", node_count=node_count, category="fault_report_invalid", description="Fault report must PASS", evidence=[rel(self.root, paths["fault_report"]), str(fault.get("status"))])
        self.check(safety.get("host_network_mutated") is False and safety.get("global_firewall_mutated") is False and safety.get("sandbox_only") is True, node_count=node_count, category="unsafe_fault_scope", description="Fault report safety checks must prove sandbox-only behavior", evidence=[rel(self.root, paths["fault_report"]), json.dumps(safety)])
        first_fault = (fault.get("faults") or [{}])[0] if isinstance(fault.get("faults"), list) else {}
        self.check(isinstance(first_fault.get("fault_apply_latency_ms"), (int, float)), node_count=node_count, category="missing_fault_metric", description="Fault apply latency must be numeric", evidence=[rel(self.root, paths["fault_report"]), str(first_fault.get("fault_apply_latency_ms"))])
        self.check(isinstance(first_fault.get("fault_clear_latency_ms"), (int, float)), node_count=node_count, category="missing_fault_metric", description="Fault clear latency must be numeric", evidence=[rel(self.root, paths["fault_report"]), str(first_fault.get("fault_clear_latency_ms"))])
        self.check(first_fault.get("after_clear_nodes_observed") == node_count, node_count=node_count, category="missing_fault_metric", description="Fault report must record restored after-clear node count", evidence=[rel(self.root, paths["fault_report"]), str(first_fault.get("after_clear_nodes_observed"))])
        self.check(first_fault.get("after_clear_cluster_state") == "ok", node_count=node_count, category="missing_fault_metric", description="Fault report must record after-clear cluster_state ok", evidence=[rel(self.root, paths["fault_report"]), str(first_fault.get("after_clear_cluster_state"))])
        self.check(first_fault.get("scope") in {"owned_container_or_process", "container_namespace_or_sandbox_proxy"}, node_count=node_count, category="unsafe_fault_scope", description="Fault scope must be owned/sandboxed", evidence=[rel(self.root, paths["fault_report"]), str(first_fault.get("scope"))])

        failover = payloads["failover_report"] or {}
        summary = failover.get("summary") if isinstance(failover.get("summary"), dict) else {}
        first_failover = (failover.get("failovers") or [{}])[0] if isinstance(failover.get("failovers"), list) else {}
        self.check(failover.get("status") == "PASS", node_count=node_count, category="failover_report_invalid", description="Failover report must PASS", evidence=[rel(self.root, paths["failover_report"]), str(failover.get("status"))])
        self.check(summary.get("promotion_observed") is True, node_count=node_count, category="promotion_missing", description="Promotion must be observed", evidence=[rel(self.root, paths["failover_report"]), str(summary.get("promotion_observed"))])
        self.check(isinstance(first_failover.get("failover_latency_ms"), (int, float)), node_count=node_count, category="missing_failover_metric", description="Failover latency must be numeric", evidence=[rel(self.root, paths["failover_report"]), str(first_failover.get("failover_latency_ms"))])
        split = summary.get("split_brain_duration_ms")
        split_ok = isinstance(split, (int, float)) or (isinstance(split, dict) and split.get("status") == "MISSING" and bool(split.get("reason")))
        self.check(split_ok, node_count=node_count, category="split_brain_invalid", description="Split-brain duration must be measured or explicit MISSING with reason", evidence=[rel(self.root, paths["failover_report"]), json.dumps(split)])

        workload = payloads["workload_window_report"] or {}
        windows = workload.get("windows") if isinstance(workload.get("windows"), list) else []
        names = {window.get("name") for window in windows if isinstance(window, dict)}
        selected_logical = evidence.get("selected_primary_logical_id")
        self.check(workload.get("status") == "PASS", node_count=node_count, category="workload_window_invalid", description="Workload window report must PASS", evidence=[rel(self.root, paths["workload_window_report"]), str(workload.get("status"))])
        self.check({"before_fault", "during_fault", "after_recovery"}.issubset(names), node_count=node_count, category="workload_window_invalid", description="Workload report must include before/during/after windows", evidence=[rel(self.root, paths["workload_window_report"]), json.dumps(sorted(names))])
        for idx, window in enumerate(windows):
            if not isinstance(window, dict):
                continue
            status = window.get("status", "MEASURED")
            reason = window.get("reason", "")
            self.check(status == "MEASURED", node_count=node_count, category="workload_window_not_measured", description="PASS L08 workload windows must be measured SET/GET workload operations", evidence=[rel(self.root, paths["workload_window_report"]), str(window.get("name")), str(status)])
            self.check(status == "MEASURED" or bool(reason), node_count=node_count, category="missing_reason_absent", description="Skipped/missing workload windows require reason", evidence=[rel(self.root, paths["workload_window_report"]), str(window.get("name"))])
            self.check(window.get("workload_scope") == "failed_primary_slot", node_count=node_count, category="workload_window_invalid", description="Workload window must target the selected failed primary's slot range", evidence=[rel(self.root, paths["workload_window_report"]), str(window.get("name")), str(window.get("workload_scope"))])
            self.check(window.get("source_logical_id") == selected_logical, node_count=node_count, category="workload_window_invalid", description="Workload source logical id must match selected failed primary", evidence=[rel(self.root, paths["workload_window_report"]), str(window.get("name")), str(window.get("source_logical_id")), str(selected_logical)])
            for key in ["operation_count", "availability_percent", "errors_total", "timeouts_total"]:
                self.check(isinstance(window.get(key), (int, float)), node_count=node_count, category="workload_window_invalid", description=f"Workload window {key} must be numeric", evidence=[rel(self.root, paths["workload_window_report"]), f"window={window.get('name')}", str(window.get(key))])
            self.check(isinstance(window.get("operation_count"), int) and window.get("operation_count") > 0, node_count=node_count, category="workload_window_invalid", description="Measured workload window must record at least one attempted operation", evidence=[rel(self.root, paths["workload_window_report"]), f"window={window.get('name')}", str(window.get("operation_count"))])
            if window.get("name") in {"before_fault", "after_recovery"}:
                self.check(isinstance(window.get("roundtrip_successes"), int) and window.get("roundtrip_successes") > 0, node_count=node_count, category="workload_window_invalid", description="Before/after workload windows must prove at least one SET/GET round trip", evidence=[rel(self.root, paths["workload_window_report"]), f"window={window.get('name')}", str(window.get("roundtrip_successes"))])
            for key, unit in [("availability_percent", "percent"), ("errors_total", "count"), ("timeouts_total", "count"), ("operation_count", "count")]:
                metrics.append(self.metric(f"workload.{window.get('name')}.{key}", surface="workload", unit=unit, source_artifact=paths["workload_window_report"], pointer=f"$.windows.{idx}.{key}", value=window.get(key), status="MEASURED" if status == "MEASURED" else status, reason=reason))

        cleanup = payloads["cleanup_report"] or {}
        remaining = cleanup.get("resources_remaining")
        self.check(cleanup.get("status") == "PASS", node_count=node_count, category="cleanup_invalid", description="Cleanup report must PASS", evidence=[rel(self.root, paths["cleanup_report"]), str(cleanup.get("status"))])
        self.check(remaining == [], node_count=node_count, category="cleanup_residue", description="Cleanup residual resources must be empty", evidence=[rel(self.root, paths["cleanup_report"]), json.dumps(remaining)])

        metrics.extend(
            [
                self.metric("fault.apply_latency_ms", surface="fault", unit="ms", source_artifact=paths["fault_report"], pointer="$.faults.0.fault_apply_latency_ms", value=first_fault.get("fault_apply_latency_ms")),
                self.metric("fault.clear_latency_ms", surface="fault", unit="ms", source_artifact=paths["fault_report"], pointer="$.faults.0.fault_clear_latency_ms", value=first_fault.get("fault_clear_latency_ms")),
                self.metric("fault.cleanup_residual_count", surface="cleanup", unit="count", source_artifact=paths["cleanup_report"], pointer="$.resources_remaining", value=len(remaining) if isinstance(remaining, list) else None, status="MEASURED" if isinstance(remaining, list) else "MISSING", reason="" if isinstance(remaining, list) else "cleanup_report lacks resources_remaining"),
                self.metric("failover.promotion_observed", surface="failover", unit="boolean", source_artifact=paths["failover_report"], pointer="$.summary.promotion_observed", value=summary.get("promotion_observed")),
                self.metric("failover.failover_latency_ms", surface="failover", unit="ms", source_artifact=paths["failover_report"], pointer="$.failovers.0.failover_latency_ms", value=first_failover.get("failover_latency_ms")),
                self.metric("failover.nodes_observed_before", surface="failover", unit="nodes", source_artifact=paths["valkey_e2e_evidence"], pointer="$.nodes_observed_before", value=evidence.get("nodes_observed_before")),
                self.metric("failover.nodes_observed_after", surface="failover", unit="nodes", source_artifact=paths["valkey_e2e_evidence"], pointer="$.nodes_observed", value=evidence.get("nodes_observed")),
                self.metric("failover.nodes_observed_after_clear", surface="failover", unit="nodes", source_artifact=paths["valkey_e2e_evidence"], pointer="$.nodes_observed_after_clear", value=evidence.get("nodes_observed_after_clear")),
            ]
        )
        if isinstance(split, dict):
            metrics.append(self.metric("failover.split_brain_duration_ms", surface="failover", unit="ms", source_artifact=paths["failover_report"], pointer="$.summary.split_brain_duration_ms", value=split.get("value"), status=split.get("status", "MISSING"), reason=split.get("reason", "")))
        else:
            metrics.append(self.metric("failover.split_brain_duration_ms", surface="failover", unit="ms", source_artifact=paths["failover_report"], pointer="$.summary.split_brain_duration_ms", value=split))

        rung_findings = self.findings[before_count:]
        return {
            "node_count": node_count,
            "phase_id": spec["phase_id"],
            "scenario": spec["scenario"],
            "status": "PASS" if not any(f["blocking"] for f in rung_findings) else "FAIL",
            "real_valkey": payloads["valkey_e2e_evidence"] is not None and evidence.get("real_valkey") is True and not any(f["blocking"] for f in rung_findings),
            "source_artifacts": [self.source_record(role, path, payloads[role]) for role, path in paths.items()],
            "metric_records": metrics,
            "findings": rung_findings,
        }

    def audit_p14(self) -> dict[str, Any]:
        p14_dir = self.root / "artifacts" / "phases" / P14_ID
        real_count = 0
        if p14_dir.exists():
            for path in p14_dir.glob("*.json"):
                payload = load_json(path) or {}
                artifact_type = payload.get("artifact_type")
                fault_failover_artifact = artifact_type in {
                    "fault_report",
                    "failover_report",
                    "workload_window_report",
                    "valkey_e2e_evidence",
                } or path.name in {
                    "fault_report_1000.json",
                    "failover_report_1000.json",
                    "workload_window_report_1000.json",
                    "valkey_e2e_evidence_fault_1000.json",
                }
                if fault_failover_artifact and (payload.get("real_valkey") is True or payload.get("node_count") == 1000 or "1000" in path.name):
                    real_count += 1
                    self.finding(node_count=1000, category="p14_real_fault_failover_forbidden", description="P14/1000 real fault/failover evidence is forbidden in L08", evidence=[rel(self.root, path)])
        return {
            "phase_id": P14_ID,
            "status": "SKIPPED_WITH_REASON" if real_count == 0 else "FAIL",
            "dry_run_only": True,
            "real_valkey_coverage": False,
            "real_evidence_count": real_count,
            "reason": "P14 remains opt-in dry-run/resource/planner only and L08 did not run 1000-node fault/failover gates.",
        }

    def build(self) -> dict[str, Any]:
        rungs = [self.audit_rung(node_count) for node_count in [30, 50, 100]]
        p14 = self.audit_p14()
        blocking = [finding for finding in self.findings if finding["blocking"]]
        metrics = [record for rung in rungs for record in rung["metric_records"]]
        return {
            "schema_version": "v1",
            "artifact_type": "fault_failover_scale",
            "created_at": utc_now(),
            "producer": {"name": "scripts/audit_fault_failover_scale.py", "version": "v1"},
            "status": "PASS" if not blocking else "FAIL",
            "summary": {
                "canonical_node_counts": [30, 50, 100],
                "rung_count": len(rungs),
                "blocking_findings_count": len(blocking),
                "real_valkey_rung_count": sum(1 for rung in rungs if rung["real_valkey"] is True),
                "measured_metric_count": sum(1 for metric in metrics if metric["status"] == "MEASURED"),
                "missing_metric_count": sum(1 for metric in metrics if metric["status"] in {"MISSING", "SKIPPED_WITH_REASON"}),
            },
            "canonical_rungs": rungs,
            "p14_boundary": p14,
            "findings": self.findings,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit L08 30/50/100 fault/failover scale artifacts")
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    auditor = Auditor(root)
    report = auditor.build()
    out = Path(args.out)
    if not out.is_absolute():
        out = root / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    if report["status"] != "PASS":
        print(f"FAIL fault_failover_scale blocking_findings={report['summary']['blocking_findings_count']} out={rel(root, out)}", file=sys.stderr)
        return 1
    print(f"PASS fault_failover_scale {rel(root, out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
