# coding agent 的 Knowledge Site 部署规则

## 何时阅读

修改 Knowledge Site、运行会影响现有服务的测试、操作 FastAPI/Uvicorn，或诊断 Cloudflare Tunnel 前，先阅读本文。具体命令和完整操作步骤以 [Knowledge Site 当前部署运行手册](../operations/knowledge-site-deployment.md) 为唯一事实源。

## 当前 process manager

production 由两个 LaunchAgent 管理：

```text
top.miniaiheadlines.knowledge-site
top.miniaiheadlines.cloudflared
```

不要把历史 `screen` 会话、临时前台 Uvicorn 或 Quick Tunnel 当成当前主部署方式。OpenClaw 的 `ai.openclaw.knowledge-digest` 是内容任务 worker，不属于网站部署。

## 操作前必须检查

```bash
launchctl print gui/$(id -u)/top.miniaiheadlines.knowledge-site
launchctl print gui/$(id -u)/top.miniaiheadlines.cloudflared
lsof -nP -iTCP:8000 -sTCP:LISTEN || true
ps axww -o pid=,comm=,args= | awk '$2 ~ /(^|\/)cloudflared$/ {print}'
```

停止健康 listener 前，必须先确认：

- `~/.config/knowledge-site/env` 存在且可读；
- `~/.config/knowledge-site/cloudflared-token` 存在且可读；
- 两个 plist 路径和 label 与当前部署一致；
- 任务确实需要重启，而不是只需要同步数据；
- 目标是网站 job，不是正在处理视频的 OpenClaw worker。

只允许报告 secret 文件和变量为 `present` 或 `missing`，不得读取或输出真实值。

## 最小变更原则

- Python 应用代码变化：只重启 `top.miniaiheadlines.knowledge-site`。
- Tunnel connector 配置变化：只重启 `top.miniaiheadlines.cloudflared`。
- 只同步新内容：不要重启网站或 Tunnel。
- 只读诊断：不要改变任何 job 状态。
- 不要为了“确保干净”同时杀死 Uvicorn、cloudflared 和 OpenClaw worker。

不要使用 `pkill -f`、`pgrep -f` 或模糊的 `ps | rg` 作为清理手段。这些模式可能匹配日志、工具命令或其他 agent 进程。

## 重启规则

预检通过后，才可以重启精确目标：

```bash
launchctl kickstart -k gui/$(id -u)/top.miniaiheadlines.knowledge-site
```

只有 connector 本身异常时才运行：

```bash
launchctl kickstart -k gui/$(id -u)/top.miniaiheadlines.cloudflared
```

绝不能对正在工作的 `ai.openclaw.knowledge-digest` 使用 `launchctl kickstart -k`。先排队、查看状态并等待当前任务自然结束。

## 验证契约

本应用的健康检查使用 `GET`，不是 `HEAD`：

```bash
curl -sS -o /tmp/knowledge-site-local.html -w '%{http_code}\n' --max-time 5 http://127.0.0.1:8000/
curl -sS -o /tmp/knowledge-site-root.html -w '%{http_code}\n' --max-time 10 https://miniaiheadlines.top/
curl -sS -o /tmp/knowledge-site-www.html -w '%{http_code}\n' --max-time 10 https://www.miniaiheadlines.top/
```

未登录时预期 `303` 到登录流程。完成操作前必须再次确认：

- 两个 LaunchAgent 的最终状态；
- 8000 最多一个 listener；
- 没有重复或临时 Quick Tunnel；
- 本机和两个公网 hostname 的 GET；
- 对应错误日志没有新的崩溃循环。

最终回复要明确服务是“保持运行”还是“已停止”，不能只报告测试通过。
