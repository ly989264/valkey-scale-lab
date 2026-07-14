from __future__ import annotations

import json
from copy import deepcopy

from valkey_scale_lab.scenarios import (
    LOCAL_FULL_FLOW_DEFINITION_PATH,
    validate_scenario_definition,
)


def test_validator_rejects_identity_admission_from_wrong_raw_artifact() -> None:
    document = deepcopy(
        json.loads(LOCAL_FULL_FLOW_DEFINITION_PATH.read_text(encoding="utf-8"))
    )
    admission = document["artifacts"][1]["admissions"].pop()
    document["artifacts"][0]["admissions"].append(admission)

    assert validate_scenario_definition(document)
