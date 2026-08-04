# ADR-0001：使用 launchd 和本地 queue worker，而不是 Celery

- **日期**：2026-06-11
- **状态**：accepted
- **决策者**：User、Codex

## 当前适用范围

本决策仍然有效，但 queue worker 不属于当前仓库的 Python package。它位于：

```text
~/.openclaw/workspace/automation/knowledge-digest/
```

并由 `ai.openclaw.knowledge-digest` LaunchAgent 定期运行。本仓库只提供正式 CLI 与 `integrations/openclaw/` 薄 adapter，不复制 worker 的队列、lock 和状态实现。

## 背景

Digest workflow 是 local-first、单机运行的日常任务。它的可靠性问题集中在重试、状态报告、中断处理和 lock 恢复，而不是分布式吞吐量。这些问题可以由本地 worker 解决，无需引入分布式 task system。

## 决策

保留 `launchd + local queue worker` 架构，不为这套单机工作流引入 Celery 或 broker。

Worker 负责：

- 接收并保留排队请求；
- 防止同一时间重叠运行；
- 记录可观察状态；
- 处理 lock 和中断恢复；
- 调用本仓库正式 `yt-video2knowledge` CLI。

## 考虑过的替代方案

### Celery + broker

- **优点**：内建 task queue、retry 和 worker 隔离概念。
- **缺点**：增加 broker 部署、监控、恢复和更多 failure mode。
- **不采用原因**：当前没有分布式 worker 或跨机器调度需求。

### 只手动运行 Digest CLI

- **优点**：操作表面最小。
- **缺点**：把无人值守运行、排队、状态和中断恢复全部交给操作者。
- **不采用原因**：日常工作流需要可观察的自动执行。

## 影响

### 正面

- 保持本机架构小而可理解。
- 避免引入 broker 的维护成本。
- 可以集中解决已知的 retry、status 和 lock 问题。

### 负面

- 本地 worker 必须明确实现 queue、lock 和状态协议。
- 这套架构不为多机扩展做准备。

### 风险

- 仓库与仓库外 worker 可能产生 interface drift。通过只调用正式 CLI、维护 adapter smoke test 和清楚记录边界来缓解。

## 相关资料

- [项目地图](../guides/project-map.md)
- [仓库 Skill 的 OpenClaw 运行规则](../../SKILL.md)
- [ADR-0004：让 worker 中断安全](0004-make-worker-interruption-safe.md)
- [ADR-0005：不强制重启运行中的 worker](0005-do-not-force-restart-running-worker.md)
