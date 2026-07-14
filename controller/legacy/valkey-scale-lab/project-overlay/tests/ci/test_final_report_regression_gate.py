from __future__ import annotations

import json
from pathlib import Path


def test_p26_manifest_generates_final_report_before_assertions() -> None:
    manifest = json.loads(Path("codex/phase_manifest.json").read_text(encoding="utf-8"))
    phase = next(item for item in manifest["phases"] if item["id"] == "P26_FINAL_REPORT_REGRESSION")
    names = [gate["name"] for gate in phase["gates"]]

    assert names.index("real_valkey_e2e") < names.index("p26_final_report_generation")
    assert names.index("p26_final_report_generation") < names.index("quant_artifact_assertion")
    assert names.index("quant_artifact_assertion") < names.index("final_report_regression_assertion")
    assert names.index("final_report_regression_assertion") < names.index("cleanup_report_check")
    generation_command = phase["gates"][names.index("p26_final_report_generation")]["command"]
    assertion_command = phase["gates"][names.index("final_report_regression_assertion")]["command"]
    assert "--kind final-goal-loop" in generation_command
    assert "scripts/assert_final_report_regression.py" in assertion_command


def test_p26_manifest_declares_final_report_indexes() -> None:
    manifest = json.loads(Path("codex/phase_manifest.json").read_text(encoding="utf-8"))
    phase = next(item for item in manifest["phases"] if item["id"] == "P26_FINAL_REPORT_REGRESSION")
    artifacts = {item["path"]: item["schema"] for item in phase["required_artifacts"]}

    assert artifacts["artifacts/phases/P26_FINAL_REPORT_REGRESSION/final_report_index.json"] == "schemas/artifact/final_report_index.schema.json"
    assert artifacts["artifacts/phases/P26_FINAL_REPORT_REGRESSION/report_index.json"] == "schemas/artifact/final_report_index.schema.json"
    assert artifacts["artifacts/phases/P26_FINAL_REPORT_REGRESSION/csv_export_index.json"] == "schemas/artifact/csv_export_index.schema.json"
