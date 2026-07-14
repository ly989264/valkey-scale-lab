from __future__ import annotations

import importlib.util
from pathlib import Path

from valkey_scale_lab.goal.digests import files_digest, product_tree_digest


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("isolated_v7_evaluator", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v7_evaluator_is_self_contained_and_legacy_edits_do_not_change_its_digest(tmp_path: Path) -> None:
    project = Path(__file__).resolve().parents[2]
    source = (project / "scripts/meta_m1_evidence_gate_v7.py").read_text(encoding="utf-8")
    assert "from meta_m1_evidence_gate import" not in source
    isolated = tmp_path / "scripts/meta_m1_evidence_gate_v7.py"
    isolated.parent.mkdir(parents=True)
    isolated.write_text(source, encoding="utf-8")
    legacy = tmp_path / "scripts/meta_m1_evidence_gate.py"
    legacy.write_text("raise RuntimeError('legacy must not load')\n", encoding="utf-8")
    before = files_digest(tmp_path, ("scripts/meta_m1_evidence_gate_v7.py",))
    legacy.write_text("raise RuntimeError('changed legacy must not load')\n", encoding="utf-8")
    assert files_digest(tmp_path, ("scripts/meta_m1_evidence_gate_v7.py",)) == before
    evaluator = _load(isolated)
    assert evaluator.evaluate(50, tmp_path / "missing")
    isolated.write_text(source + "\n# controlled evaluator change\n", encoding="utf-8")
    assert files_digest(tmp_path, ("scripts/meta_m1_evidence_gate_v7.py",)) != before


def test_product_digest_excludes_every_goal_and_meta_harness_prefix(tmp_path: Path) -> None:
    product = tmp_path / "src/valkey_scale_lab/product.py"
    product.parent.mkdir(parents=True)
    product.write_text("VALUE = 1\n", encoding="utf-8")
    goal = tmp_path / "src/valkey_scale_lab/goal/controller.py"
    goal.parent.mkdir(parents=True)
    goal.write_text("KERNEL = 1\n", encoding="utf-8")
    old = tmp_path / "src/valkey_scale_lab/meta_loop_v4/controller.py"
    old.parent.mkdir(parents=True)
    old.write_text("OLD = 1\n", encoding="utf-8")
    script = tmp_path / "scripts/meta_m1_any_version.py"
    script.parent.mkdir(parents=True)
    script.write_text("HARNESS = 1\n", encoding="utf-8")
    excludes = ("src/valkey_scale_lab/goal", "src/valkey_scale_lab/meta_loop", "scripts/meta_m1_")
    before = product_tree_digest(tmp_path, ("src", "scripts"), excludes)
    goal.write_text("KERNEL = 2\n", encoding="utf-8")
    old.write_text("OLD = 2\n", encoding="utf-8")
    script.write_text("HARNESS = 2\n", encoding="utf-8")
    assert product_tree_digest(tmp_path, ("src", "scripts"), excludes) == before
    product.write_text("VALUE = 2\n", encoding="utf-8")
    assert product_tree_digest(tmp_path, ("src", "scripts"), excludes) != before
