# Cloudflare 边缘压缩实施记录

- **原方案类型**：PRD
- **当前状态**：已完成并验证
- **验证日期**：2026-08-03

> 本文从 `docs/plans/` 归档而来，保留当时的目标、决策和验证方法。它不是待实施计划，也不表示压缩规则由本仓库代码管理。

## 原始问题

Knowledge Site 通过 Cloudflare Named Tunnel 提供 FastAPI Web 应用。移动端网络可能不稳定，因此需要判断：

- Cloudflare 是否应压缩 HTML、CSS、JavaScript 和 JSON；
- 是否需要修改 FastAPI；
- Brotli、Gzip 和未压缩回退是否兼容常见浏览器；
- 如何验证配置确实生效。

部署链路是：

```text
浏览器
  -> Cloudflare Edge
  -> Named Tunnel: knowledge-site-mac
  -> 本机 cloudflared
  -> FastAPI / Uvicorn at 127.0.0.1:8000
```

## 决策

第一阶段只使用 Cloudflare 边缘压缩，不给 FastAPI 添加 `GZipMiddleware`。

理由：

- 边缘压缩直接减少 Cloudflare 到访问者的文本传输量；
- 浏览器通过 `Accept-Encoding` 自动协商；
- 不修改 application route、cookie、database schema 或 API contract；
- 当前没有证据表明 Mac 到 Cloudflare 的 origin 上行是瓶颈。

应用层 gzip 只在测量证明 origin 传输是瓶颈时再考虑，不能因为“可能有用”就增加 middleware 和测试负担。

## 当前验证结果

2026-08-03 对两个固定 hostname 的 `static/site.css` 进行只读验证：

| Hostname | 请求 `Accept-Encoding` | HTTP | `Content-Encoding` |
| --- | --- | --- | --- |
| `miniaiheadlines.top` | `gzip` | `200` | `gzip` |
| `miniaiheadlines.top` | `br, gzip` | `200` | `br` |
| `www.miniaiheadlines.top` | `gzip` | `200` | `gzip` |
| `www.miniaiheadlines.top` | `br, gzip` | `200` | `br` |

这证明当前 Cloudflare edge 会按客户端能力为可压缩 CSS 响应选择 Gzip 或 Brotli。它不能证明所有 status、content type 和 response size 都会被压缩；Cloudflare 仍会按规则和响应条件判断。

## 复验命令

```bash
curl -sS -D - -o /dev/null -H 'Accept-Encoding: gzip' https://miniaiheadlines.top/static/site.css
curl -sS -D - -o /dev/null -H 'Accept-Encoding: br, gzip' https://miniaiheadlines.top/static/site.css
curl -sS -D - -o /dev/null -H 'Accept-Encoding: gzip' https://www.miniaiheadlines.top/static/site.css
curl -sS -D - -o /dev/null -H 'Accept-Encoding: br, gzip' https://www.miniaiheadlines.top/static/site.css
```

检查：

- status 为 `200`；
- `content-type` 是文本类型；
- `content-encoding` 与客户端声明兼容；
- 页面、登录、CSS 和 JavaScript 仍能正常加载。

不要用未登录的 `/` redirect 作为主要压缩样本。`303` 适合检查部署链路，但不是可靠的压缩目标。

## 未实施的应用层方案

FastAPI 当前没有为了本方案增加 `GZipMiddleware`。只有出现以下证据时才重新评估：

- 大型 HTML/JSON 使本机到 Cloudflare 的上传成为主要瓶颈；
- Cloudflare edge 已压缩，但实测传输时间仍受 origin 文本体积主导；
- 明确需要在不经过 Cloudflare 的本机访问中压缩响应。

如果以后实施，必须单独决定 minimum size、静态 assets 策略，并增加压缩/未压缩行为测试。

## 安全与兼容边界

- 不在仓库中保存 Cloudflare API token、connector token 或 Knowledge Site secret。
- 不强制单一 encoding；保留浏览器协商和未压缩回退。
- 不为压缩修改登录 cookie、route 或 SQLite。
- 图片等已经压缩的资源不应期待明显收益。

## 官方参考

- [Cloudflare Content compression](https://developers.cloudflare.com/speed/optimization/content/compression/)
- [Cloudflare Compression Rules](https://developers.cloudflare.com/rules/compression-rules/)
- [Compression Rules settings](https://developers.cloudflare.com/rules/compression-rules/settings/)
- [Cloudflare Tunnel](https://developers.cloudflare.com/tunnel/)
