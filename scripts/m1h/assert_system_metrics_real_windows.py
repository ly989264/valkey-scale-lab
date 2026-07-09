#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _capability_script import run

if __name__ == "__main__":
    raise SystemExit(run("assert_system_metrics_real_windows", "system_metrics", {30, 50, 100, 200}))
