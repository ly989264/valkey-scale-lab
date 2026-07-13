#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "src"
EVALUATOR_PATHS = {
    1: PROJECT_ROOT / "evaluators/vpro/milestone1_evidence_policy.py",
    2: PROJECT_ROOT / "evaluators/vpro/milestone2_evidence_policy.py",
    3: PROJECT_ROOT / "evaluators/vpro/milestone3_evidence_policy.py",
}
PREFLIGHT_PATHS = {
    2: PROJECT_ROOT / "checks/vpro/milestone2_preflight.py",
    3: PROJECT_ROOT / "checks/vpro/milestone3_preflight.py",
}
PREREQUISITE_VERIFIER_PATHS = {
    2: PROJECT_ROOT / "checks/vpro/milestone2_prerequisite.py",
    3: PROJECT_ROOT / "checks/vpro/milestone3_prerequisite.py",
}
SAFETY_PATTERNS = (
    (re.compile(r"\bsudo\b"), "sudo is forbidden as a default path"),
    (re.compile(r"\bpfctl\b"), "host PF mutation is forbidden"),
    (re.compile(r"\biptables\b"), "host iptables mutation is forbidden"),
    (re.compile(r"\bnft\b"), "host nftables mutation is forbidden"),
    (re.compile(r"\bip\s+route\b"), "host route mutation is forbidden"),
    (re.compile(r"\broute\s+(add|delete|del)\b"), "host route mutation is forbidden"),
    (re.compile(r"\bifconfig\b"), "host interface mutation is forbidden"),
    (re.compile(r"\bnetworksetup\b"), "macOS global network mutation is forbidden"),
    (re.compile(r"\bkillall\b"), "broad process killing is forbidden"),
    (re.compile(r"\bpkill\s+-f\b"), "broad process killing is forbidden"),
)
SAFETY_SCAN_DIRS = ("src", "tests", "scripts", "templates/configs")
SAFETY_SCAN_FILES = ("pyproject.toml", "requirements-dev.txt")
SAFETY_SCAN_EXCLUDED_PREFIXES = (
    "src/valkey_scale_lab/vpro",
    "tests/vpro",
    "tests/vpro_milestones",
)
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

