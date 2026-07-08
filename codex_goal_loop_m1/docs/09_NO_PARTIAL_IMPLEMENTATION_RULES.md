# 09_NO_PARTIAL_IMPLEMENTATION_RULES — 禁止局部实现

## 明确禁止

以下实现方式必须被 review 判为 FAIL：

```text
只在 30 节点真实运行路径加指标。
只在 200 节点路径加指标。
只在 fake fixture 里加字段。
只在 report 里写字段，但底层 artifact 没有。
只在 artifact writer 写字段，但 analyzer 不读。
只在 analyzer 读字段，但中文报告不展示。
只新增测试，不接入运行路径。
只新增 schema，不接入 writer。
只新增 stage-specific 临时脚本。
真实 gate 失败时 hard-code PASS。
真实运行不可用时写 fake real evidence。
只检查文件存在，不检查内容。
空 JSONL 仍判 PASS。
```

## 正确做法

每次新增指标或行为时，必须同时处理：

```text
通用 runtime path
所有相关 scale rung
fake fixture
smoke path
real local run path
dry-run / blocked path
failure path
cleanup path
schema
analysis
report
regression gate
```

## review 检查问题

review subagent 必须逐项回答：

1. 这个改动是否进入通用路径？
2. 是否只服务某个规模？
3. 是否只服务某个测试？
4. 是否只服务某个阶段？
5. fake 和真实路径是否使用同一 schema？
6. dry-run / blocked 是否有 reason？
7. report 是否真的展示这些字段？
8. final acceptance gate 是否能防止该字段未来掉线？
