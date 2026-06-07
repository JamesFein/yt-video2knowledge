# miniaiheadlines.top 绑定 Cloudflare Public Hostname 操作说明

本文说明如何把已购买的 NameSilo 域名 `miniaiheadlines.top` 配置成 Cloudflare Tunnel 的固定公网入口，让用户可以通过下面两个地址访问本机 Knowledge Site：

```text
https://miniaiheadlines.top
https://www.miniaiheadlines.top
```

这两个地址最终都指向本机正在运行的服务：

```text
http://127.0.0.1:8000
```

本文不会记录真实密码、Cloudflare connector token、session secret 或任何敏感凭证。

## 先理解整体关系

当前临时访问方式是 Quick Tunnel：

```text
Cloudflare 随机 trycloudflare.com 地址
  -> cloudflared
  -> 127.0.0.1:8000
  -> Knowledge Site
```

Quick Tunnel 的地址每次可能变化，不适合长期收藏。

固定域名访问方式是 Named Tunnel + Public Hostname：

```text
https://miniaiheadlines.top
  -> Cloudflare DNS
  -> Cloudflare Tunnel public hostname
  -> 运行在本机的 cloudflared
  -> 127.0.0.1:8000
  -> Knowledge Site
```

这里有几个角色：

- NameSilo 是域名注册商，负责证明你拥有 `miniaiheadlines.top`。
- Cloudflare 需要接管这个域名的 DNS，才能把域名流量交给 Tunnel。
- Public Hostname 不是 Cloudflare 免费送你的域名，而是把你自己的域名绑定到某个 Tunnel。
- `cloudflared` 是运行在这台 Mac 上的小工具，负责把 Cloudflare 请求转发到本机应用。

## 当前已配置状态

当前目标配置是：

```text
Cloudflare nameserver:
audrey.ns.cloudflare.com
dilbert.ns.cloudflare.com

Cloudflare Tunnel:
knowledge-site-mac

Published application routes:
https://miniaiheadlines.top -> http://127.0.0.1:8000
https://www.miniaiheadlines.top -> http://127.0.0.1:8000
```

本机已安装 `cloudflared`：

```text
cloudflared version 2026.5.2
```

当前 Knowledge Site 运行目标仍是：

```text
http://127.0.0.1:8000
```

## 操作总览

整个配置分成四段：

1. 在 Cloudflare 添加 `miniaiheadlines.top` 这个网站。
2. 在 NameSilo 把 nameserver 改成 Cloudflare 分配的 nameserver。
3. 在 Cloudflare Zero Trust 创建命名 Tunnel 和 Public Hostname。
4. 在本机运行 Cloudflare 提供的 `cloudflared` connector，并验证访问。

## 第 1 步：在 Cloudflare 添加网站

目标：让 Cloudflare 知道你要管理 `miniaiheadlines.top`。

操作位置：

```text
Cloudflare Dashboard -> Websites -> Add a domain / Add a site
```

填写：

```text
miniaiheadlines.top
```

Cloudflare 会扫描当前 DNS，并给你分配两个 Cloudflare nameserver，形如：

```text
xxxx.ns.cloudflare.com
yyyy.ns.cloudflare.com
```

请记录这两个 nameserver。后面要复制到 NameSilo。

### 我可以执行

- 如果浏览器已经登录 Cloudflare，并且你允许我操作页面，我可以用 Computer Use 帮你走到添加网站页面。
- 我可以帮你识别 Cloudflare 页面上分配的两个 nameserver。

### 需要你确认/操作

- Cloudflare 登录、MFA、passkey、验证码。
- 任何 Cloudflare 让你确认域名所有权、套餐、付款或升级的步骤。
- 如果 Cloudflare 要你选择套餐，第一版通常选 Free 即可，但最终确认需要你点。

## 第 2 步：在 NameSilo 修改 nameserver

目标：把域名的 DNS 管理权从 NameSilo / DNS Owl 交给 Cloudflare。

操作位置大致是：

```text
NameSilo -> Domain Manager -> miniaiheadlines.top -> Change Nameservers
```

