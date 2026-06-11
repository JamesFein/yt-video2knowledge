# 阅读页排版改造计划

> 目标：让视频详情页（`knowledge_site/templates/video.html`）左侧 Summary 阅读区，
> 在**窄屏单列阅读**场景下更舒服。配套原型见 `reading-layout-prototype.html`。

## 涉及文件

- `knowledge_site/templates/video.html` —— Summary block 的结构
- `knowledge_site/static/site.css` —— 阅读区样式
- `knowledge_site/markdown_blocks.py` —— 正文从 markdown 转纯文本（仅批次 B 涉及）

## 原型怎么看

浏览器打开 `reading-layout-prototype.html`，顶部两组切换：

- **并排对比 / 仅改造前 / 仅改造后**
- **手机宽 / 桌面宽**

「改造前」精确还原了当前 `site.css` 的关键规则；「改造后」是本计划的目标效果。

---

## 问题诊断（按对阅读的影响排序）

| # | 问题 | 位置 | 严重度 |
|---|------|------|--------|
| ① | **正文内部层级被压平**：小标题、加粗、列表被抹成纯文本，靠空行硬撑，无法扫读 | `markdown_blocks.py:80` `markdown_to_plain_text` + `video.html:51` `<pre>` | 🔴 高 |
| ② | **移动端标题/正文左边界错位**：≤560px 时正文顶格，标题仍被复选框推右 ~29px | `site.css:656` `pre{margin-left:0}` vs `site.css:500` label grid | 🟠 中 |
| ③ | **重复祖先面包屑**：每个 block 都重复显示同一个父标题前缀 | `video.html:43-46` + `site.css:528-536` | 🟠 中 |
| ④ | **复选框混在阅读流**：纯阅读时每段左侧一个空 checkbox，占缩进、分散注意 | `video.html:40` + `site.css:499-513` | 🟡 中低 |
| ⑤ | **行宽过长 / 正文字体**：Summary 正文无 `max-width`，宽屏拖到屏幕边；正文用无衬线，长篇中文不如 serif 耐读 | `site.css:548-555` `pre` | 🟡 中低 |

---

## 落地分两批

### 批次 A —— 纯 CSS + 模板（零数据风险，建议先做）

涵盖 ②③④⑤。不动 Python、不动「写入 Meta Summary」逻辑，可独立提交。

**② 修移动端错位**
- 让标题与正文共享同一条左边界。两种做法择一：
  - 把复选框移出文本流（见 ④ 的绝对定位方案），标题/正文都从最左开始；或
  - 保留 grid，但 `pre` 的 `margin-left` 跟随标题缩进，不在 ≤560px 单独清零。

**③ 重复面包屑只显一次**
- 模板上把 `heading_ancestors` 从「每个 block 都渲染」改为「按 section 分组、组顶显示一次」的 eyebrow。
- 简单实现：在 `video.html` 的 `{% for block %}` 里，用 `loop` 比较相邻 block 的 `heading_ancestors`，仅当与上一个不同才输出祖先行；其余 block 只渲染 `heading_text`。
- 样式参考原型 `.a-eyebrow`：12px、`--faint`、`letter-spacing:.06em`。

**④ 复选框让位阅读**
- 桌面端：复选框绝对定位到正文左外侧（原型 `.a-pick { position:absolute; left:-30px }`），默认 `opacity:0`，`:hover / :focus-visible / :checked` 时显现。
- 窄屏（≤720px）：回退为行内 `float:left` 且仍默认弱化。
- 勾选高亮（现 `site.css:492` `:has(input:checked)`）保留，确保「写入 Meta Summary」体验不变。

**⑤ 行宽 + serif 正文**
- 给正文加 `max-width: 38em`（约 38 个汉字/行）。
- 正文字体由 `font:inherit`（sans）改为 `--font-serif`，`font-size:17px`、`line-height:1.85`，与每日总览 `.summary-text`（`site.css:409`）统一气质。

> 验收：原型「改造后」即批次 A + B 的合并效果；只看批次 A 时，忽略小标题层级即可。

### 批次 B —— 恢复正文层级（动数据层，需补测试）

仅 ①，工作量与风险都更高，单独做。

- **核心改动**：正文不再走 `markdown_to_plain_text` 一把抹平，而是保留轻量结构——至少区分「子标题行 / 段落 / 列表项」。
- **两条技术路线（二选一，待定）**：
  1. **渲染为 HTML**：`body_markdown` 经一个受控的小型 markdown→HTML（子标题→`<h3>`、`**强调**`→`<strong>`、`-`/`1.`→`<ul>/<ol>`），模板用 `| safe` 输出。需做转义与白名单，防 XSS。
  2. **结构化数据**：在 `MarkdownBlock` 增加 `body_segments`（类型化片段列表：subhead / paragraph / list），模板按类型渲染。无需 `| safe`，更安全，但要改 dataclass + 模板循环。
- **联动「写入 Meta Summary」**：当前 `video.html:52` 的隐藏 `<textarea class="block-text">` 喂给 `site.js` 拼接 Meta。恢复层级后要确认写入的仍是期望文本（纯文本或带 markdown 标记），二者保持一致，避免选中写入的内容和屏幕所见不符。
- **必须补测试**：`tests/` 下为新解析/渲染加用例（子标题、加粗、有序/无序列表、空 body、代码块边界），跑 `uv run python3 -m unittest discover -s tests`。

---

## 验证清单

- [ ] 批次 A：浏览器对照原型「手机宽 / 桌面宽」逐条核对 ②③④⑤
- [ ] 批次 A：勾选 block → 仍能「写入 Meta Summary」，高亮正常
- [ ] 批次 B：新增解析/渲染单测全绿
- [ ] 批次 B：选中写入的文本与屏幕所见一致
- [ ] 回归：`uv run python3 -m unittest discover -s tests`
- [ ] 同步：如改了 block 数据结构，确认 `scripts/sync_knowledge_site.py` 不受影响

---

## 备注

- 原型 `reading-layout-prototype.html` 与本文档均为方案产物，**不参与线上渲染**，落地后可删。
- 批次 A 与批次 B 解耦，建议分两次提交，便于回退。