SUITES = {
    "m1-evaluator-policy": ("tests/vpro_milestones/test_milestone1_evidence_policy.py",),
    "m2-evaluator-policy": ("tests/vpro_milestones/test_milestone2_evidence_policy.py",),
    "m3-evaluator-policy": ("tests/vpro_milestones/test_milestone3_evidence_policy.py",),
    "m1-scenario": ("tests/scenarios",),
    "m1-runtime": (
        "tests/gates",
        "tests/integration/test_gate_orchestration.py",
        "tests/real_valkey/test_gate_small_real_parity.py",
        "tests/vpro_milestones/test_milestone1_sandbox_network_proxy.py",
    ),
    "m1-evidence": (
        "tests/evidence",
        "tests/provenance/test_evidence_pipeline_v9.py",
        "tests/provenance/test_meta_m1_evidence_gate_v9.py",
    ),
    "m1-report": ("tests/analysis", "tests/report"),
    "m1-compatibility": (
        "tests/cli",
        "tests/config",
        "tests/planner",
        "tests/scale",
        "tests/fault/test_owned_runtime_guard_gap.py",
        "tests/fault/test_sandbox_fault.py",
    ),
    "m2-runtime-parity": ("tests/milestone2/test_runtime_parity.py",),
    "m2-inventory-placement": ("tests/milestone2/test_inventory_placement.py",),
    "m2-native-process-journal": ("tests/milestone2/test_native_process_journal.py",),
    "m2-lifecycle-safety": ("tests/milestone2/test_distributed_lifecycle_safety.py",),
    "m2-clocked-evidence": ("tests/milestone2/test_clocked_evidence.py",),
    "m2-analysis-cost": ("tests/milestone2/test_analysis_cost_teardown.py",),
    "m3-profiles-preflight": ("tests/milestone3/test_profiles_preflight.py",),
    "m3-scalable-orchestration": ("tests/milestone3/test_scalable_orchestration.py",),
    "m3-telemetry-transfer": ("tests/milestone3/test_telemetry_transfer.py",),
    "m3-hierarchical-safety": ("tests/milestone3/test_hierarchical_safety.py",),
    "m3-comparison-report": ("tests/milestone3/test_comparison_report.py",),
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Authoritative VPRO milestone check adapter")
    commands = parser.add_subparsers(dest="command", required=True)
    suite = commands.add_parser("suite")
    suite.add_argument("--id", required=True, choices=sorted(SUITES))
    commands.add_parser("static-safety")
    commands.add_parser("closure")
    guard = commands.add_parser("evaluator-guard")
    guard.add_argument("--milestone", type=int, required=True, choices=(1, 2, 3))
    prerequisite = commands.add_parser("prerequisite")
    prerequisite.add_argument("--milestone", type=int, required=True, choices=(1, 2, 3))
    prerequisite.add_argument("--receipt", required=True)
    preflight = commands.add_parser("preflight")
    preflight.add_argument("--milestone", type=int, required=True, choices=(1, 2, 3))
    preflight.add_argument("--scale", type=int, required=True)
    preflight.add_argument("--prior")
    preflight.add_argument("--prerequisite")
    capture = commands.add_parser("capture")
    capture.add_argument("--milestone", type=int, required=True, choices=(1, 2, 3))
    capture.add_argument("--scale", type=int, required=True)
    capture.add_argument("--output", required=True)
    capture.add_argument("--prior")
    capture.add_argument("--prerequisite")
    admission = commands.add_parser("admission")
    admission.add_argument("--milestone", type=int, required=True, choices=(1, 2, 3))
    admission.add_argument("--scale", type=int, required=True)
    admission.add_argument("--capture", required=True)
    admission.add_argument("--output", required=True)
    admission.add_argument("--prior")
    admission.add_argument("--prerequisite")
    product_cli = commands.add_parser("product-cli", help=argparse.SUPPRESS)
    product_cli.add_argument("arguments", nargs=argparse.REMAINDER)
    return parser


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    return env


def _run(command: list[str]) -> int:
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=_child_env(),
        check=False,
    )
    return completed.returncode


def _suite(suite_id: str) -> int:
    paths = SUITES[suite_id]
    missing = [path for path in paths if not (PROJECT_ROOT / path).exists()]
    if missing:
        print(f"BLOCKED: externally authored acceptance paths are missing: {missing}")
        return 2
    return _pytest(*paths)


def _closure() -> int:
    return _pytest(
        "--ignore=tests/real_valkey",
        "--ignore=tests/fault/test_network_proxy.py",
        "--ignore=tests/vpro",
        "--ignore=tests/vpro_milestones",
        "--ignore=tests/meta_loop_v7/test_o1_retry_budget_gap.py",
        "--deselect=tests/meta_loop_v8/test_contract.py::test_v8_kernel_manifest_seals_v7_reproduction_and_v8_successor",
        "tests",
    )


