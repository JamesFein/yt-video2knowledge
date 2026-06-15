# Knowledge Site Cloudflare 边缘压缩 PRD

## 问题陈述

Knowledge Site 目前通过 Cloudflare Named Tunnel 对外提供一个 FastAPI Web 应用。移动端用户可能通过 Safari 或微信打开站点，而移动网络条件并不稳定。站点所有者希望弄清楚：开启压缩是否能提升加载速度、需要在 Cloudflare 里做哪些具体操作、是否需要改应用代码，以及这个变化会不会影响手机浏览器兼容性。

当前部署分为两层：

1. FastAPI / Uvicorn 在本机监听 `127.0.0.1:8000`。
2. `cloudflared` 将本机应用连接到 Cloudflare，并服务 `https://miniaiheadlines.top` 和 `https://www.miniaiheadlines.top`。

压缩可能发生在两个不同位置：

1. Cloudflare 边缘压缩：Cloudflare 在把符合条件的文本响应发送给访问者之前进行压缩。
2. 源站 gzip：FastAPI 在把符合条件的文本响应通过 `cloudflared` 发给 Cloudflare 之前进行压缩。

这两者相关，但不是同一件事。建议优先决定是否开启 Cloudflare 边缘压缩，因为它的收益/风险比最高，而且不需要修改仓库代码。

## 解决方案

优先为 Knowledge Site 的公网 hostname 开启或确认 Cloudflare 边缘压缩。使用 Cloudflare Compression Rules，开启 Brotli 和 Gzip；如果当前 Cloudflare 套餐支持 Auto compression，也可以使用 Auto。

预期行为：

- 支持 Brotli 的现代浏览器可能收到 Brotli 压缩后的文本响应。
- 只支持 gzip 的浏览器或 WebView 可能收到 gzip 压缩后的文本响应。
- 两者都不支持的客户端应收到未压缩响应。
- 图片等已经压缩过的资源不应期待明显变小。

可选的后续增强：给 FastAPI 添加 gzip middleware，用来压缩“本机源站到 Cloudflare”这一段。只有当测量结果显示大 HTML/JSON 响应或本地上行带宽确实是瓶颈时，才建议这样做。

## 用户故事

1. 作为站点所有者，我希望 Cloudflare 压缩 HTML、CSS、JavaScript 和 JSON 响应，以便移动端用户下载更少的文本数据。
2. 作为站点所有者，我希望压缩通过协议自动协商，以便 Safari、微信 WebView 和其他客户端保持兼容。
3. 作为站点所有者，我希望有一个低风险、只改 Cloudflare 配置的选项，以便不修改应用代码也能改善传输。
4. 作为站点所有者，我希望有验证命令，以便确认压缩是否真的生效。
5. 作为站点所有者，我希望知道应用层 gzip 在什么情况下有用，以便不添加不必要的代码。
6. 作为手机 Safari 用户，我希望开启压缩后页面仍能正常加载，以免站点体验被不支持的编码破坏。
7. 作为手机微信浏览器用户，我希望站点能回退到兼容的编码，以便微信仍能显示 Knowledge Site。
8. 作为未来实现者，我希望有清晰的验收标准，以便安全验证代码或 Cloudflare 配置变化。

## 实现决策

- 第一实施路径：只使用 Cloudflare 边缘压缩。
- 使用 Cloudflare 的协商式压缩行为，而不是强制单一算法。
- 在 Cloudflare Compression Rules 中优先选择 `Enable Brotli and Gzip compression` 或 `Auto`。
- 不要把 Cloudflare token、Knowledge Site 密码或 session secret 存入本仓库。
- 不要把未登录根路径 redirect 作为主要压缩验证对象，因为 redirect 响应不是可靠的压缩目标。
- 把应用层 gzip 视为可选项，并且由测量结果驱动。
- 如果后续实现应用层 gzip，只压缩超过合理最小体积的文本类响应，例如 1000 或 4096 字节以上。
- 如果后续实现应用层 gzip，应避免压缩 `/assets/*`，因为缩略图和媒体通常已经压缩过。
- 边缘压缩不应改变任何公开 route、cookie、数据库 schema 或 API contract。

## Cloudflare 操作指南

### 选项 A：Dashboard 操作

1. 打开 Cloudflare Dashboard。
2. 选择包含 `miniaiheadlines.top` 的站点。
3. 打开 Rules。
4. 打开 Compression Rules。
5. 为 Knowledge Site hostnames 创建一条规则。
6. 匹配 hostnames：
   - `miniaiheadlines.top`
   - `www.miniaiheadlines.top`
7. 选择以下动作之一：
   - 推荐：enable Brotli and Gzip compression。
   - 也可接受：Auto compression。
8. 保存并部署规则。

