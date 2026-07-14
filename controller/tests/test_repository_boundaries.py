from __future__ import annotations

import ast
import subprocess
import sys
import zipfile
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = REPOSITORY_ROOT / "project"
CONTROLLER_ROOT = REPOSITORY_ROOT / "controller"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_product_tree_has_no_controller_or_vpro_material() -> None:
    forbidden = [
        PROJECT_ROOT / "checks/vpro",
        PROJECT_ROOT / "evaluators/vpro",
        PROJECT_ROOT / "schemas/vpro",
        PROJECT_ROOT / "schemas/vpro2",
        PROJECT_ROOT / "src/valkey_scale_lab/vpro",
        PROJECT_ROOT / "src/vpro2",
        PROJECT_ROOT / "tests/vpro",
        PROJECT_ROOT / "VPRO_LAUNCH.py",
        PROJECT_ROOT / "VPRO_START.md",
    ]
    assert not [path for path in forbidden if path.exists()]
    product_files = [
        path
        for root in (PROJECT_ROOT / "src", PROJECT_ROOT / "schemas", PROJECT_ROOT / "scripts")
        for path in root.rglob("*")
        if path.is_file()
    ]
    forbidden_tokens = (
        "VPRO_",
        "VSLAB_META_M1_",
        "META_M1",
        "M1_",
        "M1-",
        "m1_",
        "m1-",
        "_m1",
        "MILESTONE",
    )
    offenders = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in product_files
        if any(
            token in path.read_text(encoding="utf-8", errors="ignore")
            for token in forbidden_tokens
        )
    ]
    assert offenders == []


def test_product_source_imports_only_product_and_library_layers() -> None:
    forbidden_roots = {"tests", "milestones", "verification", "controller", "vpro", "vpro2"}
    offenders: list[str] = []
    for path in (PROJECT_ROOT / "src").rglob("*.py"):
        for imported in _imports(path):
            root = imported.split(".", 1)[0]
            if root in forbidden_roots or any(
                token in imported.split(".")
                for token in ("tests", "milestones", "verification", "controller", "vpro", "vpro2")
            ):
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {imported}")
    assert offenders == []


def test_product_tests_do_not_import_milestones_or_controller() -> None:
    forbidden = {"milestones", "controller", "vpro", "vpro2"}
    offenders: list[str] = []
    for path in (PROJECT_ROOT / "tests").rglob("*.py"):
        for imported in _imports(path):
            if any(part in forbidden for part in imported.split(".")):
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {imported}")
    assert offenders == []


def test_milestones_reference_suite_ids_not_test_paths() -> None:
    for path in (PROJECT_ROOT / "milestones").glob("m*/milestone.json"):
        text = path.read_text(encoding="utf-8")
        assert "tests/" not in text
        assert "pytest" not in text
        assert "VPRO" not in text
        assert "controller" not in text.lower()


def test_active_vpro2_integration_and_vpro1_archive_are_outside_product() -> None:
    assert (CONTROLLER_ROOT / "vpro2/src/vpro2/service.py").is_file()
    assert (CONTROLLER_ROOT / "integrations/valkey-scale-lab/compile_contract.py").is_file()
    assert (CONTROLLER_ROOT / "integrations/valkey-scale-lab/evaluators/evidence_admission.py").is_file()
    assert (CONTROLLER_ROOT / "legacy/valkey-scale-lab/vpro1-bundles/milestone1.bundle.json").is_file()
    assert not (CONTROLLER_ROOT / "bundles/valkey-scale-lab").exists()
    assert (CONTROLLER_ROOT / "vpro/codex/vpro/framework_release.json").is_file()


def test_product_wheel_contains_only_the_product_package(tmp_path: Path) -> None:
    import setuptools

    if int(setuptools.__version__.split(".", 1)[0]) < 68:
        packages = setuptools.find_namespace_packages(where=str(PROJECT_ROOT / "src"))
        assert packages
        assert all(name == "valkey_scale_lab" or name.startswith("valkey_scale_lab.") for name in packages)
        assert '"valkey_scale_lab.scenarios" = ["definitions/*.json"]' in (
            PROJECT_ROOT / "pyproject.toml"
        ).read_text(encoding="utf-8")
        return
    wheel_dir = tmp_path / "wheel"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheel_dir),
            ".",
        ],
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout
    wheel = next(wheel_dir.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    assert any(name.startswith("valkey_scale_lab/") for name in names)
    assert "valkey_scale_lab/scenarios/definitions/local_full_flow_v1.json" in names
    assert not any(
        name.startswith(("tests/", "verification/", "milestones/", "controller/"))
        for name in names
    )
