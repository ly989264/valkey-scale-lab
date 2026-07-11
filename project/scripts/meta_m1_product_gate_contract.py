#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import inspect
from pathlib import Path

from valkey_scale_lab import milestone1_gate


def main() -> int:
    validator = getattr(milestone1_gate, "validate_admission_sources", None)
    builder = getattr(milestone1_gate, "build_admission_from_sources", None)
    if getattr(milestone1_gate, "ADMISSION_SCHEMA_VERSION", None) != "meta-m1-admission-v2":
        print("FAIL: product gate must declare ADMISSION_SCHEMA_VERSION='meta-m1-admission-v2'")
        return 1
    if not callable(validator):
        print("FAIL: milestone1_gate.validate_admission_sources(base, scale) is required")
        return 1
    if not callable(builder):
        print("FAIL: milestone1_gate.build_admission_from_sources(base, scale, product_digest) is required")
        return 1
    with tempfile.TemporaryDirectory(prefix="meta-m1-product-contract-") as temporary:
        errors = validator(Path(temporary), 50)
    if not isinstance(errors, list) or not errors:
        print("FAIL: product admission source validator accepted an empty evidence directory")
        return 1
    run_source = inspect.getsource(milestone1_gate.run_real_gate)
    if "validate_admission_sources" not in run_source or "build_admission_from_sources" not in run_source:
        print("FAIL: run_real_gate must validate sources before building admission")
        return 1
    if "common_duration" in run_source:
        print("FAIL: run_real_gate must not synthesize lifecycle timing by averaging total duration")
        return 1
    print("PASS product real-gate source validation contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