把当前 nameserver：

```text
ns1.dnsowl.com
ns2.dnsowl.com
ns3.dnsowl.com
```

替换成 Cloudflare 给你的两个 nameserver：

```text
xxxx.ns.cloudflare.com
yyyy.ns.cloudflare.com
```

保存后等待生效。通常几分钟到几小时，极端情况下可能更久。

### 我可以执行

- 如果浏览器已经登录 NameSilo，并且你允许我操作页面，我可以用 Computer Use 帮你找到 nameserver 设置页。
- 我可以把 Cloudflare 给出的 nameserver 填入 NameSilo。
- 我可以用命令检查生效情况：

```bash
dig NS miniaiheadlines.top
```

### 需要你确认/操作

- NameSilo 登录、MFA、passkey、验证码。
- 确认是否真的把 nameserver 从 DNS Owl 改为 Cloudflare。
- 如果 NameSilo 出现域名锁定、邮箱验证、付款或升级提示，需要你确认。

## 第 3 步：等待 Cloudflare 激活域名

回到 Cloudflare 的 `miniaiheadlines.top` 网站页面。

Cloudflare 会检查 nameserver 是否已经切换成功。如果成功，状态通常会变成 Active。

可以用本机命令辅助确认：

```bash
dig NS miniaiheadlines.top
```

当输出变成 Cloudflare nameserver 时，说明 DNS 切换方向正确。

### 我可以执行

- 用 `dig` 检查当前公开 nameserver。
- 在 Cloudflare 页面查看域名是否 Active（需要你允许 Computer Use 操作）。

### 需要你确认/操作

- 如果 Cloudflare 页面要求重新检查 nameserver，通常需要你在页面上点击确认。
- 如果很久不生效，需要你确认 NameSilo 页面保存是否成功。

## 第 4 步：创建命名 Tunnel

目标：创建一个长期可管理的 Tunnel，替代临时 Quick Tunnel。

推荐 tunnel 名称：

```text
knowledge-site-mac
```

操作位置：

```text
Cloudflare Dashboard -> Zero Trust -> Networks -> Tunnels -> Create a tunnel
```

选择 Cloudflared 类型的 Tunnel。

Cloudflare 会给出本机 connector 安装或运行命令。这个命令通常包含一段很长的 token。

注意：这个 token 是敏感信息，不要写入仓库文档，不要截图公开分享。

### 我可以执行

- 如果你允许我操作页面，我可以用 Computer Use 帮你创建 tunnel。
- 我可以在本机运行 Cloudflare 页面提供的 connector 命令。
- 我可以检查 tunnel 进程是否运行。

### 需要你确认/操作

- Cloudflare Zero Trust 首次开通时可能要求创建团队名、选择套餐或确认条款。
- 如果页面显示 connector token，需要你允许我使用它，但不要把 token 发到聊天里或写进文件。
- 如果需要安装后台服务，macOS 可能会弹出权限确认，需要你处理。

## 第 5 步：添加 Public Hostname

目标：把固定域名绑定到刚才创建的 Tunnel。

在 `knowledge-site-mac` tunnel 的 Public Hostname 页面添加第一条：

```text
Subdomain: 留空
Domain: miniaiheadlines.top
Path: 留空
Service type: HTTP
URL: 127.0.0.1:8000
```

最终含义是：

```text
https://miniaiheadlines.top -> http://127.0.0.1:8000
```

再添加第二条：

```text
Subdomain: www
Domain: miniaiheadlines.top
Path: 留空
Service type: HTTP
URL: 127.0.0.1:8000
```

最终含义是：

```text
https://www.miniaiheadlines.top -> http://127.0.0.1:8000
```

### 我可以执行

- 如果你允许我操作页面，我可以用 Computer Use 填写 Public Hostname。
- 我可以验证 Cloudflare 是否自动创建了对应 DNS 记录。

### 需要你确认/操作

- 如果 Cloudflare 提示 DNS 冲突，需要你确认是否覆盖旧记录。
- 如果 Cloudflare 提示 Access、WAF、证书或安全策略选择，第一版建议先保持默认，最终确认由你来点。