def _pytest(*arguments: str) -> int:
    tests_root = PROJECT_ROOT / "tests"
    try:
        sealed_tools = json.loads(os.environ.get("VPRO_SEALED_TOOLS_JSON", ""))
    except json.JSONDecodeError:
        sealed_tools = None
    pytest_path = sealed_tools.get("pytest") if isinstance(sealed_tools, Mapping) else None
    pytest_executable = Path(pytest_path) if isinstance(pytest_path, str) else None
    if (
        pytest_executable is None
        or not pytest_executable.is_absolute()
        or not pytest_executable.is_file()
        or not os.access(pytest_executable, os.X_OK)
    ):
        print("BLOCKED: sealed pytest executable is unavailable")
        return 2
    temporary_parent = Path(os.environ.get("TMPDIR", tempfile.gettempdir())).resolve()
    report_root = Path(tempfile.mkdtemp(prefix="vpro-pytest-", dir=temporary_parent))
    report_path = report_root / "report.xml"
    try:
        returncode = _run(
            [
                str(pytest_executable),
                "-q",
                "-p",
                "no:cacheprovider",
                "-c",
                os.devnull,
                "--rootdir",
                str(tests_root),
                "--confcutdir",
                str(tests_root),
                "--import-mode=importlib",
                "-o",
                f"pythonpath={SOURCE_ROOT}",
                f"--junitxml={report_path}",
                *arguments,
            ]
        )
        if returncode != 0:
            return returncode
        try:
            report = ET.parse(report_path)
        except (OSError, ET.ParseError) as exc:
            print(f"FAIL: authoritative pytest report is unavailable: {exc}")
            return 1
        skipped = len(report.findall(".//testcase/skipped"))
        if skipped:
            print(f"FAIL: authoritative acceptance skipped {skipped} required test(s)")
            return 1
        return 0
    finally:
        shutil.rmtree(report_root, ignore_errors=True)


def _run_product_cli(arguments: list[str]) -> int:
    return _run(
        [
            sys.executable,
            "-I",
            "-B",
            str(Path(__file__).resolve()),
            "product-cli",
            *arguments,
        ]
    )


def _static_safety() -> int:
    errors: list[str] = []
    extensions = {".py", ".sh", ".bash", ".yaml", ".yml", ".toml", ".json", ".ini", ".cfg", ""}
    for directory in SAFETY_SCAN_DIRS:
        base = PROJECT_ROOT / directory
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(PROJECT_ROOT).as_posix()
            if (
                relative == "scripts/safety_scan.py"
                or "__pycache__" in path.parts
                or any(
                    relative == prefix or relative.startswith(prefix + "/")
                    for prefix in SAFETY_SCAN_EXCLUDED_PREFIXES
                )
            ):
                continue
            if path.suffix not in extensions and path.name not in {"Dockerfile", "Makefile"}:
                continue
            errors.extend(_scan_safety_text(path))
    for name in SAFETY_SCAN_FILES:
        path = PROJECT_ROOT / name
        if path.is_file():
            errors.extend(_scan_safety_text(path))
    errors.extend(_scan_default_node_caps())
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("PASS authoritative safety policy")
    return 0


def _scan_safety_text(path: Path) -> list[str]:
    relative = path.relative_to(PROJECT_ROOT).as_posix()
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return [f"{relative}: cannot read: {exc}"]
    errors: list[str] = []
    for line_number, line in enumerate(lines, start=1):
        if "SAFETY-SANDBOX-OK" in line:
            continue
        for pattern, reason in SAFETY_PATTERNS:
            if pattern.search(line):
                errors.append(f"{relative}:{line_number}: {reason}: {line.strip()}")
    return errors


def _scan_default_node_caps() -> list[str]:
    errors: list[str] = []
    for path in (PROJECT_ROOT / "templates/configs").glob("*.yaml"):
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        if "scale_1000" in path.name:
            required = ("allow_1000_nodes: true", "dry_run: true", "opt_in_1000: true")
            if any(value not in text for value in required):
                errors.append(f"{relative}: 1000 profile must be opt-in dry-run")
            continue
        if re.search(r"allow_1000_nodes:\s*true", text):
            errors.append(f"{relative}: non-1000 config may not enable 1000 nodes")
        shards = re.search(r"\n\s*shards:\s*(\d+)", text)
        replicas = re.search(r"\n\s*replicas_per_shard:\s*(\d+)", text)
        if shards and replicas:
            nodes = int(shards.group(1)) * (1 + int(replicas.group(1)))
            exception = (
                path.name == "scale_200.yaml"
                and nodes == 200
                and "bounded_exception_phase: P21_FAILOVER_LATENCY_CURVE_200" in text
                and "bounded_exception_nodes: 200" in text
                and "allow_1000_nodes: false" in text
                and "default_max_nodes: 100" in text
            )
            if nodes > 100 and not exception:
                errors.append(f"{relative}: default config creates {nodes} nodes (>100)")
    return errors


