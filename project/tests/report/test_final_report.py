from __future__ import annotations

import json
from pathlib import Path

from valkey_scale_lab.report.final import MANAGEMENT_ROWS, _management_rows


def test_management_rows_use_one_canonical_result_stream(tmp_path: Path) -> None:
    results = tmp_path / "management_operation_results.jsonl"
    results.write_text(
        "".join(
            json.dumps(
                {
                    "operation_name": operation,
                    "operation_status": "PASS",
                    "node_count": 50,
                    "capability_id": "management_matrix",
                }
            )
            + "\n"
            for operation in MANAGEMENT_ROWS
        ),
        encoding="utf-8",
    )

    rows = _management_rows({"management_results": results})

    assert [row["operation_name"] for row in rows] == MANAGEMENT_ROWS
    assert all(row["status"] == "PASS" for row in rows)
    assert all(row["row_count"] == 1 for row in rows)
    assert all(row["source_artifacts"] == results.as_posix() for row in rows)
