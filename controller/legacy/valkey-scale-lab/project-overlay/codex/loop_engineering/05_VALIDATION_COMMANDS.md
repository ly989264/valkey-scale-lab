# 05_VALIDATION_COMMANDS.md — 验证命令清单

## 1. 每个 stage 必跑 baseline

```bash
python3 scripts/codex_gate.py precheck --all
python3 scripts/safety_scan.py
python3 -m compileall -q src scripts tests
python3 -m pytest -q tests/ci/test_postcheck_compatibility.py
python3 -m pytest -q tests/unit tests/ci/test_github_coverage_gates.py
python3 -m pytest -q tests/config tests/planner
python3 -m pytest -q tests/integration tests/fault tests/failover tests/orchestrator
python3 -m pytest -q tests/analysis tests/report tests/stability tests/scale
```

## 2. loop-engineering 自身验证

```bash
python3 scripts/loop_engineering_validate.py --root artifacts/loop_engineering
python3 -m pytest -q tests/loop_engineering tests/ci/test_loop_engineering_pack.py
```

如果 `scripts/loop_engineering_validate.py` 尚未存在，则 L00 必须先实现。

## 3. 审计验证

```bash
python3 scripts/audit_committed_artifacts.py --out artifacts/loop_engineering/reports/audit_report.json
python3 -m pytest -q tests/audit
python3 -m pytest -q tests/ci/test_committed_artifact_audit_gate.py
```

## 4. metric coverage 验证

```bash
python3 scripts/build_metric_coverage_matrix.py --out-dir artifacts/loop_engineering/reports
python3 -m pytest -q tests/metrics tests/coverage
```

## 5. 报告与可视化验证

```bash
python3 -m pytest -q tests/report tests/visualization
python3 scripts/render_audit_report.py --input-dir artifacts/loop_engineering/reports --out-dir artifacts/loop_engineering/reports
```

## 6. real Valkey 小集群验证

在需要真实小集群时运行：

```bash
python3 scripts/valkey_e2e_gate.py --phase P03_LOCAL_DOCKER_VALKEY --config templates/configs/single_mac_6node.yaml --scenario cluster_smoke --out artifacts/loop_engineering/real_gates/valkey_e2e_cluster_smoke.json --min-nodes 6 --require-data-path
```

故障/接管场景使用现有或新增 gate wrapper，必须先 resource/preflight 或环境检测。

## 7. real Valkey 30/50/100 scale 验证

当前项目已有 30/50/100 scale gate。需要真实验证时运行对应 preflight，再运行 gate：

```bash
python3 -m valkey_scale_lab.cli resource preflight --config templates/configs/scale_30.yaml --out artifacts/loop_engineering/real_gates/resource_preflight_30.json
python3 scripts/valkey_e2e_gate.py --phase P12_SCALE_LADDER_10_30 --config templates/configs/scale_30.yaml --scenario scale_30 --out artifacts/loop_engineering/real_gates/valkey_e2e_scale_30.json --min-nodes 30 --require-data-path

python3 -m valkey_scale_lab.cli resource preflight --config templates/configs/scale_50.yaml --out artifacts/loop_engineering/real_gates/resource_preflight_50.json
python3 scripts/valkey_e2e_gate.py --phase P13_SCALE_LADDER_50_100 --config templates/configs/scale_50.yaml --scenario scale_50 --out artifacts/loop_engineering/real_gates/valkey_e2e_scale_50.json --min-nodes 50 --require-data-path

python3 -m valkey_scale_lab.cli resource preflight --config templates/configs/scale_100.yaml --out artifacts/loop_engineering/real_gates/resource_preflight_100.json
python3 scripts/valkey_e2e_gate.py --phase P13_SCALE_LADDER_50_100 --config templates/configs/scale_100.yaml --scenario scale_100 --out artifacts/loop_engineering/real_gates/valkey_e2e_scale_100.json --min-nodes 100 --require-data-path
```

如果资源 preflight 失败，不得把 real stage 标为 PASS。

## 8. 1000+ dry-run 验证

```bash
export VSLAB_ALLOW_1000_DRYRUN=I_UNDERSTAND_THIS_IS_NOT_A_DEFAULT_GATE
python3 -m valkey_scale_lab.cli resource preflight --config templates/configs/scale_1000_dryrun_optin.yaml --dry-run --out artifacts/loop_engineering/dryrun/resource_preflight_1000.json
python3 -m valkey_scale_lab.cli plan --config templates/configs/scale_1000_dryrun_optin.yaml --dry-run --out artifacts/loop_engineering/dryrun/scale_1000_dryrun_plan.json
python3 scripts/assert_plan_constraints.py --plan artifacts/loop_engineering/dryrun/scale_1000_dryrun_plan.json --max-nodes 100 --allow-opt-in-1000 --require-dry-run
```

不得将这些 dry-run artifact 计入 real Valkey coverage。

## 9. git 验证与 push

```bash
git status --short
git diff --stat
git diff -- tests scripts schemas .github codex artifacts/gates artifacts/phases artifacts/loop_engineering

git add .
git commit -m "<STAGE_ID>: <summary>"
git push origin HEAD:codex/valkey-scale-lab-loop

git rev-parse HEAD
git log -1 --oneline
```
