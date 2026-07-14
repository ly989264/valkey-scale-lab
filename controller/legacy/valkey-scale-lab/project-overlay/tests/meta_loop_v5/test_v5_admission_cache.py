from __future__ import annotations

import json
from pathlib import Path

from valkey_scale_lab.meta_loop_v5.contracts import validate_control_block
from valkey_scale_lab.meta_loop_v5.runner import ProgramRunner


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _check(check_id: str, digest_mode: str, inputs: list[str]) -> dict:
    return {
        "id": check_id,
        "level": 3,
        "command": ["python3", "scripts/meta_m1_real_gate_v5.py", "--mode", digest_mode, "--scale", "50"],
        "timeout_seconds": 20,
        "inputs": inputs,
        "digest_mode": "product_evidence" if digest_mode == "capture" else "admission",
    }


def test_v5_control_contract_is_valid() -> None:
    root = Path(__file__).resolve().parents[2]
    control = json.loads((root / "codex/meta_m1_v5/control_block.json").read_text(encoding="utf-8"))
    validate_control_block(control)


def test_evaluator_upgrade_invalidates_admission_but_not_real_capture(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _write(project / "src/valkey_scale_lab/product.py", "VALUE = 1\n")
    _write(project / "src/valkey_scale_lab/meta_loop_v5/kernel.py", "KERNEL = 1\n")
    _write(project / "scripts/meta_m1_real_gate_v5.py", "raise SystemExit(0)\n")
    evaluator = project / "scripts/meta_m1_evidence_gate.py"
    _write(evaluator, "EVALUATOR = 1\n")
    evidence = tmp_path / "evidence/scale-50/admission.json"
    _write(evidence, "{}\n")
    runner = ProgramRunner(project, tmp_path, tmp_path / "logs", 400)
    evidence_input = "../evidence/scale-50"
    capture = _check("capture", "capture", ["src", "scripts", evidence_input])
    admission = _check("admission", "admit", ["src", "scripts", evidence_input])

    capture_before = runner.check_input_digest(capture)
    admission_before = runner.check_input_digest(admission)
    _write(evaluator, "EVALUATOR = 2\n")

    assert runner.check_input_digest(capture) == capture_before
    assert runner.check_input_digest(admission) != admission_before


def test_v5_kernel_is_not_part_of_product_capture_digest(tmp_path: Path) -> None:
    project = tmp_path / "project"
    kernel = project / "src/valkey_scale_lab/meta_loop_v5/controller.py"
    _write(project / "src/valkey_scale_lab/product.py", "VALUE = 1\n")
    _write(kernel, "KERNEL = 1\n")
    _write(project / "scripts/meta_m1_real_gate_v5.py", "raise SystemExit(0)\n")
    evidence = tmp_path / "evidence/scale-50/admission.json"
    _write(evidence, "{}\n")
    runner = ProgramRunner(project, tmp_path, tmp_path / "logs", 400)
    capture = _check("capture", "capture", ["src", "scripts", "../evidence/scale-50"])
    before = runner.check_input_digest(capture)
    _write(kernel, "KERNEL = 2\n")
    assert runner.check_input_digest(capture) == before
