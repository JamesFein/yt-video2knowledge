# Domain 文档使用规则

## 何时阅读

修改 domain 术语、跨 module 数据流、依赖方向或架构决定前阅读本文。普通局部实现不必加载全部 domain 文档。

按任务读取最小集合：

1. [`CONTEXT.md`](../../CONTEXT.md)：任务使用 Playlist Entry、Target Date、Digest Run、Video Summary、Meta Summary 等 domain 概念时读取。
2. [ADR 索引](../adr/README.md)：计划改变现有架构或状态判定时，只读取相关且仍为 `accepted` 的记录。
3. [项目地图](../guides/project-map.md)：需要理解目录、module 边界、数据流或代码入口时读取。

如果某个引用文件不存在，继续完成当前任务，不要为了填满模板而提前创建空文档。只有当术语或架构决策真正形成时，才补充 domain 文档或 ADR。

## 当前布局

这是一个 single-context repository：

```text
/
├── CONTEXT.md
├── docs/adr/
└── src/yt_video2knowledge/
    ├── digest/
    └── site/
```

`digest/` 和 `site/` 是同一知识整理上下文中的两个 module 边界，不是拥有独立词汇表的两个 bounded context。因此当前没有 `CONTEXT-MAP.md`，也没有在各 source 子目录复制 `CONTEXT.md`。

只有仓库真正出现多个拥有独立语言和决策的 bounded context 时，才引入根 `CONTEXT-MAP.md`、context 级 `CONTEXT.md` 和 ADR；不要仅因目录变多升级布局。

## 使用统一词汇

Issue、方案、测试名和代码评审使用 `CONTEXT.md` 的正式名称。尤其不要用 Upload Date 代替 Playlist-added Date，也不要混淆 Transcript、Video Summary 与 Meta Summary。

需要的新概念不在词表时，先判断它是多余同义词还是真实缺口；只有真实缺口才补充 `CONTEXT.md`。

## 发现 ADR 冲突时

如果计划或实现与现有 ADR 矛盾，必须明确指出，不得静默绕过。例如：

> 与 ADR-0002“以 manifest 作为完成权威”冲突；如果仍要改变，应先说明新证据并更新或 supersede 该 ADR。

ADR 的 `accepted` 表示当前仍有效；`deprecated` 或 `superseded` 表示需要继续阅读替代决策。
