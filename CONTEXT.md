# YouTube Knowledge Digest

本上下文描述一套本地优先的个人知识整理流程：把加入固定 YouTube 播放列表的视频转化为可追溯的简体中文视频摘要，并将已完成内容提供给个人阅读。

## Language

### 来源与日期

**Knowledge Playlist（知识播放列表）**:
固定名为 `knowledge` 的 YouTube 播放列表，是此工作流接收待整理视频的业务入口。
_Avoid_: YouTube 频道、任意视频列表、观看历史

**Playlist Entry（播放列表条目）**:
一个视频加入 Knowledge Playlist 所形成的条目；日期筛选针对这个条目，而不是只针对视频本身。
_Avoid_: Video（讨论加入时间时）

**Playlist-added Date（加入播放列表日期）**:
Playlist Entry 被加入 Knowledge Playlist 的日历日期，是视频归入某一天的依据。
_Avoid_: Upload Date、First-seen Date、Processing Date

**Target Date（目标日期）**:
一次处理请求希望覆盖的 Playlist-added Date；只有归属于该日期的条目才进入这次日期范围。
_Avoid_: 运行日期、视频发布日期

### 知识内容

**Transcript（原始文本）**:
代表视频口述内容的源文本，是生成 Video Summary 时唯一可使用的事实依据。
_Avoid_: Video Summary、Meta Summary

**Video Summary（视频摘要）**:
由单个视频的 Transcript 改写而成的简体中文 Markdown 文章；它忠于原始文本且不补充外部事实。每个视频独立成文，不再聚合成每日总览。
_Avoid_: Daily Overview、Meta Summary、Transcript

**Meta Summary（元摘要）**:
用户在 Knowledge Site 中为单个视频另行整理的可编辑提炼笔记；它可以引用 Video Summary 的内容，但独立保存且不替代原摘要。
_Avoid_: Video Summary、模型生成摘要

### 处理状态

**Digest Run（摘要运行）**:
围绕一个 Target Date 累积形成的处理记录；后续增量处理或恢复操作仍属于这个日期范围，而不是天然构成一份全新的知识内容。
_Avoid_: 无状态批处理、单次命令执行

**Summary-ready Video（摘要已就绪视频）**:
已经同时拥有可用 Transcript 和 Video Summary 的已选视频，是能够进入 Knowledge Site 的内容。
_Avoid_: Completed Digest Run

**Pending-summary Video（待总结视频）**:
已经保留可用 Transcript、但尚无可用 Video Summary 的视频；恢复时应继续总结，而不是重新获取原始文本。
_Avoid_: Transcript-failed Video

**Transcript-failed Video（原始文本失败视频）**:
未能获得可用 Transcript 的已选视频，因此尚不具备生成 Video Summary 的事实来源。
_Avoid_: Pending-summary Video

**Needs-review Entry（待核查条目）**:
无法确认 Playlist-added Date、因而不能在严格日期规则下归入 Target Date 的 Playlist Entry；它需要核查或明确授权回退，但不等同于内容处理失败。
_Avoid_: Pending-summary Video、Transcript-failed Video

**Completed Digest Run（已完成摘要运行）**:
不存在 Pending-summary Video 或 Transcript-failed Video 的 Digest Run；所有已选视频都已达到可发布状态。
_Avoid_: Partial Digest Run、仅命令执行成功

### 阅读入口

**Knowledge Site（知识站点）**:
按 Target Date 展示 Summary-ready Video、并允许编辑 Meta Summary 的个人阅读入口。它消费已经生成的知识内容，不负责生成 Video Summary。
_Avoid_: 内容生成流水线、云端托管副本