## 第 6 步：确认本机应用还在运行

固定域名是否可访问，取决于两个本机进程：

```text
Uvicorn / FastAPI 应用
cloudflared connector
```

检查 FastAPI：

```bash
lsof -iTCP:8000 -sTCP:LISTEN -n -P
curl -I http://127.0.0.1:8000/
```

未登录时，`curl -I http://127.0.0.1:8000/` 正常应返回登录跳转。

如果本机应用没有运行，先启动：

```bash
cd /Users/administrator/projects/yt-video2knowledge
set -a
source ~/.config/knowledge-site/env
set +a
.venv/bin/uvicorn knowledge_site.main:create_app --factory --host 127.0.0.1 --port 8000
```

建议把 `~/.config/knowledge-site/env` 放在仓库外，内容示例：

```bash
KNOWLEDGE_SITE_PASSWORD='你的共享密码'
KNOWLEDGE_SITE_SECRET_KEY='一段长期固定的随机字符串'
KNOWLEDGE_SITE_COOKIE_DOMAIN='.miniaiheadlines.top'
```

注意：不要把真实密码、session secret 或 Cloudflare token 写进文档或提交到仓库。

### 我可以执行

- 检查端口和进程。
- 启动或重启本机 FastAPI。
- 检查 `cloudflared` connector 是否在运行。

### 需要你确认/操作

- 如果要换 Knowledge Site 登录密码，需要你提供或自己设置环境变量。
- 如果希望长期在线，需要你保持这台 Mac 开机、联网，并保持应用和 tunnel 进程运行。

## 日常恢复：关闭 Codex 后怎么重新启动

关闭 Codex、关闭终端、电脑重启或网络断开后，需要重新恢复两个进程。

### 1. 启动 Knowledge Site

```bash
cd /Users/administrator/projects/yt-video2knowledge
set -a
source ~/.config/knowledge-site/env
set +a
.venv/bin/uvicorn knowledge_site.main:create_app --factory --host 127.0.0.1 --port 8000
```

这个终端保持打开。

### 2. 启动 Cloudflare connector

如果还没有把 connector 安装成系统服务，就需要手动运行 tunnel：

```bash
cloudflared tunnel run --token <Cloudflare 给出的敏感 token>
```

获取 token 的位置：

```text
Cloudflare Dashboard
-> Zero Trust
-> Networks
-> Connectors
-> Cloudflare Tunnels
-> knowledge-site-mac
-> Add a connector / Install and run connectors
-> 复制 cloudflared tunnel run --token ... 命令
```

这个 token 很敏感，不要发给别人，也不要写入仓库。这个终端也保持打开。

### 3. 验证

```bash
curl -I http://127.0.0.1:8000/
curl -I https://miniaiheadlines.top/
curl -I https://www.miniaiheadlines.top/
```

如果公网域名打不开，按顺序检查：

1. FastAPI 是否在 `127.0.0.1:8000` 运行。
2. `knowledge-site-mac` tunnel 是否显示 `HEALTHY`。
3. `knowledge-site-mac` 是否有两条 Published application routes。
4. `dig NS miniaiheadlines.top` 是否显示 Cloudflare nameserver。

## 登录状态为什么会反复失效

代码里的 session cookie 有效期是 15 天，但它依赖下面几个条件：

- 每次重启都必须使用同一个 `KNOWLEDGE_SITE_SECRET_KEY`。如果 secret 变化，旧 cookie 会立刻失效。
- 公网固定域名部署建议设置 `KNOWLEDGE_SITE_COOKIE_DOMAIN='.miniaiheadlines.top'`，这样 `miniaiheadlines.top` 和 `www.miniaiheadlines.top` 可以共享同一个 cookie。
- 尽量固定使用 `https://miniaiheadlines.top`，不要在根域名、`www` 和旧的 `trycloudflare.com` 地址之间来回切换。
- 不要点击退出登录，浏览器也不要清理该站点 cookie。

