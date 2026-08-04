# Knowledge Site 当前部署运行手册

本文是 Knowledge Site 日常启动、停止、重启、查看日志和验证公网访问的唯一运行手册。Coding Agent 在改变服务状态前还必须阅读 [部署安全规则](../agents/knowledge-site-deployment.md)；代码和浏览器验收见 [Site 验收规则](../agents/knowledge-site-validation.md)。Cloudflare DNS 与 Published application 的首次配置见 [Cloudflare Tunnel 配置说明](cloudflare-public-hostname.md)。

## 当前结论

Knowledge Site 的 production 部署运行在这台 Mac 上，并由两个 `launchd` LaunchAgent 持久维护：

| 角色 | LaunchAgent label | plist | 日志 |
| --- | --- | --- | --- |
| FastAPI/Uvicorn | `top.miniaiheadlines.knowledge-site` | `~/Library/LaunchAgents/top.miniaiheadlines.knowledge-site.plist` | `~/Library/Logs/knowledge-site/uvicorn.out.log`、`uvicorn.err.log` |
| Cloudflare Tunnel connector | `top.miniaiheadlines.cloudflared` | `~/Library/LaunchAgents/top.miniaiheadlines.cloudflared.plist` | `~/Library/Logs/knowledge-site/cloudflared.out.log`、`cloudflared.err.log` |

两个公网入口是：

```text
https://miniaiheadlines.top
https://www.miniaiheadlines.top
```

日常优先使用 `https://miniaiheadlines.top`。两个 hostname 都通过 Named Tunnel `knowledge-site-mac` 转发到：

```text
http://127.0.0.1:8000
```

前端不是独立进程。FastAPI 同时提供 Jinja2 页面、CSS、JavaScript、站内 API 和同步后的 assets。

## 部署链路

```text
公网浏览器
  -> Cloudflare Edge
  -> Named Tunnel: knowledge-site-mac
  -> 本机 cloudflared LaunchAgent
  -> http://127.0.0.1:8000
  -> Uvicorn / FastAPI LaunchAgent
  -> data/knowledge.sqlite3 + data/knowledge-assets/
```

`cloudflared` 主动从 Mac 建立出站 Tunnel。Mac 关机、断网、任一 LaunchAgent 失效或本机 8000 origin 不健康时，公网网站都会受到影响。

## 外部配置与 secret

LaunchAgent 使用两份仓库外文件：

```text
~/.config/knowledge-site/env
~/.config/knowledge-site/cloudflared-token
```

第一份提供 Knowledge Site 的环境变量，至少包括：

```text
KNOWLEDGE_SITE_PASSWORD
KNOWLEDGE_SITE_SECRET_KEY
KNOWLEDGE_SITE_COOKIE_DOMAIN
```

第二份保存 Cloudflare remotely-managed tunnel token。只能检查文件是否存在和可读，不能打印内容：

```bash
test -r ~/.config/knowledge-site/env && echo 'knowledge-site env: present' || echo 'knowledge-site env: missing'
test -r ~/.config/knowledge-site/cloudflared-token && echo 'cloudflared token file: present' || echo 'cloudflared token file: missing'
```

不要把真实密码、session secret、connector token 或文件内容复制到仓库、聊天、日志或命令行参数。

## 日常状态检查

### 1. 检查 LaunchAgent

```bash
launchctl print gui/$(id -u)/top.miniaiheadlines.knowledge-site
launchctl print gui/$(id -u)/top.miniaiheadlines.cloudflared
```

健康状态应满足：

- 两个 job 都已加载；
- `state = running`；
- Knowledge Site 只有一个进程监听 `127.0.0.1:8000`；
- `cloudflared` 的进程参数是 `tunnel run --token-file ...`。

### 2. 检查端口和精确进程

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN || true
ps axww -o pid=,comm=,args= | awk '$2 ~ /(^|\/)cloudflared$/ {print}'
```

不要使用宽泛的 `pgrep -f`、`pkill -f` 或 `ps | rg` 来停止服务。工具命令、日志或其他 agent 进程也可能包含相同字符串。

### 3. 检查日志

```bash
tail -n 100 ~/Library/Logs/knowledge-site/uvicorn.err.log
tail -n 100 ~/Library/Logs/knowledge-site/cloudflared.err.log
```

需要持续观察时使用：

```bash
tail -f ~/Library/Logs/knowledge-site/uvicorn.err.log
tail -f ~/Library/Logs/knowledge-site/cloudflared.err.log
```

## 健康验证

应用健康检查使用 `GET`，不要使用 `HEAD /`；当前 FastAPI route 可以对 `HEAD` 返回 `405`。

```bash
curl -sS -o /tmp/knowledge-site-local.html -w '%{http_code}\n' --max-time 5 http://127.0.0.1:8000/
curl -sS -o /tmp/knowledge-site-root.html -w '%{http_code}\n' --max-time 10 https://miniaiheadlines.top/
curl -sS -o /tmp/knowledge-site-www.html -w '%{http_code}\n' --max-time 10 https://www.miniaiheadlines.top/
```

未登录访问 `/` 时，正常结果是 `303` 并跳转到 `/login?next=/`。这说明应用和认证入口可用，不是错误。

验证顺序固定为：

```text
本机 127.0.0.1:8000
  -> cloudflared LaunchAgent
  -> Cloudflare Tunnel
  -> miniaiheadlines.top
