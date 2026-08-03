# Knowledge Site 当前部署使用说明

本文说明当前 FastAPI 知识站通过 Cloudflare Named Tunnel + 固定域名部署后如何使用、如何停止/重启，以及为什么当前推荐保持两个核心进程。

## 当前访问入口

当前固定公网入口是：

```text
https://miniaiheadlines.top
https://www.miniaiheadlines.top
```

推荐日常只使用主入口：

```text
https://miniaiheadlines.top
```

`www.miniaiheadlines.top` 只是备用入口。访问后会先进入登录页。登录密码来自启动时设置的 `KNOWLEDGE_SITE_PASSWORD`，不要把密码写进仓库文档里；如果忘记密码，停止服务后重新用新的环境变量启动即可。

## 关闭 Codex 后如何恢复服务

关闭 Codex、关闭终端、电脑重启或网络断开后，需要恢复两个进程：

```text
FastAPI / Uvicorn 应用 -> 监听 127.0.0.1:8000
cloudflared connector -> 连接 Cloudflare 的 knowledge-site-mac tunnel
```

### 1. 准备固定环境变量

建议把真实密码和固定 session secret 放在仓库外，例如：

```bash
mkdir -p ~/.config/knowledge-site
nano ~/.config/knowledge-site/env
```

文件内容示例：

```bash
KNOWLEDGE_SITE_PASSWORD='你的共享密码'
KNOWLEDGE_SITE_SECRET_KEY='一段长期固定的随机字符串'
KNOWLEDGE_SITE_COOKIE_DOMAIN='.miniaiheadlines.top'
```

注意：

- `KNOWLEDGE_SITE_SECRET_KEY` 必须长期固定。它一变，浏览器里原来的 15 天登录 cookie 会全部失效，用户就需要重新输入密码。
- `KNOWLEDGE_SITE_COOKIE_DOMAIN='.miniaiheadlines.top'` 让 `miniaiheadlines.top` 和 `www.miniaiheadlines.top` 共用同一个登录 cookie。
- 不要把真实密码、secret 或 Cloudflare token 写进仓库。

如果需要生成一个新的长期 secret，可以在终端运行：

```bash
python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
```

生成后保存好，以后重启继续使用同一个值。

### 2. 启动 FastAPI

在项目根目录运行：

```bash
cd /Users/administrator/projects/yt-video2knowledge
set -a
source ~/.config/knowledge-site/env
set +a
.venv/bin/uvicorn knowledge_site.main:create_app --factory --host 127.0.0.1 --port 8000
```

这个终端要保持打开。未登录访问本机首页时，正常会跳到登录页：

```bash
curl -i http://127.0.0.1:8000/ | sed -n '1,8p'
```

### 3. 启动 Cloudflare Tunnel connector

如果你还没有把 tunnel 安装成系统服务，关闭 Codex 后原来的前台 `cloudflared` 进程会消失。恢复方式：

1. 打开 Cloudflare Dashboard。
2. 进入 `Zero Trust -> Networks -> Connectors -> Cloudflare Tunnels`。
3. 打开 `knowledge-site-mac`。
4. 在 Connectors 区域添加/查看 connector token。
5. 在另一个终端用 `TUNNEL_TOKEN` 启动 named tunnel。

推荐用隐藏输入，避免 token 留在 shell history：

```bash
read -s TUNNEL_TOKEN
export TUNNEL_TOKEN
cloudflared tunnel run
unset TUNNEL_TOKEN
```

不要把 token 写进仓库。这个终端也要保持打开。

### 4. 验证固定域名

两个进程都启动后验证：

```bash
curl -I https://miniaiheadlines.top/
curl -I https://www.miniaiheadlines.top/
```

正常情况下会进入 Knowledge Site 登录流程；已登录浏览器会直接进入首页。

### 5. 登录 15 天有效的条件

代码中 session cookie 有效期是 15 天。要真正做到“同一个浏览器只输入一次密码，半个月内有效”，需要同时满足：

- 每次启动都使用同一个 `KNOWLEDGE_SITE_SECRET_KEY`。
- 公网固定域名部署时设置 `KNOWLEDGE_SITE_COOKIE_DOMAIN='.miniaiheadlines.top'`。
- 尽量固定使用 `https://miniaiheadlines.top`，不要在根域名、`www`、旧的 `trycloudflare.com` 地址之间来回切。
- 不要点击退出登录。
- 浏览器没有清理该站点 cookie。

如果只登录了 `miniaiheadlines.top`，再访问旧 Quick Tunnel 地址或其他 hostname，浏览器会把它当成另一个站点，仍然会要求重新登录。

## 登录后怎么使用

1. 打开公网地址。
2. 输入共享密码登录。
3. 首页 `/` 会按日期倒序展示已同步的知识日期。
4. 点击某一天进入 `/days/{date}`，查看当天已完成总结的视频列表。
5. 点击视频进入 `/videos/{video_id}`。
6. 在视频页左侧勾选 summary block。
7. 点击“写入 Meta Summary”，选中的纯文本会追加到右侧编辑区。
8. 可以继续手动编辑右侧内容。
9. 点击“保存”会调用 API，把整条 meta-summary 写入 SQLite。
10. 点击“清空”会把该视频的 meta-summary 保存为空字符串。

## 当前为什么需要两个进程

推荐的当前部署只需要两个核心进程：

```text
Python .../.venv/bin/uvicorn knowledge_site.main:create_app --factory --host 127.0.0.1 --port 8000
cloudflared tunnel run
```

