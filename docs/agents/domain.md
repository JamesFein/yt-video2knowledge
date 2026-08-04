# Domain 文档使用规则

本文说明 coding agent 在探索代码和输出工程结论时，如何使用本仓库的 domain 文档。

## 探索代码前先读什么

1. 根目录 [`CONTEXT.md`](../../CONTEXT.md)：定义本项目的统一 domain 语言。
2. [`docs/adr/`](../adr/README.md)：阅读与目标区域有关的 Architecture Decision Record。
3. [`docs/guides/project-map.md`](../guides/project-map.md)：需要理解目录、数据流或部署边界时阅读。

如果某个引用文件不存在，继续完成当前任务，不要为了填满模板而提前创建空文档。只有当术语或架构决策真正形成时，才补充 domain 文档或 ADR。

## 当前结构

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

如果以后仓库真的拆成多个 bounded context，再引入下面的形式：

```text
/
├── CONTEXT-MAP.md
├── docs/adr/                 # 系统级决策
└── src/<context>/
    ├── CONTEXT.md
    └── docs/adr/             # context 级决策
```

不要仅仅因为目录变多就升级为 multi-context 结构。

## 使用统一词汇

Issue、重构方案、测试名和代码评审中出现 domain 概念时，使用 `CONTEXT.md` 已定义的名称，例如：

- Knowledge Playlist
- Playlist Entry
- Playlist-added Date
- Target Date
- Transcript
- Video Summary
- Meta Summary
- Digest Run
- Summary-ready Video
- Pending-summary Video
- Transcript-failed Video
- Needs-review Entry
- Knowledge Site

不要用 `Upload Date` 代替 Playlist-added Date，也不要把 Video Summary、Meta Summary 和 Transcript 混为一谈。

如果需要的概念不在词汇表中，先判断：

1. 是否只是发明了项目没有使用的新同义词；
2. 是否发现了确实缺失的 domain 概念。

只有第二种情况才应提出补充 `CONTEXT.md`。

## 发现 ADR 冲突时

如果计划或实现与现有 ADR 矛盾，必须明确指出，不得静默绕过。例如：

> 与 ADR-0002“以 manifest 作为完成权威”冲突；如果仍要改变，应先说明新证据并更新或 supersede 该 ADR。

ADR 的 `accepted` 表示当前仍有效；`deprecated` 或 `superseded` 表示需要继续阅读替代决策。
