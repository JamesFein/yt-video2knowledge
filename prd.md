
## 1. 背景

当前项目已经在本机生成 YouTube 知识笔记，目标数据目录为：

`/Users/administrator/projects/yt-video2knowledge/data/runs/2026-06-06`

该目录下已有 5 个视频目录包含 `metadata.json`、`report.md`、`summary.zh-CN.md`，另有 1 个视频目录仅包含音频文件。现在需要把这些 Markdown 内容整理成一个本地 HTML 页面，并通过 Cloudflare Quick Tunnel 暴露到公网访问，用来测试在当前电脑和较差网络环境下的访问效果。

## 2. 明确假设

- “cloud player tones” 按 “Cloudflare Tunnels” 理解。
- 本次目标是验证访问链路和弱网体验，不是上线正式知识库产品。
- 页面内容只来自 `data/runs/2026-06-06`。
- 首版只做静态 HTML 页面，不引入前端框架。
- 首版只展示已有 Markdown 文档，不处理仅有 `source_audio.webm` 且没有 Markdown 的视频目录。
- 本机环境按 macOS Apple Silicon 处理，且已安装 Homebrew。
- 首轮 Tunnel 主流程使用 Quick Tunnel / TryCloudflare，生成临时 `trycloudflare.com` URL。
- 如果本机没有安装 `cloudflared`，通过 Homebrew 安装。
- 命名 Tunnel、自有域名、Cloudflare Access 和长期在线服务都属于后续进阶项，不作为首轮测试必需条件。
- PRD 只描述需求、步骤和验收，不包含实现代码。

## 3. 目标

1. 从 `data/runs/2026-06-06/videos/*/summary.zh-CN.md` 和 `report.md` 生成一个可浏览的 HTML 页面。
2. 在本机启动静态页面服务，确认本机访问正常。
3. 使用 Cloudflare Quick Tunnel 把本机页面临时暴露到公网 URL。
4. 在正常网络和较差网络环境下测试页面可访问性、加载速度和阅读体验。
5. 形成测试记录，判断 Cloudflare Tunnel 是否适合后续用于个人知识页面临时预览。

## 4. 非目标

- 不做用户登录、权限系统、数据库、搜索后端或评论功能。
- 不把页面部署到 Cloudflare Pages、Vercel、Netlify 等静态托管平台。
- 不处理视频音频播放、字幕同步播放或在线播放器。
- 不改动现有知识摘要生成主流程。
- 不将 Cloudflare Tunnel 配置成长期生产服务，除非测试结果确认需要进入下一阶段。

## 5. 用户场景

### 场景 A: 本机快速预览

用户希望在本机浏览器打开一个页面，快速看到 2026-06-06 当天所有已生成的视频知识笔记。

验收方式：本机浏览器能打开页面，看到 5 条视频内容入口，并能进入或展开阅读对应总结。

### 场景 B: 公网临时访问

用户希望通过 Cloudflare Quick Tunnel 生成的公网 URL，从手机或另一台设备访问本机页面。

验收方式：外部设备能通过 Tunnel URL 打开页面，内容与本机页面一致。

### 场景 C: 弱网体验测试

用户希望模拟或实际使用较差网络，观察页面是否能稳定打开、是否出现加载过慢、内容错位或无法阅读。

验收方式：在弱网条件下记录至少 3 次访问结果，包括是否成功打开、首屏可阅读时间、完整加载时间和失败现象。

## 6. 数据范围

首版纳入以下 5 个视频目录：

- `08SVa45XimY`: 向量模型工程师：AI 的隐藏瓶颈与新时代的信息迷宫
- `5qHI6y4Qisc`: 睡眠專家：休息的關鍵不在晚上，而是白天
- `GGLr-TtKguA`: 从编解码和词嵌入开始，一步一步理解 Transformer
- `eG7P2QFU16I`: 经济学家颠覆建议：「发展中国家别再搞AI培训了，直接用税收买下AI公司的股票」
- `gSNFJbgoaHI`: How to Build an AI-Native Services Company

暂不纳入：

- `vOIkUSYfUMo`: 当前目录仅发现 `source_audio.webm`，没有可展示的 Markdown 内容。

## 7. Cloudflare 新手解释

### 7.1 Cloudflare Tunnel 是什么

Cloudflare Tunnel 的作用是让公网用户可以访问你本机上正在运行的服务，但不需要你打开路由器端口、不需要公网 IP，也不需要修改入站防火墙规则。

本次使用的是 Quick Tunnel，也叫 TryCloudflare。它会把你本机的 `http://127.0.0.1:8787` 临时映射成一个公网 URL，形式类似 `https://xxxx.trycloudflare.com`。