它们分别负责：

- `Python ... uvicorn ...`：真正运行 FastAPI 应用的 Python/Uvicorn 进程，监听本机 `127.0.0.1:8000`。
- `cloudflared tunnel run`：Cloudflare Tunnel 客户端进程，负责把固定域名的公网 HTTPS 请求转发到本机 `http://127.0.0.1:8000`。

也就是说：

```text
公网浏览器
  -> Cloudflare miniaiheadlines.top
  -> cloudflared
  -> 127.0.0.1:8000
  -> FastAPI / Uvicorn
```

也可以用 `uv run uvicorn ...` 启动应用，但它会多一个 `uv` 父进程。`uv run` 适合首次确认依赖环境；长期运行时，直接调用 `.venv/bin/uvicorn` 更简单。

## 操作前检查

每次修改代码、跑完测试、启动或重启部署前，先确认当前进程状态：

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN || true
pgrep -x cloudflared || true
screen -ls | sed -n '/knowledge-site/p' || true
```

不要用宽泛的 `pkill -f cloudflared`、`pgrep -f cloudflared` 或 `pkill -f 8000` 做判断或清理。历史日志、agent 消息和工具进程里也可能出现这些字符串，容易误伤。

## 如何确认服务还在运行

本机端口检查：

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN || true
```

本机访问检查要使用 `GET`，不要用 `HEAD`；当前应用可以对 `HEAD /` 返回 `405`：

```bash
curl -sS -o /tmp/knowledge-site-local.html -w '%{http_code}\n' --max-time 5 http://127.0.0.1:8000/
```

公网访问检查：

```bash
curl -sS -o /tmp/knowledge-site-root.html -w '%{http_code}\n' --max-time 10 https://miniaiheadlines.top/
curl -sS -o /tmp/knowledge-site-www.html -w '%{http_code}\n' --max-time 10 https://www.miniaiheadlines.top/
```

未登录访问 `/` 正常应返回 `303`，并跳转到 `/login?next=/`。

最终进程状态必须二选一：

- 已停止：`127.0.0.1:8000` 没有监听进程，且没有精确名为 `cloudflared` 的进程。
- 已运行：`127.0.0.1:8000` 只有一个 Uvicorn/FastAPI 监听进程，且只有一个 `cloudflared tunnel run` named tunnel connector。

## 如何停止当前部署

先找精确进程：

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN || true
ps axww -o pid=,comm=,args= | awk '$2 ~ /(^|\/)cloudflared$/ {print}'
screen -ls | sed -n '/knowledge-site/p' || true
```

然后停止 `8000` 监听进程、精确名为 `cloudflared` 的进程，以及可选的 `screen` 会话：

```bash
kill $(lsof -tiTCP:8000 -sTCP:LISTEN) 2>/dev/null || true
kill $(pgrep -x cloudflared) 2>/dev/null || true
screen -S knowledge-site-uvicorn -X quit 2>/dev/null || true
screen -S knowledge-site-cloudflared -X quit 2>/dev/null || true
```

不要照抄历史进程号；先重新运行检查命令，再停止当前查到的新进程。

## 如何重新启动

先设置密码、固定 session secret 和 cookie domain，再启动 FastAPI：

```bash
cd /Users/administrator/projects/yt-video2knowledge
set -a
source ~/.config/knowledge-site/env
set +a
.venv/bin/uvicorn knowledge_site.main:create_app --factory --host 127.0.0.1 --port 8000
```

另开一个终端启动 Cloudflare named tunnel connector。推荐用隐藏输入的 `TUNNEL_TOKEN` 或临时 token 文件传入，避免 token 出现在最终回复、仓库文件或长期命令行记录里：

```bash
read -s TUNNEL_TOKEN
export TUNNEL_TOKEN
cloudflared tunnel run
unset TUNNEL_TOKEN
```

如果固定域名返回 Cloudflare `530`，通常说明 Cloudflare 已收到请求，但本机 named tunnel connector 或 origin 不可用。先检查 `127.0.0.1:8000`，再检查精确名为 `cloudflared` 的 named tunnel connector。

## 临时 Quick Tunnel 备用方案

如果只是临时测试，也可以不用固定域名，改用 Quick Tunnel：

```bash
KNOWLEDGE_SITE_PASSWORD='你的共享密码' \
KNOWLEDGE_SITE_SECRET_KEY='一段足够长的随机字符串' \
.venv/bin/uvicorn knowledge_site.main:create_app --factory --host 127.0.0.1 --port 8000
```

另开一个终端启动 Cloudflare Quick Tunnel：

```bash
cloudflared tunnel --url http://127.0.0.1:8000 --protocol http2
```

终端会输出新的公网地址，形如：

```text
https://xxxx-xxxx-xxxx-xxxx.trycloudflare.com
```

复制这个地址访问即可。

切回固定域名前，必须停止 Quick Tunnel，再启动 `cloudflared tunnel run` named tunnel connector，避免公网入口和实际 connector 状态混淆。

## 注意事项

- Quick Tunnel 不需要在 Cloudflare 官网做配置。
- Quick Tunnel 地址不是固定域名，不适合长期收藏。
- 固定域名长期使用 named tunnel + 自有域名；可按需再加 Cloudflare Access。
- 不要把 `KNOWLEDGE_SITE_PASSWORD` 和 `KNOWLEDGE_SITE_SECRET_KEY` 提交到仓库。
- 如果公网地址返回 `530`，先确认本机 `8000` origin，再确认 `cloudflared tunnel run` named connector。