如果当前套餐的 Cloudflare UI 提供的是默认压缩开关，而不是规则配置，也可以在那里开启 Brotli/Gzip，但仍然需要使用下面的命令验证。

### 选项 B：验证命令

Cloudflare 规则部署后运行：

```bash
curl -sI -H 'Accept-Encoding: gzip' https://miniaiheadlines.top/static/site.css
curl -sI -H 'Accept-Encoding: br, gzip' https://miniaiheadlines.top/static/site.css
curl -sI -H 'Accept-Encoding: gzip' https://www.miniaiheadlines.top/static/site.css
```

有用的预期信号：

- Status 应为 `200`。
- `content-type` 应为文本类类型，例如 `text/css`。
- `content-encoding` 可能是 `gzip`、`br` 或其他受支持的编码，具体取决于 Cloudflare 设置和客户端请求头。
- 可能出现 `vary: Accept-Encoding`。

不要只依赖下面这个命令验证压缩：

```bash
curl -I https://miniaiheadlines.top/
```

根路径在未登录时可能返回 `303` 登录 redirect。Redirect 响应用于部署健康检查是有用的，但不是最好的压缩验证目标。

### 选项 C：以后再考虑本地应用 gzip

只有当测量结果显示以下情况之一时，才考虑应用层 gzip：

- 视频摘要较长，导致 HTML 详情页较大。
- JSON API 响应变大。
- 本机 Mac 到 Cloudflare 的上传路径成为瓶颈。
- Cloudflare 边缘压缩已经开启，但页面加载仍主要受文本传输影响。

如果实施，应用应做到：

- 在 FastAPI app factory 中添加 gzip middleware。
- 使用中等压缩级别，例如 5，以避免不必要的 CPU 成本。
- 设置最小响应体积，例如 1000 或 4096 字节。
- 跳过 `/assets/*`。
- 为压缩和未压缩路径添加测试。

## 测试决策

好的测试应验证外部可见行为：

- 带有 `Accept-Encoding: gzip` 的文本响应可以返回 `Content-Encoding: gzip`。
- 低于配置阈值的小响应可以保持未压缩。
- 如果添加了应用层 gzip，`/assets/*` 下的资源响应仍保持未压缩。
- 现有登录/session 行为仍然有效。
- 现有 Knowledge Site 测试仍然通过。

如果修改了代码，推荐运行仓库测试命令：

```bash
uv run python3 -m unittest discover -s tests
```

Cloudflare 配置完成后，推荐手动浏览器检查：

1. 在桌面 Safari 或 Chrome 打开 `https://miniaiheadlines.top`。
2. 在手机 Safari 打开同一个 URL。
3. 在手机微信中打开同一个 URL。
4. 登录并打开首页、某一天页面和某个视频详情页。
5. 确认页面正常渲染，并且没有出现无限登录循环。

## 验收标准

- 当请求声明支持相应编码时，Cloudflare 会为符合条件的 `200` 文本响应返回压缩内容。
- 手机 Safari 能正常打开并使用 Knowledge Site。
- 手机微信能正常打开并使用 Knowledge Site。
- 登录 cookie 行为不变。
- 静态 CSS 和 JavaScript 仍可访问。
- 图片和缩略图行为不变。
- 仓库中没有提交任何 secret 值。

## 不在范围内

- 修改 Cloudflare Tunnel connector token 或 tunnel identity。
- 把 FastAPI 应用迁移到其他 host 或 port。
- 用其他部署架构替换 Cloudflare Tunnel。
- 为需要登录的 HTML 页面添加缓存规则。
- 优化图片格式或生成响应式图片。
- 添加 CDN cache invalidation workflow。
- 修改 Knowledge Site 登录模型。

## 进一步说明

压缩对文本密集型响应最有价值。这个 Knowledge Site 的静态 CSS 和 JavaScript 文件较小，所以最明显的收益可能来自包含视频摘要或每日 digest 文本的长 HTML 页面。

压缩预计不会明显改善已经压缩过的图片、缩略图或视频文件。在应用层重新压缩这些资源可能只会浪费 CPU，而不会带来有意义的传输节省。

对移动端兼容性来说，这个变化应当是安全的，因为 HTTP 压缩使用内容协商。浏览器会发送 `Accept-Encoding` 请求头，Cloudflare 会选择兼容的响应编码，或回退到未压缩数据。

官方参考：

- Cloudflare content compression: https://developers.cloudflare.com/speed/optimization/content/compression/
- Cloudflare Compression Rules settings: https://developers.cloudflare.com/rules/compression-rules/settings/
- Cloudflare Tunnel overview: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/
- FastAPI GZipMiddleware: https://fastapi.tiangolo.com/advanced/middleware/
- MDN Accept-Encoding: https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Accept-Encoding