```

本机失败时先修 FastAPI；本机成功而公网失败时，才继续检查 Tunnel 和 Cloudflare 配置。

## 启动已经加载的 job

如果 LaunchAgent 已加载但当前没有运行，先确认外部配置存在，再启动：

```bash
launchctl kickstart gui/$(id -u)/top.miniaiheadlines.knowledge-site
launchctl kickstart gui/$(id -u)/top.miniaiheadlines.cloudflared
```

等待几秒后重新运行状态、端口、日志和 GET 验证。不要只因为 `kickstart` 返回成功就报告网站已经恢复。

## 有控制地重启

只有以下情况需要重启对应服务：

- Python 应用代码或 app 配置发生变化：重启 Knowledge Site job；
- Tunnel token、connector 配置或 `cloudflared` 状态异常：重启 cloudflared job；
- 仅同步新数据：通常不需要重启任何 job。

重启前必须确认：

1. 两份外部配置文件存在且可读；
2. 当前 plist 路径和 label 正确；
3. 已记录重启前本机和公网状态；
4. 没有把 OpenClaw Digest worker 误认成网站进程。

确认后只重启目标 job：

```bash
launchctl kickstart -k gui/$(id -u)/top.miniaiheadlines.knowledge-site
```

只有 connector 本身需要重启时才运行：

```bash
launchctl kickstart -k gui/$(id -u)/top.miniaiheadlines.cloudflared
```

重启后检查 `launchctl print`、8000 listener、错误日志以及本机/公网 GET。

`launchctl kickstart -k` 不得用于 `ai.openclaw.knowledge-digest`：它可能正在处理长视频，强制重启会打断进行中的 Digest Run。

## job 未加载时恢复

如果 `launchctl print` 返回找不到服务，但 plist 仍存在，可以重新加载：

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/top.miniaiheadlines.knowledge-site.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/top.miniaiheadlines.cloudflared.plist
```

然后使用 `launchctl print` 和 GET 验证。`bootstrap` 报“service already loaded”时，不要重复加载；改为检查或 `kickstart` 现有 job。

如果 plist 或外部配置缺失，不要临时拼接包含 secret 的新命令。先恢复正确文件或向用户确认配置来源。

## 停止部署

因为两个 job 都配置了 `KeepAlive`，直接 `kill` 进程会被 `launchd` 再次拉起。要让服务保持停止，应卸载准确的 job：

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/top.miniaiheadlines.knowledge-site.plist
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/top.miniaiheadlines.cloudflared.plist
```

停止后验证：

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN || true
ps axww -o pid=,comm=,args= | awk '$2 ~ /(^|\/)cloudflared$/ {print}'
```

停止公网部署会影响真实用户访问。除非任务明确要求，不要为了跑测试或阅读代码而停止健康服务。

## 开发时手动前台运行

下面的命令只用于开发、诊断或 LaunchAgent 不可用时的临时验证，不是 production 的主启动方式：

```bash
cd /Users/administrator/projects/yt-video2knowledge
set -a
source ~/.config/knowledge-site/env
set +a
uv run uvicorn yt_video2knowledge.site.app:create_app --factory --host 127.0.0.1 --port 8000
```

不要在 production LaunchAgent 已监听 8000 时再启动第二个 Uvicorn。前台进程结束后，应恢复并验证 LaunchAgent 状态。

Quick Tunnel 也只用于临时测试：

```bash
cloudflared tunnel --url http://127.0.0.1:8000 --protocol http2
```

Quick Tunnel 使用随机 hostname，不替代 `knowledge-site-mac`。测试结束后停止它，并确认固定域名仍由 `top.miniaiheadlines.cloudflared` 提供。

## 登录与使用

1. 打开 `https://miniaiheadlines.top`。
2. 使用 `KNOWLEDGE_SITE_PASSWORD` 对应的共享密码登录。
3. 首页按 Target Date 倒序显示已同步日期。
4. 日期页显示当天的 Summary-ready Video。
5. 视频页允许选择 summary block，并写入、编辑和保存 Meta Summary。

Session cookie 最长有效 15 天，但依赖：

- `KNOWLEDGE_SITE_SECRET_KEY` 长期保持不变；
- `KNOWLEDGE_SITE_COOKIE_DOMAIN='.miniaiheadlines.top'`；
- 浏览器没有清理 cookie；
- 日常固定使用同一主域名。

Secret 变化后旧 session 立即失效是正常安全行为。

## 按现象排查

| 现象 | 第一检查点 | 下一步 |
| --- | --- | --- |
| 本机 8000 不通 | Knowledge Site LaunchAgent 与 Uvicorn 日志 | 外部 env 文件、package import、端口占用 |
| 本机正常，公网不通或 530 | cloudflared LaunchAgent 与日志 | Tunnel health、Published application、DNS |
| 网站能开但没有新内容 | 目标日期 manifest | `yt-video2knowledge sync-site` 输出和 SQLite |
| 登录循环或频繁失效 | 固定 secret 与 cookie domain | 是否混用根域名、`www`、Quick Tunnel |
| Meta Summary 保存失败 | 登录 session 和浏览器请求 | `/api/v1/...` 响应与 SQLite 写入 |
| 重启后短暂成功又退出 | `launchctl print` 的退出码 | 对应 `.err.log` 和外部配置可读性 |

## 完成操作前的验收

- [ ] 两个目标 LaunchAgent 状态明确：都在运行，或按请求都已停止。
- [ ] `127.0.0.1:8000` 最多只有一个 listener。
- [ ] 没有多余 Quick Tunnel 或重复 cloudflared connector。
- [ ] 本机 GET 状态符合预期。
- [ ] 根域名和 `www` 公网 GET 状态符合预期。
- [ ] 错误日志没有新的持续崩溃循环。
- [ ] 没有输出、记录或提交任何 secret。
