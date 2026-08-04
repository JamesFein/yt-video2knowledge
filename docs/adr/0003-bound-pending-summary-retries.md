# ADR-0003：限制 Pending-summary Video 的重试

- **日期**：2026-06-11
- **状态**：accepted
- **决策者**：User、Codex

## 当前适用范围

本决策已落实在 `digest.summary` 和 `digest.run`。模型请求、输出校验、重试次数、时间窗口、错误分类和 `summary_retry` metadata 都由正式 package 维护。

## 背景

`IncompleteRead`、空响应、结构不完整或临时 provider 故障可能让单个视频停留在 Pending-summary。重跑整天会浪费已经完成的 Transcript 和 Video Summary；无限重试又会持续消耗时间和 API budget。

## 决策

只重试失败或 Pending-summary 的摘要步骤，不重新处理成功视频，也不默认重新获取 Transcript。

自动重试同时受以下边界限制：

- attempt count；
- retry window；
- retriable / non-retriable error classification；
- 每次运行允许的 inline attempt 数量。

达到停止条件后，视频保留为可诊断的 Pending-summary 状态，并在 `summary_retry` 中记录 `stopped_reason`、`last_error` 和面向人工处理的 `next_step`。显式 `--force-summary-retry` 只允许额外的有界尝试，不把系统变成无限重试。

## 考虑过的替代方案

### 重跑整个 Target Date

- **优点**：操作模型简单。
- **缺点**：重复处理成功视频，并可能重新下载或转写。
- **不采用原因**：manifest 和单视频产物已经能精确定位待处理项。

### 永久重试

- **优点**：提高最终自动成功的机会。
- **缺点**：可能持续消耗 API 调用，让 Digest Run 永久悬而未决。
- **不采用原因**：本工作流需要有边界的自动化和明确人工接管点。

### 完全手动重试

- **优点**：不会自动消耗额外 API budget。
- **缺点**：普通临时故障也需要人工介入。
- **不采用原因**：常见 transient failure 应自动恢复。

## 影响

### 正面

- 保留成功的 Transcript 和摘要。
- 减少重复下载、ASR 和模型调用。
- Retry 状态可以被 manifest、CLI 和测试观察。

### 负面

- 需要保存 attempt、时间和 error classification。
- 人工恢复必须理解 `summary_retry` metadata。

### 风险

- Error classification 可能不完美。通过小而明确的分类、保留错误 metadata 和显式 force retry 来缓解。

## 相关资料

- [`digest/summary.py`](../../src/yt_video2knowledge/digest/summary.py)
- [`digest/run.py`](../../src/yt_video2knowledge/digest/run.py)
- [ADR-0002：以 manifest 作为完成权威](0002-use-manifest-as-completion-authority.md)
