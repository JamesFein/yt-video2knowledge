# Cloudflare Tunnel 与固定公网 hostname 配置

本文记录 `miniaiheadlines.top` 的当前 Cloudflare 配置，以及需要重新建立 DNS、Tunnel 或 Published application 时的步骤。网站的日常启动、停止、日志和健康检查统一见 [Knowledge Site 当前部署运行手册](knowledge-site-deployment.md)。

## 当前配置

| 项目 | 当前值 |
| --- | --- |
| 域名注册商 | NameSilo |
| Cloudflare zone | `miniaiheadlines.top` |
| Named Tunnel | `knowledge-site-mac` |
| 主入口 | `https://miniaiheadlines.top` |
| 备用入口 | `https://www.miniaiheadlines.top` |
| 本机 origin | `http://127.0.0.1:8000` |
| connector | 本机 `top.miniaiheadlines.cloudflared` LaunchAgent |
| 认证 | Knowledge Site 自带密码/session；未启用 Cloudflare Access |

当前 authoritative nameserver 是：

```text
audrey.ns.cloudflare.com
dilbert.ns.cloudflare.com
```

Nameserver 是 Cloudflare 为 zone 分配的值。如果 Dashboard 显示的实际值发生变化，应以 Dashboard 和公开 DNS 查询结果为准，不要机械照抄本文。

## 用最少概念理解链路

```text
NameSilo       -> 证明域名属于谁
Cloudflare DNS -> 决定 hostname 进入哪条 Tunnel
Named Tunnel   -> 保存 hostname 到本机 service 的映射
cloudflared    -> 在 Mac 上建立出站连接
FastAPI        -> 真正生成页面和 API 响应
```

公网请求的实际路径是：

```text
浏览器
  -> Cloudflare DNS / Edge
  -> Published application
  -> knowledge-site-mac
  -> 本机 cloudflared
  -> http://127.0.0.1:8000
  -> FastAPI / Uvicorn
```

Cloudflare Tunnel 不会把应用复制到云端。Mac 关机、断网、origin 停止或 connector 停止时，固定域名都会不可用。

## Published application

`knowledge-site-mac` 当前应包含两条 Published application route：

| Public hostname | Service type | Service URL |
| --- | --- | --- |
| `miniaiheadlines.top` | HTTP | `http://127.0.0.1:8000` |
| `www.miniaiheadlines.top` | HTTP | `http://127.0.0.1:8000` |

Cloudflare Dashboard 当前入口通常是：

```text
Networking -> Tunnels -> knowledge-site-mac -> Routes
```

选择 `Add route` → `Published application` 可以新增映射。Cloudflare UI 会变化，因此以“Tunnel”“Routes”“Published application”这些概念定位，不依赖过细的菜单文案。

## 首次配置或完整重建

只有域名迁移、Tunnel 被删除或本机部署重建时，才需要从头执行本节。

### 1. 把 zone 加入 Cloudflare

在 Cloudflare Dashboard 添加：

```text
miniaiheadlines.top
```

选择适合的套餐并记录 Cloudflare 分配的两个 nameserver。

### 2. 在 NameSilo 切换 nameserver

在 NameSilo Domain Manager 中，把原 nameserver 替换为 Cloudflare 为该 zone 分配的值。

公开验证：

```bash
dig NS miniaiheadlines.top
```

只有结果已经指向 Cloudflare，zone 才具备完整 DNS 控制权。传播可能需要一些时间。

### 3. 创建 remotely-managed Tunnel

在 Cloudflare Dashboard 的 Tunnels 页面创建：

```text
knowledge-site-mac
```

当前 connector 使用 remotely-managed tunnel token。Token 等同于运行 Tunnel 的凭据，不得写入仓库、聊天或截图。

### 4. 添加两条 Published application

分别把 apex 与 `www` 映射到：

```text
http://127.0.0.1:8000
```

在 full DNS setup 中，Cloudflare 通常会同时创建相应 DNS 记录。保存后检查 Routes 和 DNS 页面，避免残留冲突记录。