### 7.2 `cloudflared` 是什么

`cloudflared` 是 Cloudflare 提供的本机命令行工具。它在你的电脑上运行，并主动连接 Cloudflare 网络。外部设备访问 `trycloudflare.com` URL 时，请求会经过 Cloudflare，再转发到你电脑上的本地服务。

### 7.3 Quick Tunnel 的生命周期

Quick Tunnel 适合测试和临时分享：

- 不要求你已经有 Cloudflare 托管域名。
- 不要求你在 Cloudflare Dashboard 里提前创建 Tunnel。
- URL 是临时生成的，不适合作为长期固定入口。
- 电脑关机、网络断开、终端停止或 `cloudflared` 退出后，公网 URL 就不可用了。

### 7.4 本次不需要做的事情

首轮测试不需要：

- 购买域名。
- 把域名 DNS 托管到 Cloudflare。
- 创建命名 Tunnel。
- 配置 Cloudflare Access。
- 配置系统服务或开机自启。

## 8. 页面需求

### 8.1 内容结构

页面应包含：

- 页面标题：`2026-06-06 YouTube Knowledge Digest`
- 数据来源说明：显示源目录路径和生成日期。
- 视频列表：展示标题、视频 ID、时长、YouTube 链接。
- 内容入口：每条视频至少能阅读中文总结。
- 详细内容：可继续阅读完整 `report.md` 内容。
- 缺失内容提示：如果某个视频目录没有 Markdown，明确标记为“暂无 Markdown 内容”，但首版不展示音频文件。

### 8.2 阅读体验

页面应满足：

- 桌面浏览器和手机浏览器都能正常阅读。
- 首屏应先展示视频列表和摘要入口，避免一打开就是大量长文。
- 长报告内容需要有清晰标题层级。
- 外链打开 YouTube 原视频时，不影响当前页面阅读。
- 不依赖远程字体、远程 CSS、远程 JS 或第三方 CDN，以减少弱网变量。

### 8.3 静态资源策略

首版应尽量只有一个 HTML 文件，或一个 HTML 文件加极少量本地静态资源。

理由：

- 便于本机静态服务直接发布。
- 便于弱网测试时减少请求数量。
- 便于判断 Cloudflare Tunnel 本身的访问表现，而不是把问题混入复杂前端构建链路。

## 9. 实施步骤

### 第 1 步：确认输入数据

行动：

- 扫描 `data/runs/2026-06-06/videos`。
- 找出包含 `summary.zh-CN.md`、`report.md`、`metadata.json` 的视频目录。
- 记录缺少 Markdown 的目录。

验收：

- 确认首版页面包含 5 个可展示视频。
- 确认 `vOIkUSYfUMo` 因缺少 Markdown 暂不展示或显示为缺失项。

### 第 2 步：确定 HTML 输出位置

行动：

- 在仓库内选择一个不会污染原始数据目录的位置存放生成页面。
- 建议位置：`dist/cloudflare-tunnel-test/2026-06-06/index.html`。

验收：

- 输出目录与 `data/runs` 原始数据分离。
- 删除或重建输出目录不会影响原始 Markdown、metadata、transcript 和音频文件。

### 第 3 步：生成静态 HTML 页面

行动：

- 读取每个视频的 `metadata.json` 获取标题、时长和 YouTube 链接。
- 读取 `summary.zh-CN.md` 作为列表和摘要展示来源。
- 读取 `report.md` 作为完整详情展示来源。
- 将 Markdown 转换为 HTML。
- 生成一个单页 HTML 文件。

验收：

- 页面能展示 5 个视频条目。
- 每个条目至少有标题、时长、原视频链接和中文总结。
- 完整报告内容能被展开、跳转或阅读。
- 页面中没有明显乱码、重复标题混乱或 Markdown 原始符号泄漏。

### 第 4 步：本机访问验证

行动：

- 固定使用本地端口 `8787`。
- 在 HTML 输出目录启动一个本地静态文件服务：
  - `python3 -m http.server 8787 --bind 127.0.0.1 --directory dist/cloudflare-tunnel-test/2026-06-06`
- 使用本机浏览器访问：
  - `http://127.0.0.1:8787/`
- 检查桌面窗口和手机尺寸模拟下的排版。

验收：

- `http://127.0.0.1:8787/` 可以稳定打开。
- 页面刷新后仍可正常加载。
- 窄屏下标题、链接、段落不重叠。
- 浏览器控制台没有影响页面阅读的错误。

### 第 5 步：创建 Cloudflare Quick Tunnel 临时访问入口

行动：

1. 打开一个新终端窗口，检查本机是否已安装 `cloudflared`：
   - `cloudflared --version`
