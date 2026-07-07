from __future__ import annotations

import json
import subprocess
from pathlib import Path

from valkey_scale_lab.observer.failover_timeline import build_rto_summary

PHASE = "P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY"


def write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


def test_fake_schema_timeline_artifacts_validate_but_do_not_claim_real(tmp_path: Path) -> None:
    sample = {
        "schema_version": "v1",
        "phase_id": PHASE,
        "run_id": "fake-run",
        "scenario_name": "fake-schema",
        "sample_id": "fake-schema-sample",
        "status": "FAIL",
        "execution_mode": "fake_schema",
        "real_valkey": False,
        "node_count": 30,
        "scale": "30",
        "fault_apply_at_ms": "MISSING",
        "target_process_gone_at_ms": "MISSING",
        "first_pfail_seen_at_ms": "MISSING",
        "first_fail_seen_at_ms": "MISSING",
        "first_promotion_seen_at_ms": "MISSING",
        "first_slots_covered_at_ms": "MISSING",
        "first_cluster_ok_at_ms": "MISSING",
        "first_client_success_at_ms": "MISSING",
        "clean_snapshot_passed_at_ms": "MISSING",
        "kill_to_pfail_ms": "MISSING",
        "pfail_to_cluster_ok_ms": "MISSING",
        "kill_to_client_recovered_ms": "MISSING",
        "cluster_ok_to_client_success_ms": "MISSING",
        "cluster_ok_to_clean_snapshot_ms": "MISSING",
        "kill_to_clean_snapshot_ms": "MISSING",
        "timeline_source": "fake_schema_unit",
        "client_probe_source": "fake_schema_unit",
        "first_client_success_source": "fake_schema_unit",
        "observer_samples_ref": "observer_samples.jsonl#fake-schema-sample",
        "client_recovery_samples_ref": "client_recovery_samples.jsonl#fake-schema-sample",
    }
    timeline = tmp_path / "failover_timeline_samples.jsonl"
    summary = tmp_path / "failover_rto_summary.json"
    write_jsonl(timeline, [sample])
    write_json(
        summary,
        build_rto_summary(
            [sample],
            phase_id=PHASE,
            run_id="fake-summary",
            timeout_config_ms=30000,
            server_profile="unit_schema",
            nodehost_strategy="unit_schema",
            scale="fake",
        ),
    )

    for schema, instance, extra in [
        ("schemas/artifact/failover_timeline_sample.schema.json", timeline, ["--jsonl"]),
        ("schemas/artifact/failover_rto_summary.schema.json", summary, []),
    ]:
        proc = subprocess.run(
            ["python3", "scripts/validate_json_schema.py", "--schema", schema, "--instance", str(instance), *extra],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr

    proc = subprocess.run(
        [
            "python3",
            "scripts/assert_failover_timeline_completeness.py",
            "--phase",
            PHASE,
            "--artifact-dir",
            str(tmp_path),
            "--require-scales",
            "30,50,100,200",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )

    assert proc.returncode == 1
    assert "real_valkey must be true" in proc.stderr