### 5. 在 Mac 上提供 connector

当前机器已经通过下面的 LaunchAgent 运行 connector：

```text
~/Library/LaunchAgents/top.miniaiheadlines.cloudflared.plist
```

它执行的核心命令是：

```text
cloudflared tunnel run --token-file ~/.config/knowledge-site/cloudflared-token
```

`--token-file` 避免把 token 直接放进命令参数。文件内容不能打印；权限应限制为当前用户可读。

重新建立本机 job 时，先准备 token 文件和 plist，再按 [部署运行手册](knowledge-site-deployment.md) 使用 `launchctl bootstrap`。不要在文档或 shell history 中粘贴真实 token。

## 验证配置

### DNS

```bash
dig NS miniaiheadlines.top
dig miniaiheadlines.top
dig www.miniaiheadlines.top
```

### 本机 origin 与公网

```bash
curl -sS -o /tmp/knowledge-site-local.html -w '%{http_code}\n' --max-time 5 http://127.0.0.1:8000/
curl -sS -o /tmp/knowledge-site-root.html -w '%{http_code}\n' --max-time 10 https://miniaiheadlines.top/
curl -sS -o /tmp/knowledge-site-www.html -w '%{http_code}\n' --max-time 10 https://www.miniaiheadlines.top/
```

未登录时 `303` 到登录页是正常应用响应。先验证本机，再验证公网；否则很容易把 FastAPI 故障误诊为 Cloudflare 故障。

### Tunnel 状态

```bash
launchctl print gui/$(id -u)/top.miniaiheadlines.cloudflared
tail -n 100 ~/Library/Logs/knowledge-site/cloudflared.err.log
```

Dashboard 中 `knowledge-site-mac` 应至少有一个 healthy connector，并且两条 Published application route 都存在。

## 常见问题

### Cloudflare 返回 530

这通常表示请求已经到达 Cloudflare，但 Tunnel connector 或本机 origin 不可用。按顺序检查：

1. `GET http://127.0.0.1:8000/`；
2. `top.miniaiheadlines.cloudflared`；
3. `cloudflared.err.log`；
4. Dashboard 中的 Tunnel health 和 Routes。

### 根域名可用但 `www` 不可用

检查 `www.miniaiheadlines.top` 是否拥有独立的 Published application route 和对应 DNS 记录。

### 为什么不能只在 NameSilo 添加一条普通 A 记录

当前架构通过 Cloudflare Tunnel 发布本机服务，没有稳定的公网 origin IP。Published application 把 hostname 映射到 Tunnel，`cloudflared` 再把流量送到本机服务。

### Quick Tunnel 是否还是主方案

不是。Quick Tunnel 只用于短期诊断，会产生随机 `trycloudflare.com` hostname。production 主入口始终是 `knowledge-site-mac` 和两个固定 hostname。

### 是否需要 Cloudflare Access

当前没有启用。Knowledge Site 使用自己的密码和 session。以后增加 Access 会改变登录链路，应作为单独的安全决策处理。

## 安全边界

- 不记录 Cloudflare account ID、API token、connector token 或 Knowledge Site secret。
- 不把 token 放进命令行参数、仓库文件或 agent 最终回复。
- 不因 Dashboard 文案变化就删除现有 Tunnel 或 DNS 记录；先读取当前状态。
- 不在未验证 origin 的情况下反复重启 connector。
- 不把 Quick Tunnel hostname 当作长期入口或写入 cookie domain。

## 官方参考

- [Cloudflare Tunnel](https://developers.cloudflare.com/tunnel/)
- [Tunnel routing 与 Published applications](https://developers.cloudflare.com/tunnel/routing/)
- [`cloudflared tunnel run` 参数](https://developers.cloudflare.com/tunnel/advanced/run-parameters/)
- [Tunnel token](https://developers.cloudflare.com/tunnel/advanced/tunnel-tokens/)