def _evaluator(milestone: int) -> Any:
    return _authority_module(
        EVALUATOR_PATHS[milestone],
        f"Milestone {milestone} authoritative evidence evaluator",
    )


def _authority_module(path: Path, label: str) -> Any:
    if not path.is_file():
        raise RuntimeError(f"{label} is missing: {path}")
    spec = importlib.util.spec_from_file_location(
        f"vpro_authority_{hashlib.sha256(str(path).encode()).hexdigest()[:16]}",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {label}: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prerequisite(milestone: int, raw_path: str) -> int:
    try:
        _verified_prerequisite(milestone, raw_path)
    except FileNotFoundError as exc:
        print(f"BLOCKED: {exc}")
        return 2
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 1
    return 0


def _verified_prerequisite(milestone: int, raw_path: str) -> dict[str, Any]:
    path = (PROJECT_ROOT / raw_path).resolve()
    if not path.is_relative_to(PROJECT_ROOT) or not path.is_file():
        raise FileNotFoundError(f"milestone {milestone} prerequisite receipt is missing: {raw_path}")
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid prerequisite receipt: {exc}") from exc
    required_milestone = milestone - 1
    if not isinstance(receipt, dict) or receipt.get("milestone") != required_milestone:
        raise ValueError(f"prerequisite receipt must prove milestone {required_milestone}")
    if receipt.get("claim") != "MILESTONE_COMPLETE" or not _digest(receipt.get("completion_digest")):
        raise ValueError("prerequisite receipt lacks a milestone completion digest")
    verifier = _authority_module(
        PREREQUISITE_VERIFIER_PATHS[milestone],
        f"Milestone {milestone} prerequisite verifier",
    )
    verified = verifier.verify(
        receipt=receipt,
        required_milestone=required_milestone,
        required_claim="MILESTONE_COMPLETE",
    )
    if not isinstance(verified, Mapping) or verified.get("status") != "PASS":
        raise RuntimeError("prerequisite verifier did not authenticate a PASS receipt")
    if verified.get("completion_digest") != receipt["completion_digest"]:
        raise RuntimeError("prerequisite verifier returned another completion digest")
    return dict(verified)


def _preflight(
    milestone: int,
    scale: int,
    prior: str | None,
    prerequisite: str | None,
) -> int:
    scratch = Path(os.environ.get("TMPDIR", "/tmp")).resolve()
    product_digest = os.environ.get("VPRO_PRODUCT_DIGEST", "")
    if not _digest(product_digest):
        print("FAIL: VPRO_PRODUCT_DIGEST is missing")
        return 1
    _prior(
        prior,
        milestone=milestone,
        scale=scale,
        product_digest=product_digest,
    )
    verified_prerequisite = (
        _verified_prerequisite(milestone, prerequisite)
        if milestone > 1 and prerequisite is not None
        else None
    )
    if milestone > 1 and verified_prerequisite is None:
        print(f"FAIL: Milestone {milestone} preflight requires an authenticated prerequisite")
        return 1
    if milestone == 1:
        if scale not in {50, 200}:
            print("FAIL: Milestone 1 completion gates are exact 50 and 200")
            return 1
        if shutil.which("docker") is None:
            print("BLOCKED: sealed Docker CLI is unavailable")
            return 2
        if _run(["docker", "info", "--format", "{{.ServerVersion}}"]):
            print("BLOCKED: Docker daemon is unavailable")
            return 2
        from valkey_scale_lab.resource import run_resource_preflight
        from valkey_scale_lab.scenarios import compile_gate_plan, load_milestone1_definition

        plan = compile_gate_plan(load_milestone1_definition(), scale)
        if plan.config_template is None or plan.runtime_phase is None or plan.runtime_scenario is None:
            print("FAIL: Milestone 1 exact gate has no runtime configuration")
            return 1
        report = run_resource_preflight(
            plan.config_template,
            scratch / f"vpro-m1-{scale}-preflight.json",
            phase_id=plan.runtime_phase,
            scenario=plan.runtime_scenario,
        )
        observed = report.get("nodes_requested", report.get("node_count"))
        if observed != scale or report.get("status") not in {"PASS", "READY"}:
            print(f"BLOCKED: exact resource preflight failed: {report}")
            return 2
        return 0
    allowed_scales = {2: {50, 200}, 3: {500, 1000, 2000}}
    if scale not in allowed_scales[milestone]:
        print(f"FAIL: Milestone {milestone} has no exact {scale} completion gate")
        return 1
    module = _authority_module(
        PREFLIGHT_PATHS[milestone],
        f"Milestone {milestone} authoritative preflight",
    )
    report = module.run(
        milestone=milestone,
        scale=scale,
        product_digest=product_digest,
        prerequisite=verified_prerequisite,
        scratch_root=scratch,
    )
    _validate_distributed_preflight(report, milestone, scale, product_digest)
    return 0


def _validate_distributed_preflight(
    report: Any,
    milestone: int,
    scale: int,
    product_digest: str,
) -> None:
    expected = {
        "schema_version": "vpro-distributed-preflight-v1",
        "milestone": milestone,
        "requested_nodes": scale,
        "admitted_nodes": scale,
        "product_digest": product_digest,
        "status": "PASS",
        "can_run": True,
    }
    if not isinstance(report, Mapping):
        raise RuntimeError("authoritative preflight did not return an object")
    for key, value in expected.items():
        if report.get(key) != value:
            raise RuntimeError(f"authoritative preflight {key} must be {value!r}")
    required_checks = {
        "quota",
        "capacity",
        "ports",
        "file_descriptors",
        "memory",
        "cpu",
        "network",
        "storage",
        "credentials",
        "ownership",
        "cost",
    }
    checks = report.get("checks")
    if not isinstance(checks, Mapping) or any(checks.get(name) != "PASS" for name in required_checks):
        raise RuntimeError("authoritative preflight lacks required PASS checks")


def _evidence_path(raw: str) -> Path:
    root_raw = os.environ.get("VPRO_EVIDENCE_ROOT")
    if not root_raw:
        raise RuntimeError("VPRO_EVIDENCE_ROOT is required")
    root = Path(root_raw).resolve()
    relative = PurePosixPath(raw)
    if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise RuntimeError(f"invalid evidence-relative path: {raw}")
    target = root.joinpath(*relative.parts).resolve()
    if not target.is_relative_to(root):
        raise RuntimeError(f"evidence path escapes the controller root: {raw}")
    return target


def _prior(
    raw: str | None,
    *,
    milestone: int,
    scale: int,
    product_digest: str,
) -> dict[str, Any] | None:
    predecessor = {
        (1, 200): 50,
        (2, 200): 50,
        (3, 1000): 500,
        (3, 2000): 1000,
    }.get((milestone, scale))
    if raw is None:
        if predecessor is not None:
            raise RuntimeError(f"scale {scale} requires the admitted {predecessor} predecessor")
        return None
    if predecessor is None:
        raise RuntimeError(f"scale {scale} does not accept a prior admission decision")
    path = _evidence_path(raw) / "decision.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"prior admission decision is unavailable: {exc}") from exc
    if not isinstance(value, dict) or value.get("status") != "PASS" or not _digest(value.get("decision_digest")):
        raise RuntimeError("prior admission decision is not a valid PASS")
    claimed_digest = value.get("decision_digest")
    unsigned = dict(value)
    unsigned.pop("decision_digest", None)
    if claimed_digest != _canonical_digest(unsigned):
        raise RuntimeError("prior admission decision digest is invalid")
    if value.get("milestone") != milestone or value.get("scale") != predecessor:
        raise RuntimeError(
            f"prior admission decision must be Milestone {milestone} scale {predecessor}"
        )
    if value.get("product_digest") != product_digest:
        raise RuntimeError("prior admission decision belongs to another product digest")
    return value


def _capture(
    milestone: int,
    scale: int,
    output: str,
    prior: str | None,
    prerequisite: str | None,
) -> int:
    target = _evidence_path(output)
    if target.exists() and any(target.iterdir()):
        print(f"FAIL: capture output is not fresh: {target}")
        return 1
    target.mkdir(parents=True, exist_ok=True)
    product_digest = os.environ.get("VPRO_PRODUCT_DIGEST", "")
    if not _digest(product_digest):
        print("FAIL: VPRO_PRODUCT_DIGEST is missing")
        return 1
    _prior(
        prior,
        milestone=milestone,
        scale=scale,
        product_digest=product_digest,
    )
    if milestone > 1:
        if prerequisite is None:
            raise RuntimeError(f"Milestone {milestone} capture requires an authenticated prerequisite")
        _verified_prerequisite(milestone, prerequisite)
    if milestone == 1:
        from valkey_scale_lab.milestone1_gate import run_real_gate

        old_owner = os.environ.get("VSLAB_META_M1_CONTROLLER_OWNED")
        old_digest = os.environ.get("VSLAB_META_M1_PRODUCT_DIGEST")
        try:
            os.environ["VSLAB_META_M1_CONTROLLER_OWNED"] = "1"
            os.environ["VSLAB_META_M1_PRODUCT_DIGEST"] = product_digest
            run_real_gate(scale, target)
        finally:
            _restore_environment("VSLAB_META_M1_CONTROLLER_OWNED", old_owner)
            _restore_environment("VSLAB_META_M1_PRODUCT_DIGEST", old_digest)
        return 0
    return _run_product_cli(
        [
            f"milestone{milestone}",
            "real-gate",
            "--scale",
            str(scale),
            "--evidence-dir",
            str(target),
        ]
    )


def _admission(
    milestone: int,
    scale: int,
    capture: str,
    output: str,
    prior: str | None,
    prerequisite: str | None,
) -> int:
    capture_path = _evidence_path(capture)
    output_path = _evidence_path(output)
    product_digest = os.environ.get("VPRO_PRODUCT_DIGEST", "")
    if not _digest(product_digest):
        print("FAIL: VPRO_PRODUCT_DIGEST is missing")
        return 1
    prior_value = _prior(
        prior,
        milestone=milestone,
        scale=scale,
        product_digest=product_digest,
    )
    prerequisite_value = None
    if milestone > 1:
        if prerequisite is None:
            raise RuntimeError(f"Milestone {milestone} admission requires an authenticated prerequisite")
        prerequisite_value = _verified_prerequisite(milestone, prerequisite)
    decision = _evaluator(milestone).evaluate(
        milestone=milestone,
        scale=scale,
        capture_root=capture_path,
        product_digest=product_digest,
        prior_decision=prior_value,
        prerequisite_receipt=prerequisite_value,
    )
    decision = _validated_decision(
        decision,
        milestone=milestone,
        scale=scale,
        capture_path=capture_path,
        product_digest=product_digest,
        prior_decision=prior_value,
        prerequisite_receipt=prerequisite_value,
    )
    output_path.mkdir(parents=True, exist_ok=True)
    (output_path / "decision.json").write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if decision.get("status") != "PASS":
        print(json.dumps(decision, sort_keys=True))
        return 1
    return 0


def _validated_decision(
    decision: Any,
    *,
    milestone: int,
    scale: int,
    capture_path: Path,
    product_digest: str,
    prior_decision: dict[str, Any] | None,
    prerequisite_receipt: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(decision, Mapping):
        raise RuntimeError("evidence evaluator did not return a decision object")
    expected = {
        "schema_version": "vpro-milestone-admission-decision-v1",
        "milestone": milestone,
        "scale": scale,
        "run_id": os.environ.get("VPRO_RUN_ID"),
        "framework_digest": os.environ.get("VPRO_FRAMEWORK_DIGEST"),
        "bundle_digest": os.environ.get("VPRO_BUNDLE_DIGEST"),
        "product_digest": product_digest,
        "capture_digest": _capture_digest(capture_path),
        "prior_decision_digest": (
            prior_decision.get("decision_digest") if prior_decision is not None else None
        ),
        "prerequisite_completion_digest": (
            prerequisite_receipt.get("completion_digest")
            if prerequisite_receipt is not None
            else None
        ),
    }
    for key, value in expected.items():
        if not value and key in {"run_id", "framework_digest", "bundle_digest"}:
            raise RuntimeError(f"VPRO_{key.upper()} is missing")
        if decision.get(key) != value:
            raise RuntimeError(f"evaluator decision {key} must be {value!r}")
    status = decision.get("status")
    errors = decision.get("errors")
    if status not in {"PASS", "FAIL"} or not isinstance(errors, list) or any(
        not isinstance(error, str) or not error for error in errors
    ):
        raise RuntimeError("evaluator decision has an invalid status/errors envelope")
    if (status == "PASS" and errors) or (status == "FAIL" and not errors):
        raise RuntimeError("evaluator decision status and errors disagree")
    evidence_digest = decision.get("evidence_admission_digest")
    if status == "PASS" and not _digest(evidence_digest):
        raise RuntimeError("PASS decision lacks an evidence admission digest")
    if status == "FAIL" and evidence_digest is not None and not _digest(evidence_digest):
        raise RuntimeError("FAIL decision has an invalid evidence admission digest")
    claimed = decision.get("decision_digest")
    unsigned = dict(decision)
    unsigned.pop("decision_digest", None)
    if not _digest(claimed) or claimed != _canonical_digest(unsigned):
        raise RuntimeError("evaluator decision digest is invalid")
    return dict(decision)


def _capture_digest(root: Path) -> str:
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError("capture root must be a non-symlink directory")
    digest = hashlib.sha256()
    digest.update(b"VPRO-CAPTURE-TREE-v1\0")
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(directories)
        files = sorted(files)
        for name in tuple(directories):
            path = current_path / name
            if path.is_symlink():
                raise RuntimeError(f"capture contains a symlink: {path}")
            relative = path.relative_to(root).as_posix()
            digest.update(f"DIR\0{relative}\0".encode())
        for name in files:
            path = current_path / name
            if path.is_symlink() or not path.is_file():
                raise RuntimeError(f"capture contains a symlink or special file: {path}")
            relative = path.relative_to(root).as_posix()
            content = hashlib.sha256(path.read_bytes()).digest()
            digest.update(f"FILE\0{relative}\0".encode())
            digest.update(content)
    return digest.hexdigest()


def _digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _restore_environment(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "suite":
            return _suite(args.id)
        if args.command == "static-safety":
            return _static_safety()
        if args.command == "closure":
            return _closure()
        if args.command == "evaluator-guard":
            if not _evaluator(args.milestone).self_check(args.milestone):
                return 1
            return _suite(f"m{args.milestone}-evaluator-policy")
        if args.command == "prerequisite":
            return _prerequisite(args.milestone, args.receipt)
        if args.command == "preflight":
            return _preflight(args.milestone, args.scale, args.prior, args.prerequisite)
        if args.command == "capture":
            return _capture(
                args.milestone,
                args.scale,
                args.output,
                args.prior,
                args.prerequisite,
            )
        if args.command == "admission":
            return _admission(
                args.milestone,
                args.scale,
                args.capture,
                args.output,
                args.prior,
                args.prerequisite,
            )
        if args.command == "product-cli":
            sys.argv = ["valkey_scale_lab.cli", *args.arguments]
            try:
                runpy.run_module("valkey_scale_lab.cli", run_name="__main__", alter_sys=True)
            except SystemExit as exc:
                return int(exc.code or 0) if isinstance(exc.code, (int, type(None))) else 1
            return 0
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
