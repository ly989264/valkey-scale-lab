from __future__ import annotations

import sys
from pathlib import Path

from valkey_scale_lab.meta_loop_v5.digests import product_tree_digest as evaluator_product_digest
from valkey_scale_lab.meta_loop_v6.digests import product_tree_digest as wrapper_product_digest


def test_capture_wrapper_and_evaluator_share_product_digest() -> None:
    project = Path(__file__).resolve().parents[2]
    scripts = project / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        from meta_m1_evidence_gate import source_tree_digest
    finally:
        sys.path.remove(str(scripts))

    expected = evaluator_product_digest(project)
    assert wrapper_product_digest(project) == expected
    assert source_tree_digest(project) == expected
