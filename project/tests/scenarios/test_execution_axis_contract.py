from __future__ import annotations

import importlib.util
from pathlib import Path


def test_product_sources_keep_compatibility_names_outside_canonical_axes() -> None:
    script = Path(__file__).resolve().parents[2] / "scripts" / "assert_execution_axis_contract.py"
    spec = importlib.util.spec_from_file_location("execution_axis_contract", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.audit() == []
