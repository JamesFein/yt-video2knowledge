# ADR-0005：不强制重启正在运行的 worker

- **日期**：2026-06-11
- **状态**：accepted
- **决策者**：User、Codex

## 当前适用范围

本决策只针对处理长时间 Digest 任务的 `ai.openclaw.knowledge-digest`。Knowledge Site 和 cloudflared 使用另外两个 LaunchAgent；它们是否需要重启，应遵循独立的部署预检规则。

## 背景

`launchctl kickstart -k` 会先终止旧进程再启动新进程。对正在工作的 Digest worker 使用它，会中断下载、ASR 或摘要生成，并可能制造本稳定性工作原本要避免的 partial state 和 lock 问题。

## 决策

OpenClaw 应排队 Digest 请求并读取 worker 状态，而不是强制重启 active worker。

安全操作顺序是：

1. 提交 Target Date 请求；
2. 检查 queue 和 worker 状态；
3. 等待正常的 `launchd` tick；
4. 只有确认没有 active worker 时，才考虑人工恢复或重启。

## 考虑过的替代方案

### 使用 `launchctl kickstart -k` 立即重启

- **优点**：服务看起来异常时可以立即触发一次新进程。
- **缺点**：会杀死正在处理的任务，并留下 partial state。
- **不采用原因**：对长时间 Digest Run 不安全。

### 让 OpenClaw 直接控制 worker lifecycle

- **优点**：UI 或工具拥有更多直接控制能力。
- **缺点**：把 request submission 与 process management 耦合，更容易误伤 active work。
- **不采用原因**：enqueue 和 status inspection 已足够满足本地工作流。

## 影响

### 正面

- 降低 active Digest Run 被意外中断的概率。
- OpenClaw 职责保持为 enqueue 和 observe。
- 操作决策以真实状态为依据。

### 负面

- 新请求可能需要等待下一次 `launchd` interval。
- Emergency restart 仍然需要人工判断。

### 风险

- 操作者可能沿用“卡住就强制 kickstart”的习惯。通过 agent 规则、运行手册和状态输出持续强调本决策。

## 相关资料

- [ADR-0001：使用 launchd 和本地 queue worker](0001-use-launchd-local-queue-worker.md)
- [ADR-0004：让 worker 中断安全](0004-make-worker-interruption-safe.md)
- [coding agent 的 Knowledge Site 部署规则](../agents/knowledge-site-deployment.md)
- [仓库 Skill 的 OpenClaw 运行规则](../../SKILL.md)
