"""Isolated bootstrap for the fixed VPRO controller."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


if not sys.flags.isolated or not sys.flags.no_site or not sys.flags.dont_write_bytecode:
    raise SystemExit("VPRO_LAUNCH requires Python flags -I -S -B")

framework_root = Path(__file__).resolve().parent
sys.path.append(str(framework_root / "src"))
runpy.run_module("valkey_scale_lab.vpro", run_name="__main__", alter_sys=True)
