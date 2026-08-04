# Agent Memory 使用规则

`.agents/memory/` 是可复用经验的候选收件箱，不是项目正式知识库。普通任务不得默认加载这里；只有捕获、审核或提升经验时才读取。

```text
发现经验 -> 暂存 memory -> 验证与确认 -> 提升到正式位置 -> 从 memory 删除
```

## 可以写入什么

- 用户明确表达的 `ALWAYS`、`NEVER`、`PREFER` 或 `AVOID` 规则。
- 用户对 Agent 错误的纠正，且同类错误可能再次发生。
- 从真实操作中发现、尚待确认适用范围的项目 gotcha。

不要写入 secret、瞬时运行状态、大段日志、一次性计划、代码可直接回答的普通事实，或正式文档已有的内容。

## 如何记录

在 [`captured-rules.md`](captured-rules.md) 的 Pending Rules 中记录：

- 日期和标题；
- 用户原话或来源；
- 可执行的规则；
- `ALWAYS`、`NEVER`、`PREFER` 或 `AVOID` 类型；
- 适用场景与待验证点。

未经验证的内容必须保持候选语气，不能当作项目规则执行。

## 何时提升

经验同时满足“已验证、可复用、遗漏会造成实际风险、触发条件明确、获得必要确认”时，提升到唯一正式位置：

| 内容 | 正式位置 |
| --- | --- |
| 全项目规则 | [`CLAUDE.md`](../../CLAUDE.md)；`AGENTS.md` 会通过符号链接同步 |
| 特定任务约束 | [`docs/agents/`](../../docs/agents/) |
| 当前命令和运维事实 | [`docs/operations/`](../../docs/operations/) |
| 架构决定 | [`docs/adr/`](../../docs/adr/) |
| 指南或历史材料 | [`docs/guides/`](../../docs/guides/) 或 [`docs/archive/`](../../docs/archive/) |

提升后从 memory 删除原条目；Git 历史承担溯源。若 memory 与正式文档冲突，以正式文档为执行依据并核验它是否过时。
