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


def test_product_tree_has_no_controller_material() -> None:
    forbidden = [
        PROJECT_ROOT / "checks/controller",
        PROJECT_ROOT / "evaluators/controller",
        PROJECT_ROOT / "schemas/controller",
        PROJECT_ROOT / "src/valkey_scale_lab/controller",
        PROJECT_ROOT / "src/controller",
        PROJECT_ROOT / "tests/controller",
        PROJECT_ROOT / "CONTROLLER_LAUNCH.py",
        PROJECT_ROOT / "CONTROLLER_START.md",
    ]
    assert not [path for path in forbidden if path.exists()]
    product_files = [
        path
        for root in (PROJECT_ROOT / "src", PROJECT_ROOT / "schemas", PROJECT_ROOT / "scripts")
        for path in root.rglob("*")
        if path.is_file() and path.name != "assert_execution_axis_contract.py"
    ]
    forbidden_tokens = (
        "CONTROLLER_",
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
    forbidden_roots = {"tests", "milestones", "verification", "controller"}
    offenders: list[str] = []
    for path in (PROJECT_ROOT / "src").rglob("*.py"):
        for imported in _imports(path):
            root = imported.split(".", 1)[0]
            if root in forbidden_roots or any(
                token in imported.split(".")
                for token in ("tests", "milestones", "verification", "controller")
            ):
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {imported}")
    assert offenders == []


def test_product_tests_do_not_import_milestones_or_controller() -> None:
    forbidden = {"milestones", "controller"}
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
        assert "controller" not in text.lower()


def test_controller_release_is_rooted_directly_under_controller() -> None:
    assert (CONTROLLER_ROOT / "src/controller/service.py").is_file()
    assert (CONTROLLER_ROOT / "CONTROLLER_LAUNCH.py").is_file()
    assert (CONTROLLER_ROOT / "integrations/valkey-scale-lab/compile_contract.py").is_file()
    assert (CONTROLLER_ROOT / "integrations/valkey-scale-lab/evaluators/evidence_admission.py").is_file()
    assert not (CONTROLLER_ROOT / "codex/framework_manifest.json").exists()
    assert not (CONTROLLER_ROOT / "codex/framework_release.json").exists()
    assert not (CONTROLLER_ROOT / "src/controller/roles.py").exists()
    assert not (CONTROLLER_ROOT / "src/controller/release.py").exists()
    assert not (CONTROLLER_ROOT / "controller").exists()
    assert not (CONTROLLER_ROOT / "legacy").exists()
    assert not (CONTROLLER_ROOT / "bundles/valkey-scale-lab").exists()


def test_retired_release_brand_is_absent_from_the_active_tree() -> None:
    retired_brand = "vp" + "ro"
    offenders: list[str] = []
    for path in REPOSITORY_ROOT.rglob("*"):
        relative = path.relative_to(REPOSITORY_ROOT)
        if relative.parts[0] in {".git", "loop_evidence"}:
            continue
        if any(part in {".pytest_cache", "__pycache__"} for part in relative.parts):
            continue
        if retired_brand in relative.as_posix().lower():
            offenders.append(relative.as_posix())
        elif path.is_file() and retired_brand in path.read_text(
            encoding="utf-8", errors="ignore"
        ).lower():
            offenders.append(relative.as_posix())
    assert offenders == []


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
