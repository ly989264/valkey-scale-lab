"""Direct entry point for the minimal Controller CLI."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
runpy.run_module("controller", run_name="__main__", alter_sys=True)
