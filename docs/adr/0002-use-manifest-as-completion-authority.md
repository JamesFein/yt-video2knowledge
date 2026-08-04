# ADR-0002：以 manifest 作为完成状态的权威

- **日期**：2026-06-11
- **状态**：accepted
- **决策者**：User、Codex

## 当前适用范围

本决策已落实在 `src/yt_video2knowledge/digest/manifest.py` 和 CLI 退出码语义中。`manifest.json` 仍是判断 Digest Run 业务完成状态的权威；进程退出码只是调用层信号。

## 背景

Digest 进程可能完成一次命令执行，但仍有视频处于 Pending-summary 或 Transcript-failed 状态。如果只看进程是否正常退出，就会把 partial result 错报为完整成功。

## 决策

以 Digest Run manifest 判断是否完成。只有同时满足下面两个条件，Digest Run 才是 Completed Digest Run：

```text
failed_count = 0
pending_summary_count = 0
```

存在失败或待总结视频时，CLI 应保留产物、完成目标日期同步，并用 partial exit code 表达仍需恢复或人工检查。

## 考虑过的替代方案

### 只看进程退出码

- **优点**：调用方检查简单。
- **缺点**：无法区分命令完成与所有视频完成。
- **不采用原因**：会隐藏 manifest 中的 partial business failure。

### 只看输出文件是否存在

- **优点**：可以直接检查 filesystem。
- **缺点**：不能可靠表达每个视频的状态、失败原因和数量。
- **不采用原因**：manifest 已经提供结构化状态。

## 影响

### 正面

- 用户看到的完成状态与实际内容一致。
- Retry 可以只处理未完成视频。
- CLI、worker 和测试共享同一个完成不变量。

### 负面

- 调用方必须解析并信任 manifest。
- 缺失或 malformed manifest 必须被视为非成功状态，并通过恢复路径处理。

### 风险

- Manifest schema drift 可能破坏完成判断。通过把判断集中在 `digest.manifest` 并用测试覆盖稳定字段来缓解。

## 相关资料

- [`digest/manifest.py`](../../src/yt_video2knowledge/digest/manifest.py)
- [`tests/digest/test_workflow.py`](../../tests/digest/test_workflow.py)
- [ADR-0003：限制 Pending-summary 重试](0003-bound-pending-summary-retries.md)