2. 如果提示 `cloudflared: command not found`，安装 `cloudflared`：
   - `brew install cloudflared`
3. 安装完成后再次确认版本：
   - `cloudflared --version`
4. 确认第 4 步中的本地静态服务仍在运行，并且本机可以打开：
   - `http://127.0.0.1:8787/`
5. 在新终端窗口启动 Quick Tunnel：
   - `cloudflared tunnel --url http://127.0.0.1:8787`
6. 等待终端输出 `https://*.trycloudflare.com` 形式的公网 URL。
7. 复制该公网 URL。
8. 在本机浏览器打开该 URL，确认内容能通过 Cloudflare 访问。
9. 用手机或另一台设备打开同一个 URL，确认外部设备也能访问。
10. 记录 Tunnel URL、启动时间、本地端口、测试设备和测试网络。
11. 测试结束后，在运行 `cloudflared` 的终端里按 `Ctrl+C` 关闭 Quick Tunnel。
12. 如果不再需要本地静态服务，也在运行静态服务的终端里按 `Ctrl+C` 关闭。

验收：

- `cloudflared --version` 能正常显示版本号。
- 本地页面服务固定运行在 `http://127.0.0.1:8787/`。
- Cloudflare 返回一个可访问的 `https://*.trycloudflare.com` 公网 URL。
- 本机以外的设备可以打开该 URL。
- 停止 `cloudflared` 后，该 URL 不再作为有效访问入口使用。

### 第 6 步：正常网络测试

行动：

- 在本机浏览器访问 Tunnel URL。
- 在手机或另一台设备访问 Tunnel URL。
- 记录页面是否打开、首屏是否可读、完整报告是否可读。

验收：

- 正常网络下连续访问 3 次均成功。
- 首屏内容能在可接受时间内出现。
- 页面功能与本机地址访问结果一致。

### 第 7 步：较差网络测试

行动：

- 使用至少一种弱网方式测试：
  - Chrome DevTools 网络节流。
  - macOS Network Link Conditioner。
  - 手机热点弱信号。
  - 人为切换到网络较差的 Wi-Fi。
- 每种方式至少测试 3 次。

验收：

- 每次记录是否成功打开。
- 每次记录首屏可阅读时间。
- 每次记录完整页面加载时间。
- 记录失败、超时、白屏、样式错乱、内容过长导致卡顿等问题。

### 第 8 步：总结测试结论

行动：

- 汇总本机访问、Tunnel 正常网络访问、Tunnel 弱网访问三类结果。
- 判断问题主要来自本机服务、Cloudflare Tunnel、页面体积，还是网络环境。
- 给出是否进入下一阶段的建议。

验收：

- 形成一份简短测试记录。
- 明确结论：继续使用临时 Tunnel、改成命名 Tunnel、改为静态托管，或暂不继续。

## 10. 测试指标

必须记录：

- 页面总大小。
- 本机访问是否成功。
- Tunnel URL 访问是否成功。
- 首屏可阅读时间。
- 完整页面加载时间。
- 弱网下失败次数。
- 手机端是否可读。

建议记录：

- Cloudflare Quick Tunnel 连接是否频繁断开。
- 本机休眠、锁屏、网络切换后 Tunnel 是否仍可用。
- 页面是否因为内容过长导致滚动卡顿。
- 是否需要拆成多页来提升弱网体验。

## 11. 常见失败与排查

### 11.1 `cloudflared: command not found`

含义：

- 本机还没有安装 `cloudflared`，或者安装后命令没有进入当前终端的 PATH。

处理：

- 先运行 `brew install cloudflared`。
- 安装完成后重新打开终端，再运行 `cloudflared --version`。
- 如果仍然失败，记录 Homebrew 安装输出和当前 shell 环境，不继续启动 Tunnel。

### 11.2 本机 `127.0.0.1:8787` 打不开

含义：

- 本地静态服务没有成功启动，或者端口不是 `8787`。

处理：

- 先修复本地静态服务。
- 在本机页面打不开之前，不继续测试 Cloudflare Tunnel。
- 确认静态服务命令中的输出目录是 `dist/cloudflare-tunnel-test/2026-06-06`。

### 11.3 Tunnel URL 打不开

含义：

- `cloudflared` 可能已经停止，或者没有成功连接到 Cloudflare 网络。

处理：

- 检查运行 `cloudflared tunnel --url http://127.0.0.1:8787` 的终端是否仍在运行。
- 检查终端中是否出现 `trycloudflare.com` URL。
- 如果终端已经退出，重新启动 Quick Tunnel 并使用新 URL。

### 11.4 手机打不开，但电脑能打开

含义：

