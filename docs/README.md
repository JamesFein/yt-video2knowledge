# 项目文档使用说明

`docs/` 是项目的正式知识库，同时面向人类和 Coding Agent。这里保存经过整理、适合长期共享并具有明确用途的指南、运行手册、架构决策、Agent 指令和历史材料。

它与 [`.agents/memory/`](../.agents/memory/README.md) 的核心区别不是“人类与 AI”，而是内容的成熟度和权威性：

| 位置 | 主要角色 | 典型内容 |
| --- | --- | --- |
| `.agents/memory/` | Agent 经验候选区 | 待审核规则和尚待正式化的 gotcha |
| `docs/` | 人类与 Agent 共用的正式知识库 | 已验证指南、当前操作事实、正式约束和架构决策 |

## 目录分类

| 目录 | 保存什么 | 什么时候读取 |
| --- | --- | --- |
| [`guides/`](guides/) | 项目地图、概念解释和使用指南 | 第一次理解系统，或需要建立目录、模块和数据流心智模型时 |
| [`operations/`](operations/) | 当前部署事实、运行手册、恢复步骤和具体命令 | 执行或诊断真实环境操作时 |
| [`adr/`](adr/) | 已形成的架构决策、背景、替代方案和后果 | 计划改变相关架构或判断现有约束时 |
| [`agents/`](agents/) | Coding Agent 在特定任务中必须遵守的规则和读取条件 | 当前任务命中相应主题时，在修改或操作前读取 |
| [`archive/`](archive/) | 已过时但仍有历史解释价值的材料 | 研究历史方案时；不得作为当前操作依据 |

## Agent 专题索引

任务关键规则从根 `CLAUDE.md` / `AGENTS.md` 一跳到达，不要求先经过本 README：

| 文件 | 读取触发条件 |
| --- | --- |
| [`agents/domain.md`](agents/domain.md) | 修改 domain 语言、module 边界或架构决定 |
| [`agents/issue-tracker.md`](agents/issue-tracker.md) | 读取、创建或更新 Issue/PRD |
| [`agents/triage-labels.md`](agents/triage-labels.md) | 对 Issue 执行 triage |
| [`agents/knowledge-site-validation.md`](agents/knowledge-site-validation.md) | 修改 Site 代码、UI，或进行浏览器验收 |
| [`agents/knowledge-site-deployment.md`](agents/knowledge-site-deployment.md) | 操作 Uvicorn、LaunchAgent 或 Cloudflare Tunnel |

## Coding Agent 何时读取 docs

不要在每个任务中加载整个 `docs/`。根据任务选择最小的相关文档：

- 理解项目结构或寻找代码入口：读取 `guides/` 中的项目地图。
- 修改 Site 或执行浏览器验收：读取 `agents/knowledge-site-validation.md`。
- 改变服务或 Tunnel 状态：读取 Agent 部署约束，再读取 `operations/` 中的唯一运行手册。
- 执行部署、恢复或其他真实环境操作：读取对应的 `operations/` 手册。
- 计划改变既有架构：读取相关且状态仍为 `accepted` 的 ADR。
- 追查历史背景：最后再查看 `archive/`，并明确它不是当前事实源。

任务关键文档必须从根 [`AGENTS.md`](../AGENTS.md) 直接链接，并写清楚“何时阅读”。本 README 用于查找未在根文件列出的正式资料，不是任务关键规则的中转层。

## 从 memory 进入 docs

经验可以先进入 [Agent Memory](../.agents/memory/README.md) 接受验证和审核。当它稳定、可复用、影响重要且拥有明确触发条件时，再按内容类型进入本目录：

```text
待审核规则或短期经验
        ↓ 验证、确认、分类
guides / operations / adr / agents
        ↓
从 memory 删除；Git 历史保留溯源
```

完整的写入、读取、升级条件和升级后清理规则，以 [`.agents/memory/README.md`](../.agents/memory/README.md) 为准。本 README 只负责正式文档的分类和调用方式，避免在两处复制同一套生命周期规则。

## 权威性与维护原则

- Agent 执行约束以根指令和 `docs/agents/` 为准；memory 中的候选不能覆盖正式规则。
- `operations/` 保存当前可执行事实，`agents/` 保存 Agent 约束，二者不要互相复制完整内容。
- 状态为 `accepted` 的 ADR 代表当前架构决定；改变决定时新增 ADR 并标记旧记录被取代，不要静默绕过。
- 如果正式文档与代码或真实运行环境冲突，先停止有风险的操作并核验；确认文档过时后更新正式文档，而不是用 memory 长期打补丁。
- 文档不得保存 secret、未经验证的猜测或瞬时运行状态。
- 过时材料移入 `archive/`，并移除会让它被误认为当前事实源的入口。
