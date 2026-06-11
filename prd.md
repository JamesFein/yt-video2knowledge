# OpenClaw Knowledge Digest 稳定性改进方案

## 解决方案

保持现有 `launchd + 本地 queue worker` 架构，不引入 Celery。当前 workflow 是单机、本地优先、每天一次的 digest 任务，问题可以通过增强现有 worker 的重试、状态和锁处理解决，不需要引入分布式队列系统。

为摘要生成增加有限自动重试。单个视频总结失败后，只重试该视频的总结步骤，不重新抓取整天视频、不重跑已成功的视频。重试使用退避间隔，例如：

```text
第 1 次失败 -> 等 30 秒后重试
第 2 次失败 -> 等 2 分钟后重试
第 3 次失败 -> 等 5 分钟后重试
仍失败 -> 标记为 pending_summary，交给整日补跑机制
```

整日任务结束后，如果 manifest 中仍有 `pending_summary`，worker 自动触发一次只针对 pending 视频的补跑，相当于运行 `--retry-summaries`。如果补跑仍未清零，则后续按更长间隔继续补跑，例如 10 分钟、1 小时、下一次 daily worker tick。

自动重试必须有停止条件，避免无限消耗 API 和让任务永远处于未完成状态。建议停止条件为：

```text
同一个视频总结最多尝试 5 次
或超过 24 小时仍未成功
或错误明显不是临时问题，例如凭据失效、配置错误、参数错误
```

达到停止条件后，不再自动重试该视频，保留可诊断状态，并将其标记为 `needs_review` 或继续保留为带错误原因的 `pending_summary`。

worker 收到 SIGTERM/SIGINT 时执行中断保护。中断保护的目标是避免出现“进程已经死了，但状态还显示 running，锁还留着”的假运行状态。worker 被中断时应执行以下收尾：

```text
1. 记录当前任务被 interrupted
2. 将状态从 running 改为 idle / interrupted
3. 释放 worker lock
4. 保留未完成请求，不把它当作成功处理
5. 下一次 worker 启动时继续处理该请求
```

lock 中写入 `pid`、`started_at` 和 `heartbeat`。`show_status.py` 查询状态时应检查 lock 里的进程是否仍然存活，以及 heartbeat 是否过期。如果进程不存在或 heartbeat 长时间未更新，应报告 stale lock，并允许 worker 安全恢复，不再只根据 lock 文件存在就认为任务仍在运行。

OpenClaw 只负责入队和查看状态，不直接强制重启正在执行的 worker。禁止用 `launchctl kickstart -k` 强制重启执行中的 worker，因为 `-k` 会先杀掉旧进程，容易打断正在运行的 digest。正确操作是：

```text
1. 使用 queue_request.py 入队目标日期
2. 使用 show_status.py 查看状态
3. 等待 launchd 的 5 分钟 tick 接单
4. 如需排障，先确认 worker 未在运行，再做重启操作
```

成功标准改为以 manifest 结果为准，而不是只看进程 exit code。一次目标日期处理只有在满足以下条件时才算完成：

```text
failed_count = 0
pending_summary_count = 0
```

如果进程 exit code 为 0，但 manifest 里仍有 `pending_summary`，这次运行只能算“部分成功，需要补跑”，不能向用户报告为完全成功。

## 测试方案

### 测试原则

测试沿用本仓库当前风格：使用 `unittest`、`unittest.mock`、`tempfile` 和临时文件树组织测试，不要求迁移到 pytest，也不引入 freezegun。每个测试按 Arrange / Act / Assert 思路描述和实现：先布置临时 run 目录、假 manifest、假状态文件、假 API 客户端或假进程，再执行目标行为，最后断言外部可见结果。

测试应验证外部行为，不断言私有实现细节。重点断言 manifest 计数、状态文件内容、锁是否存在、请求是否保留、重试次数、被处理的视频 ID、用户可看到的 status 输出，以及最终命令可通过项目现有测试入口运行。

测试必须隔离真实环境。测试不能访问真实 YouTube、OpenAI、launchd、`.openclaw` 生产目录或真实 worker 状态；不能真实 sleep；不能依赖当前时间自然流逝。所有网络、LLM/API、时间、进程、信号和文件系统路径都应通过假对象、mock、临时目录或可注入依赖控制。

测试数据要小而明确。默认使用 1 到 3 个视频验证单个行为；只有回归场景使用 27 个视频和 2 个 pending 的结构，以贴近 2026-06-09 的实际事故形态。

### 测试范围与组织

摘要重试策略测试放在现有 digest 相关测试附近，优先复用 `tests/test_knowledge_digest.py` 的风格，使用临时目录和 mock 客户端验证“只重试失败视频”和“达到上限后停止”。

worker、lock、status 的测试应覆盖 queue worker 的核心行为。如果 worker 仍位于 `.openclaw` 外部，先将可测试的核心逻辑抽成可导入模块，或在 automation 代码旁建立同风格测试；不要让测试直接读写真实 `.openclaw/workspace/automation/knowledge-digest/state`。

Knowledge Site API 和 template 测试不是本 PRD 的重点，除非实现改动影响 digest 完成后同步到站点的可见结果。否则现有 `tests/test_knowledge_site_api.py` 和 template 相关测试不需要扩展。

### 单元测试场景

临时 LLM/API 错误会重试并最终成功。使用假 summary client 让同一个视频前几次返回 `IncompleteRead`、空响应或 bad response，最后一次返回成功结果；断言调用次数等于失败次数加最终成功次数，最终状态为 `summary_ready`，错误字段被清空。