- 可能是手机网络、URL 复制、Tunnel 进程或浏览器缓存问题。

处理：

- 确认手机访问的是完整 `https://*.trycloudflare.com` URL。
- 确认 `cloudflared` 终端仍在运行。
- 尝试关闭手机 Wi-Fi 改用蜂窝网络，或换另一台设备测试。
- 记录具体失败现象，不要直接假设是 Cloudflare 问题。

### 11.5 页面能打开但很慢

含义：

- 可能是页面体积过大、弱网带宽低、Cloudflare Tunnel 链路不稳定，或本机上行网络较差。

处理：

- 记录页面总大小、首屏可阅读时间和完整加载时间。
- 如果弱网下长文页面明显慢，下一阶段优先考虑拆成索引页加详情页。

### 11.6 `~/.cloudflared/config.yaml` 已存在导致 Quick Tunnel 异常

含义：

- Cloudflare 官方说明 Quick Tunnel 在某些情况下会受到本机已有 `cloudflared` 配置文件影响。

处理：

- 先记录该文件是否存在和异常信息。
- 不直接删除、移动或覆盖已有配置文件。
- 如果后续需要处理已有配置，单独制定变更步骤。

## 12. 风险与取舍

### 12.1 Quick Tunnel 与命名 Tunnel

Quick Tunnel 更适合本次测试：

- 配置少。
- URL 临时生成。
- 适合快速验证。
- 不需要 Cloudflare 托管域名。

命名 Tunnel 更适合后续长期访问：

- URL 稳定。
- 可以绑定自有域名或可配置 DNS 的域名。
- 更适合配合 Cloudflare Access 做访问控制。

首版只使用 Quick Tunnel。只有在 Quick Tunnel 测试通过，并且明确需要稳定域名或访问控制后，再另行规划命名 Tunnel。

### 12.2 单页与多页

单页更简单：

- 实现成本低。
- 只有一个入口。
- Tunnel 测试变量少。

多页更适合弱网：

- 首屏更轻。
- 单个报告打开更快。
- 后续内容增加时更可维护。

首版建议先做单页。如果页面体积或弱网表现不好，再拆成索引页加详情页。

### 12.3 本机暴露风险

Cloudflare Quick Tunnel 会把本机服务暴露到公网 URL。

控制方式：

- 只暴露静态输出目录，不暴露整个项目根目录。
- 测试结束后关闭 Tunnel。
- 不在页面中展示密钥、cookie、token、私人配置或未公开 transcript。
- 如果需要长期访问，必须另行评估命名 Tunnel、Cloudflare Access 或其他访问控制。

## 13. 下一阶段

只有当 Quick Tunnel 首轮测试结果可接受时，才进入下一阶段。下一阶段可选方向：

- 命名 Tunnel：用于稳定 URL，需要 Cloudflare 托管域名或可配置 DNS 的域名。
- Cloudflare Access：用于给公网入口增加访问控制。
- 多页静态站点：用于降低首屏体积，改善弱网体验。
- 静态托管：如果不需要访问本机实时内容，可以考虑 Cloudflare Pages 等静态托管方案。

## 14. 完成标准

本任务完成时应满足：

- 已有一个可本机访问的 HTML 页面。
- 页面内容来自 `data/runs/2026-06-06`。
- 页面至少包含 5 个有 Markdown 内容的视频。
- 本地页面服务固定使用 `http://127.0.0.1:8787/`。
- Cloudflare Quick Tunnel 生成的 `https://*.trycloudflare.com` URL 可以从外部设备访问。
- 已完成正常网络和弱网测试。
- 已记录测试结果和下一步建议。

## 15. 推荐执行顺序总览

1. 盘点输入数据，确认 5 个视频有 Markdown 内容。
2. 生成静态 HTML 到 `dist/cloudflare-tunnel-test/2026-06-06/index.html`。
3. 在 `8787` 端口启动本地静态服务并验证页面。
4. 检查或安装 `cloudflared`。
5. 用 Quick Tunnel 暴露 `http://127.0.0.1:8787`。
6. 复制 `trycloudflare.com` URL 并用外部设备访问。
7. 在正常网络下测试 Tunnel URL。
8. 在弱网环境下测试 Tunnel URL。
9. 测试结束后关闭 Quick Tunnel 和本地静态服务。
10. 汇总指标并决定是否进入命名 Tunnel 或静态托管阶段。

## 16. 参考资料

- Cloudflare Tunnel 概览：`https://developers.cloudflare.com/tunnel/`
- Cloudflare Quick Tunnels / TryCloudflare：`https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/`
- `cloudflared` 下载与安装：`https://developers.cloudflare.com/tunnel/downloads/`
