# coding agent 的 Knowledge Site 部署规则

## 何时阅读

操作 FastAPI/Uvicorn、LaunchAgent、Cloudflare Tunnel，运行会影响现有服务的测试，或诊断公网部署前，先阅读本文。具体命令、当前 endpoint 和恢复步骤以 [Knowledge Site 当前部署运行手册](../operations/knowledge-site-deployment.md) 为唯一事实源；代码与浏览器验收规则见 [Knowledge Site 变更与浏览器验收](knowledge-site-validation.md)。

## 目标边界

- 网站 production 由 `top.miniaiheadlines.knowledge-site` 与 `top.miniaiheadlines.cloudflared` 两个 LaunchAgent 管理。
- `ai.openclaw.knowledge-digest` 是内容任务 worker，不属于网站部署；绝不能为了网站操作强制重启它。
- 历史 `screen`、临时前台 Uvicorn 和 Quick Tunnel 都不是当前主部署方式。

## 状态变更前必须检查

停止健康 listener 前，必须先确认：

- 用户请求确实授权改变服务状态，只读诊断不得顺手重启；
- 所需环境、secret 文件和 plist 存在且可读，但只报告 `present` 或 `missing`；
- LaunchAgent label、process manager、端口 listener 和目标进程身份与运行手册一致；
- 任务确实需要重启，而不是只需要同步数据；
- 目标是网站 job，不是正在处理视频的 OpenClaw worker。

## 最小变更原则

- Python 应用代码变化：只重启 `top.miniaiheadlines.knowledge-site`。
- Tunnel connector 配置变化：只重启 `top.miniaiheadlines.cloudflared`。
- 只同步新内容：不要重启网站或 Tunnel。
- 只读诊断：不要改变任何 job 状态。
- 不要为了“确保干净”同时杀死 Uvicorn、cloudflared 和 OpenClaw worker。

不要使用 `pkill -f`、`pgrep -f` 或模糊的 `ps | rg` 识别或清理服务；它们可能匹配日志、工具命令或其他 agent 进程。所有状态变更必须使用运行手册中的精确目标和命令。

## 验证契约

本应用的健康检查使用 `GET`，不是 `HEAD`；未登录时预期 `303` 到登录流程。启动或重启命令返回成功不等于服务已经恢复，必须等待并再次确认：

- 两个 LaunchAgent 的最终状态；
- 8000 最多一个 listener；
- 没有重复或临时 Quick Tunnel；
- 本机和两个公网 hostname 的 GET；
- 对应错误日志没有新的崩溃循环。

最终回复要明确服务是“保持运行”还是“已停止”，不能只报告测试通过。