临时错误达到最大尝试次数后停止。让假 summary client 持续返回同一种可重试错误；断言系统在最大次数后停止，不再继续调用，视频仍保留为 `pending_summary` 或转为 `needs_review`，并记录最后错误原因、尝试次数和最后失败时间。

超过 24 小时窗口后停止自动重试。使用可控时钟布置第一次失败时间和当前时间；断言超过窗口后不会继续自动补跑，并保留可诊断状态。

不可重试错误不会进入退避重试。模拟凭据失效、配置错误或参数错误；断言只尝试一次，立即停止，并把错误标记为需要人工处理。

退避策略不真实等待。测试只验证下一次重试应被安排到正确的间隔，或验证 sleep/clock 被假对象接管；测试运行时不应因为 30 秒、2 分钟、5 分钟策略而变慢。

成功视频不被重复处理。布置 manifest 中同时包含 `summary_ready`、`pending_summary` 和新视频；执行补跑选择逻辑后，断言只有 pending 或需要重试的视频进入处理列表，已成功视频被跳过。

exit code 0 但仍有 pending 时不算完全成功。布置一个返回成功退出码但 manifest 中 `pending_summary_count` 大于 0 的结果；断言 worker 或状态汇总把它标记为 partial / needs retry，而不是最终 success。

### 集成测试场景

整日任务结束后自动补跑 pending summary。布置一个目标日期 run 目录，首次 manifest 中有部分视频 `summary_ready`、部分视频 `pending_summary`；执行 worker 的日任务完成流程；断言系统触发等价于 `--retry-summaries` 的补跑路径，并且只处理 pending 视频。

补跑成功后 manifest 计数清零。首次运行产生 pending，补跑返回成功摘要；断言最终 manifest 中 `failed_count = 0`、`pending_summary_count = 0`、所有目标视频为 `summary_ready`，并且状态记录为完成。

补跑仍失败后保留可诊断状态。让补跑继续遇到可重试错误直到达到上限；断言状态文件包含 target date、失败视频 ID、最后错误、尝试次数、最后失败时间和下一步人工处理信号。

worker 收到 SIGTERM/SIGINT 时执行中断保护。布置正在运行的 current job、request 文件和 lock；模拟终止信号；断言状态从 `running` 变为 `interrupted` 或 `idle`，lock 被释放，请求没有被归档为成功，也没有被删除。

中断后下一次 worker 能继续。沿用上一个中断后的状态再次启动 worker；断言它能重新识别未完成请求并继续处理，而不是因为残留状态跳过任务。

worker 不会释放别人的活锁。布置 lock 中 PID 仍存活且 heartbeat 未过期；启动第二个 worker；断言第二个 worker 不接管、不删除 lock、不修改 current job。

stale lock 会被识别并恢复。布置 lock 存在但 PID 不存在，或 heartbeat 已过期；执行 status 查询或 worker 启动逻辑；断言输出明确报告 stale lock，worker 可以安全清理并恢复接单。

status 输出能区分 running、interrupted、partial、success 和 stale lock。分别布置这些状态文件和 lock 组合；断言 `show_status.py` 的用户可见输出能让操作者判断下一步是等待、补跑、清理还是人工处理。

### 回归测试场景

复现 2026-06-09 的部分失败。布置 27 个视频，其中 25 个 `summary_ready`，2 个 `pending_summary`，错误分别模拟网络读断和 API bad response；执行补跑流程；断言只补跑这 2 个视频，最终 `failed_count = 0` 且 `pending_summary_count = 0`。

复现 2026-06-10 的 worker 启动后被中断。布置一个 request 任务刚开始写入日志和 running 状态、尚未写出 manifest 和 exit code；模拟 worker 被 SIGTERM 打断；断言不会留下假 running，lock 被释放，请求保留，下次 worker 可以继续。

复现“进程退出码成功但业务未完成”。布置 exit code 0 且 manifest 中仍有 pending summary；断言系统不会向用户报告完全成功，而是进入补跑或 partial 状态。

### 测试数据与替身

使用临时目录构造 `data/runs/YYYY-MM-DD`、`manifest.json`、视频子目录、状态文件、request 文件和 lock 文件。测试结束后由临时目录自动清理，不污染仓库和真实 OpenClaw 工作区。

使用假 LLM/API 客户端控制返回序列：先失败后成功、一直失败、不可重试失败。测试只验证调用次数和最终状态，不触碰真实 API。

使用假 clock 控制 `started_at`、`heartbeat`、最后失败时间和 24 小时窗口，避免依赖真实时间。

使用假 process runner 控制 digest 命令的返回码、输出 manifest、运行中断和 signal 行为，避免启动真实长任务。

使用小型 manifest fixture 覆盖 `summary_ready`、`pending_summary`、`failed`、`needs_review`、缺少 summary 文件、缺少 transcript 等常见组合。

### 验收标准

同一天最终成功只以 manifest 中 `failed_count = 0` 且 `pending_summary_count = 0` 为准。

LLM/API 临时错误会被有限重试；达到次数、时间窗口或不可重试错误条件后会停止。

补跑只处理失败或 pending 的视频，不重复处理已成功视频。

worker 被中断后不会留下脏锁、假 running 或被误删的请求。

stale lock 能被识别，活锁不会被误清理。

状态输出能让操作者区分等待、补跑、人工处理和异常恢复。

所有新增或调整的测试都能通过项目现有命令 `uv run python3 -m unittest discover -s tests` 运行。

## 假设

这是单机、本地优先、每天一次的 digest workflow。

当前不需要多 worker、多机器、复杂任务优先级或分布式队列。

LLM/API 的 `IncompleteRead`、空响应、bad response 等属于可重试临时错误。

凭据失效、配置错误、参数错误等属于不可自动重试错误，应尽快停止并提示人工处理。
