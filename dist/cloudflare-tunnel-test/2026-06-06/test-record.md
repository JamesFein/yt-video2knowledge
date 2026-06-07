# Cloudflare Quick Tunnel Test Record: 2026-06-06 Digest

## 基本信息

- HTML 页面：`dist/cloudflare-tunnel-test/2026-06-06/index.html`
- 本地访问地址：`http://127.0.0.1:8787/`
- Quick Tunnel URL：`https://speeds-ready-rows-reasons.trycloudflare.com`
- `cloudflared` 版本：`2026.5.2`
- 本地服务：`python3 -m http.server 8787 --bind 127.0.0.1 --directory dist/cloudflare-tunnel-test/2026-06-06`
- HTML 大小：`273406` bytes
- 展示视频数：`10`
- 缺少 Markdown 的目录：`P2uCbBdJ1JU`

## 本机验证

- 本地 HTTP 状态：`200 OK`
- 本地页面关键内容：标题、`已展示视频：10`、缺失目录提示均可读取。
- 桌面视口渲染：通过，无横向溢出。
- 手机视口渲染：通过，无横向溢出。

## Cloudflare Tunnel 验证

- Tunnel 创建：成功。
- Tunnel 连接预检查：DNS、UDP/QUIC、TCP/HTTP2、Cloudflare API 均通过。
- Tunnel HTTP 状态：`200 OK`
- Tunnel 页面关键内容：标题、`已展示视频：10`、缺失目录提示均可读取。
- Tunnel 手机视口自动化渲染：通过，无横向溢出。

## 正常网络自动化测试

| 次数 | 状态 | DOM 可读时间 | 完整加载时间 | 结果 |
| --- | --- | ---: | ---: | --- |
| 1 | 200 | 8.63s | 9.13s | 成功 |
| 2 | 200 | 7.96s | 8.47s | 成功 |
| 3 | 200 | 9.44s | 9.94s | 成功 |

- 平均 DOM 可读时间：`8.68s`
- 平均完整加载时间：`9.18s`

## 弱网模拟自动化测试

模拟条件：

- Chromium CDP 网络节流
- 延迟：`400ms`
- 下载吞吐：`50 KB/s`
- 上传吞吐：`20 KB/s`
- 连接类型：`cellular3g`

| 次数 | 状态 | DOM 可读时间 | 完整加载时间 | 结果 |
| --- | --- | ---: | ---: | --- |
| 1 | 200 | 10.29s | 10.79s | 成功 |
| 2 | 200 | 10.27s | 10.77s | 成功 |
| 3 | 200 | 10.29s | 10.79s | 成功 |

- 平均 DOM 可读时间：`10.29s`
- 平均完整加载时间：`10.78s`

## 外部设备人工测试

待补充。

需要记录：

- 设备：
- 网络环境：
- 是否成功打开：
- 首屏可读时间：
- 完整加载时间：
- 是否出现白屏、错位或加载失败：

## 初步结论

- Quick Tunnel 已经成功把本机页面暴露到公网。
- 当前单页 HTML 可以在本机、Tunnel、公网手机视口自动化测试中正常渲染。
- 页面体积约 273 KB，弱网模拟下仍能成功打开，但加载时间接近 11 秒。
- 如果后续数据量继续增长，建议优先考虑拆成索引页加视频详情页，以降低首屏体积。
