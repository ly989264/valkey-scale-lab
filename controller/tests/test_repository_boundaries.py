from __future__ import annotations

import json
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = REPOSITORY_ROOT / "project"
CONTROLLER_ROOT = REPOSITORY_ROOT / "controller"


def test_product_tree_has_no_controller_kernels_or_control_material() -> None:
    forbidden = [
        PROJECT_ROOT / "codex",
        PROJECT_ROOT / "docs/codex",
        PROJECT_ROOT / "src/valkey_scale_lab/goal",
        PROJECT_ROOT / "src/valkey_scale_lab/meta_loop",
        PROJECT_ROOT / "src/valkey_scale_lab/meta_loop_v4",
        PROJECT_ROOT / "src/valkey_scale_lab/meta_loop_v5",
        PROJECT_ROOT / "src/valkey_scale_lab/meta_loop_v6",
        PROJECT_ROOT / "src/valkey_scale_lab/meta_loop_v7",
        PROJECT_ROOT / "src/valkey_scale_lab/meta_loop_v8",
        PROJECT_ROOT / "src/valkey_scale_lab/meta_loop_v9",
        PROJECT_ROOT / "src/valkey_scale_lab/vpro",
        PROJECT_ROOT / "schemas/vpro",
        PROJECT_ROOT / "templates/vpro",
        PROJECT_ROOT / "tests/vpro",
        PROJECT_ROOT / "VPRO_LAUNCH.py",
        PROJECT_ROOT / "VPRO_START.md",
    ]
    forbidden.extend(PROJECT_ROOT.glob("CODEX_*.md"))
    forbidden.extend(PROJECT_ROOT.glob("META_M1*.md"))

    assert not [path for path in forbidden if path.exists()]


def test_product_tree_does_not_expose_controller_evidence_links() -> None:
    for name in ("artifacts", "audit", "runs", ".github"):
        path = PROJECT_ROOT / name
        assert not path.is_symlink(), f"product boundary must not contain compatibility link {path}"


def test_framework_and_valkey_policy_live_outside_product() -> None:
    manifest_path = CONTROLLER_ROOT / "vpro/codex/vpro/framework_manifest.json"
    release_path = CONTROLLER_ROOT / "vpro/codex/vpro/framework_release.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    release = json.loads(release_path.read_text(encoding="utf-8"))

    assert manifest["framework_version"] == release["framework_version"] == "1.0.0"
    assert (CONTROLLER_ROOT / "vpro/src/valkey_scale_lab/vpro").is_dir()
    assert (CONTROLLER_ROOT / "bundles/valkey-scale-lab/milestone1.bundle.json").is_file()
    assert not (PROJECT_ROOT / "milestones/vpro").exists()


def test_product_package_has_no_imports_of_controller_packages() -> None:
    forbidden = (
        "valkey_scale_lab.vpro",
        "valkey_scale_lab.goal",
        "valkey_scale_lab.meta_loop",
    )
    offenders: list[str] = []
    for path in (PROJECT_ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in forbidden):
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())

    assert offenders == []
