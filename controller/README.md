# Minimal Milestone Controller

This package runs one automatic loop for one Codex Goal session in one
controlled Git workspace:

```text
full evaluation -> one objective -> Git checkpoint -> Worker
-> full evaluation -> commit progress or roll back -> repeat
```

The Milestone contains only the immutable goal, success conditions, evidence
requirements, and termination conditions. Evaluator and Worker path settings
are ordinary Controller startup inputs, not Milestone policy.

The Python API is the runtime entry point:

```python
import sys
from pathlib import Path
from controller import CommandEvaluator, Controller

evaluator = CommandEvaluator([
    sys.executable,
    "controller/integrations/valkey-scale-lab/full_evaluator.py",
    "--milestone", "/tmp/valkey-m1.milestone.json",
    "--project-root", "project",
    "--evidence-root", "/tmp/controller-run/evidence",
    "--run-id", "m1-run",
], cwd=Path.cwd())

controller = Controller(
    milestone_path="/tmp/valkey-m1.milestone.json",
    project_root="project",
    allowed_write_paths=("src", "templates", "docs"),
    protected_paths=("milestones", "verification", "tests"),
    evaluator=evaluator,
    state_path="/tmp/controller-run/state.json",
)
result = controller.run(plan_one_objective, execute_objective)  # Goal-session callbacks
```

`evaluate_all(milestone, project_root)` must return every success-condition
result and every evidence-requirement result. Missing, stale, substituted,
untrusted, blocked, or failed evidence remains a gap. Planner and Worker return
values never count as acceptance evidence.

Validate a Milestone or inspect a run:

```bash
python3 controller/CONTROLLER_LAUNCH.py milestone-validate \
  --milestone controller/templates/milestone.template.json
python3 controller/CONTROLLER_LAUNCH.py status --state /tmp/controller-run/state.json
```

The Valkey integration keeps its real verification and evidence-admission
checks. Those artifacts are product acceptance facts; the Controller simply
uses their complete current result when deriving Goal State.
