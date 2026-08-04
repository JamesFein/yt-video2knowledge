# Architecture Decision Records

ADR 记录已经形成的架构决策、当时背景、替代方案和后果。`accepted` 表示当前仍然有效；后续改变决策时，应新增 ADR 并把旧记录标记为 `superseded`，而不是删除历史。

| ADR | 决策 | 状态 | 日期 |
| --- | --- | --- | --- |
| [0001](0001-use-launchd-local-queue-worker.md) | 使用 launchd 和本地 queue worker，而不是 Celery | accepted | 2026-06-11 |
| [0002](0002-use-manifest-as-completion-authority.md) | 以 manifest 作为完成状态的权威 | accepted | 2026-06-11 |
| [0003](0003-bound-pending-summary-retries.md) | 限制 Pending-summary Video 的重试 | accepted | 2026-06-11 |
| [0004](0004-make-worker-interruption-safe.md) | 让 queue worker 的中断可安全恢复 | accepted | 2026-06-11 |
| [0005](0005-do-not-force-restart-running-worker.md) | 不强制重启正在运行的 worker | accepted | 2026-06-11 |

创建新记录时复制 [ADR 模板](template.md)，使用下一个连续编号，并链接真实 Issue、PRD、代码或相关 ADR。
