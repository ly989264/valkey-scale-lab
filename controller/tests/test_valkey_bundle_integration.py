from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = REPOSITORY_ROOT / "project"
INTEGRATION_ROOT = REPOSITORY_ROOT / "controller/integrations/valkey-scale-lab"


def _compiler():
    path = INTEGRATION_ROOT / "compile_contract.py"
    spec = importlib.util.spec_from_file_location("repository_valkey_compiler", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_vpro2_draft_uses_project_definitions_without_copying_control_policy_back() -> None:
    compiler = _compiler()
    source = json.loads((PROJECT_ROOT / "milestones/m1/milestone.json").read_text())
    draft = compiler.compile_contract("m1")
    assert [row["id"] for row in draft["success_conditions"]] == [
        row["id"] for row in source["success_conditions"]
    ]
    assert draft["resource_budget"]
    assert "resource_budget" not in source
    assert all("argv" not in row for row in source["evidence_gates"])


def test_project_milestone_states_are_ready_then_explicitly_blocked() -> None:
    expected = {"m1": "READY", "m2": "BLOCKED", "m3": "BLOCKED"}
    for milestone_id, status in expected.items():
        completed = subprocess.run(
            [sys.executable, "verification/run.py", "milestone", "validate", "--id", milestone_id],
            cwd=PROJECT_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        assert completed.returncode == (0 if status == "READY" else 2)
        assert json.loads(completed.stdout)["status"] == status


def test_planned_suite_fails_closed_instead_of_running_a_placeholder() -> None:
    completed = subprocess.run(
        [sys.executable, "verification/run.py", "suite", "--id", "distributed.runtime.parity"],
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["status"] == "BLOCKED"


def test_independent_evaluator_does_not_import_the_product_package() -> None:
    for path in (INTEGRATION_ROOT / "evaluators").glob("*.py"):
        assert "import valkey_scale_lab" not in path.read_text(encoding="utf-8")
        assert "from valkey_scale_lab" not in path.read_text(encoding="utf-8")