如果你在同一个浏览器里第一次访问 `miniaiheadlines.top` 后又访问 `www.miniaiheadlines.top`，在没有设置 `KNOWLEDGE_SITE_COOKIE_DOMAIN` 之前，浏览器会把它们当成两个不同站点，所以可能要求再登录一次。

## 第 7 步：验证公网访问

DNS 和 tunnel 都配置好后，先用命令验证：

```bash
curl -I https://miniaiheadlines.top/
curl -I https://www.miniaiheadlines.top/
```

正常结果：

- 能建立 HTTPS 连接。
- 能进入 Knowledge Site 登录流程。
- 如果未登录，可能返回 `303` 并跳到 `/login?next=/`。

然后用浏览器验证：

1. 打开 `https://miniaiheadlines.top`
2. 输入 Knowledge Site 登录密码。
3. 进入首页。
4. 打开某一天的页面，例如 `/days/2026-06-06`。
5. 打开某个视频页，例如 `/videos/-ZGP8QymMDM`。
6. 确认 Summary block 和 Meta Summary 保存功能正常。

### 我可以执行

- 用命令检查 HTTP/HTTPS 响应。
- 用浏览器自动化或 Computer Use 验证页面是否能打开。

### 需要你确认/操作

- 如果登录页需要你输入真实 Knowledge Site 密码，而你不希望把密码告诉我，可以由你手动输入。
- 如果要在手机或外部网络上测试，需要你自己用手机打开并反馈结果。

## 常见问题

### 为什么不能只在 NameSilo 加一条 DNS 记录？

Cloudflare Tunnel 的 Public Hostname 依赖 Cloudflare 管理这个域名的 DNS。最简单、最稳定的方式是把 `miniaiheadlines.top` 的 nameserver 改成 Cloudflare。

### Public Hostname 是 Cloudflare 免费送我的域名吗？

不是。Public Hostname 是你自己的域名或子域名，例如：

```text
miniaiheadlines.top
www.miniaiheadlines.top
```

Cloudflare 做的是把这个 hostname 路由到你的 Tunnel。

### Quick Tunnel 还需要吗？

配置好命名 Tunnel 和 Public Hostname 后，Quick Tunnel 就不再是主入口了。

Quick Tunnel 仍可用于临时测试，但用户应该访问固定域名：

```text
https://miniaiheadlines.top
```

### 电脑关机后还能访问吗？

不能。这个方案仍然依赖你的 Mac：

```text
Cloudflare -> cloudflared on Mac -> 127.0.0.1:8000
```

如果 Mac 关机、断网、应用停止或 `cloudflared` 停止，固定域名也会打不开。

### 要不要开启 Cloudflare Access？

第一版先不启用 Cloudflare Access，继续使用 Knowledge Site 自己的密码登录。

后续如果想让只有你的邮箱或指定用户能访问，可以再启用 Cloudflare Access。那会多一层 Cloudflare 登录保护。

## 最终验收清单

- [ ] `dig NS miniaiheadlines.top` 显示 Cloudflare nameserver。
- [ ] Cloudflare Dashboard 中 `miniaiheadlines.top` 状态为 Active。
- [ ] Cloudflare Zero Trust 中存在 named tunnel：`knowledge-site-mac`。
- [ ] Tunnel connector 在这台 Mac 上显示 Connected。
- [ ] Public Hostname 中存在 `miniaiheadlines.top`。
- [ ] Public Hostname 中存在 `www.miniaiheadlines.top`。
- [ ] `curl -I http://127.0.0.1:8000/` 能返回本机应用响应。
- [ ] `curl -I https://miniaiheadlines.top/` 能返回公网 HTTPS 响应。
- [ ] 浏览器打开 `https://miniaiheadlines.top` 能看到 Knowledge Site 登录页。
- [ ] 登录后能浏览首页、日期页和视频页。

## 官方参考

- Cloudflare Tunnel 概览：<https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/>
- Cloudflare Tunnel 路由与 Public Hostname：<https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/routing-to-tunnel/>
- Cloudflare Tunnel 创建与连接：<https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/>
- Cloudflare 添加网站：<https://developers.cloudflare.com/fundamentals/setup/account-setup/add-site/>
