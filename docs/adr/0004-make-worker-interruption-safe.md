# ADR-0004：让 queue worker 的中断可安全恢复

- **日期**：2026-06-11
- **状态**：accepted
- **决策者**：User、Codex

## 当前适用范围

本决策适用于仓库外的 OpenClaw worker：

```text
~/.openclaw/workspace/automation/knowledge-digest/worker.py
```

当前 worker 已处理 `SIGTERM` 和 `SIGINT`，记录 interrupted 状态并释放自身 lock。它调用本仓库 CLI，但其 signal、queue 与 lock implementation 不属于本仓库 source tree。

## 背景

如果 worker 在 Digest 运行中被打断，系统可能留下虚假的 `running` 状态和 stale lock。这样既会误导状态输出，也可能阻止下一次 worker tick 继续处理未完成请求。

## 决策

Worker 收到 `SIGTERM` 或 `SIGINT` 时必须：

1. 把当前任务记录为 interrupted；
2. 把状态从 `running` 转出；
3. 释放只属于当前 worker 的 lock；
4. 保留未完成请求；
5. 允许下一次 worker run 继续处理。

## 考虑过的替代方案

### 不做清理，直接退出

- **优点**：不需要 signal handling。
- **缺点**：可能留下 stale lock 和假 running 状态。
- **不采用原因**：这正是无人值守任务最重要的恢复故障之一。

### 下次启动时删除全部状态

- **优点**：恢复逻辑表面简单。
- **缺点**：可能丢失排队请求，也会抹掉中断证据。
- **不采用原因**：恢复必须保留可诊断状态和未完成工作。

## 影响

### 正面

- 状态可以区分 active 与 interrupted。
- 下一次 tick 可以继续未完成请求。
- 操作者不必猜测 lock 是否仍代表 live worker。

### 负面

- Worker 需要明确的 signal handling 和 cleanup 顺序。
- 外部 worker 的测试和版本需要独立维护。

### 风险

- 错误清理可能删除另一个 live worker 的 lock。通过记录 ownership，并只释放当前进程拥有的 lock 来缓解。

## 相关资料

- [ADR-0001：使用 launchd 和本地 queue worker](0001-use-launchd-local-queue-worker.md)
- [ADR-0005：不强制重启运行中的 worker](0005-do-not-force-restart-running-worker.md)
- [项目地图中的 OpenClaw 边界](../guides/project-map.md)
