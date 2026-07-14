#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from valkey_scale_lab import milestone1_gate


def main() -> int:
    required = ("run_real_gate", "validate_admission_sources", "build_admission_from_sources")
    missing = [name for name in required if not callable(getattr(milestone1_gate, name, None))]
    if missing:
        print(f"FAIL: product real-gate functions are missing: {missing}")
        return 1
    if milestone1_gate.ADMISSION_SCHEMA_VERSION != "meta-m1-admission-v2":
        print("FAIL: v9 compatibility requires admission-v2")
        return 1
    errors = milestone1_gate.validate_admission_sources(Path("/definitely/missing/v9-evidence"), 50)
    if not errors:
        print("FAIL: source validator accepted missing evidence")
        return 1
    print("PASS v9 product real-gate source contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
