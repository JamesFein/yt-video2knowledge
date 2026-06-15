# 三套软件生产 Agent Skills 对比

调研日期：2026-06-11

## 说明

这里的三套 "skills" 都不是传统编程课程，而是给 Claude Code、Codex、Cursor、Gemini CLI 等 coding agent 使用的工作流指令包。它们的共同目标是减少 AI 直接乱写代码带来的问题，把软件生产重新拉回到需求澄清、规格、计划、测试、审查、发布这些工程环节中。

名称校正：

- "Gary10 / GStack" 应为 Garry Tan 的 [GStack](https://github.com/garrytan/gstack)。
- "Matt Pokark / TypeScript" 应为 Matt Pocock 的 [Skills for Real Engineers](https://github.com/mattpocock/skills)，Matt Pocock 也是 Total TypeScript / AI Hero 作者。
- "Superpowers" 指 Jesse Vincent / obra 的 [Superpowers](https://github.com/obra/superpowers)。

## 表 1：整体定位对比

| 套件 | 核心定位 | 典型使用方式 | 最适合的使用者 | 主要价值 |
|---|---|---|---|---|
| Garry Tan / GStack | 把 coding agent 组织成一个虚拟产品工程团队，包括 CEO、工程经理、设计师、QA、发布、安全、SRE 等角色 | 通过 slash commands 调用不同角色，例如 `/office-hours`、`/plan-ceo-review`、`/review`、`/qa`、`/ship` | 创始人、技术负责人、想让 agent 端到端推进产品的人 | 覆盖从产品构想到上线验证的完整链路，适合把多个 agent 当团队管理 |
| Matt Pocock / Skills for Real Engineers | 小而可组合的工程技能包，强调工程师仍然掌控流程 | 按需调用具体技能，例如 `/grill-me`、`/grill-with-docs`、`/to-prd`、`/to-issues`、`/tdd`、`/diagnose` | 已有工程判断、想提升 agent 输出质量的工程师 | 用最低限度的流程增强需求对齐、PRD、任务拆分、TDD、架构改进和 debug |
| Jesse Vincent / Superpowers | 一套强约束的软件开发方法论，让 agent 自动遵守从 brainstorm 到 TDD、review、branch finish 的流程 | 安装后由 agent 在合适任务前主动检查并触发相关 skill；核心流程被设计成 mandatory workflows | 怕 agent 跑偏、跳过测试、做大而不受控改动的团队或个人 | 用流程纪律约束 agent：先设计、再计划、测试优先、任务间审查、完成前验证 |

## 表 2：按软件生产环节对比

| 软件生产环节 | GStack 怎么用 | Matt Pocock Skills 怎么用 | Superpowers 怎么用 | 这一环节解决的问题 |
|---|---|---|---|---|
| 需求澄清 / 产品定位 | 用 `/office-hours` 做 YC-style 提问；用 `/plan-ceo-review` 重新审视产品问题和范围 | 用 `/grill-me` 或 `/grill-with-docs` 让 agent 连续追问，直到形成共享理解；`/grill-with-docs` 还会沉淀项目语言和 ADR | `brainstorming` 在写代码前启动，先把粗略想法问清楚并形成设计方向 | 防止 agent 把用户的第一句话当成最终需求，减少方向性错误 |
| 规格 / PRD | 用 `/spec` 把模糊意图转成可执行规格，后续可交给实现和发布技能 | 用 `/to-prd` 把已有对话整理成 PRD，并可作为 GitHub issue | 设计通过后进入 `writing-plans`，把规格转成足够清晰的执行计划 | 把口头意图变成可检查、可拆分、可复用的工作输入 |
| 任务拆分 | 用 `/autoplan` 或 `/spec` 串联产品、设计、工程、DX 审查后生成计划 | 用 `/to-issues` 把 PRD 拆成 vertical slices；强调 tracer bullets，小的端到端切片优先 | `writing-plans` 把工作拆成 2-5 分钟级别的小任务，并写清文件路径和验证步骤 | 避免 agent 一次性铺太大，先跑通关键路径并尽早获得反馈 |
| 架构 / 设计评审 | 用 `/plan-eng-review` 锁定架构、数据流、边界和测试；用 `/plan-design-review`、`/design-consultation`、`/plan-devex-review` 补齐 UI 和 DX 细节 | 用 `/zoom-out` 理解系统上下文；用 `/improve-codebase-architecture` 找模块边界和深模块机会 | 设计批准后再进入 worktree 和计划执行，强调 YAGNI、DRY 和 TDD 约束 | 把隐藏假设提前暴露，避免实现阶段才发现架构、界面、测试边界不清楚 |
| 实现 | 用设计、审查和 QA skills 包围普通实现；前端可用 `/design-html` 生成高质量 HTML | 用 `/tdd` 按 red-green-refactor 做一条行为一条测试；用 `/prototype` 做可丢弃原型验证设计 | `test-driven-development` 强制 RED-GREEN-REFACTOR；`executing-plans` 或 `subagent-driven-development` 执行计划 | 让 agent 写代码时有反馈回路，而不是一次性生成大块不可验证代码 |
| Debug / 故障定位 | 用 `/investigate` 先调查根因，强调没有调查不修复 | 用 `/diagnose` 走 reproduce -> minimise -> hypothesise -> instrument -> fix -> regression-test | 用 `systematic-debugging` 和 `verification-before-completion`，确保问题真实修复 | 防止 agent 猜测式修 bug，减少修一个坏三个的情况 |
| Review / QA / 安全 | 用 `/review` 做 staff engineer review；用 `/qa` 或 `/qa-only` 浏览器测试；用 `/design-review`、`/cso`、`/benchmark` 覆盖视觉、安全、性能 | 主要通过 `/tdd`、`/triage`、`/improve-codebase-architecture` 控制质量；更依赖工程师主动组合 | 用 `requesting-code-review` 和 `receiving-code-review` 在任务之间审查；critical issue 会阻塞继续 | 让质量检查进入流程本身，而不是等到最后人工兜底 |
| 发布 / 收尾 / 记忆 | 用 `/ship`、`/land-and-deploy`、`/canary`、`/document-release`、`/retro`、`/learn` 覆盖发布、生产验证、文档和复盘 | 用 `/handoff` 做上下文交接；用 `setup-pre-commit`、`git-guardrails` 等补充工程护栏 | 用 `using-git-worktrees` 建隔离工作区；用 `finishing-a-development-branch` 验证测试并决定 merge、PR、keep 或 discard | 把 agent 的工作从“写完代码”推进到“分支可安全收尾” |

## 表 3：选型和组合建议

| 判断维度 | 优先选 GStack | 优先选 Matt Pocock Skills | 优先选 Superpowers |
|---|---|---|---|
| 你最需要的是 | 从 idea 到 staging / production 的端到端软件工厂 | 把已有工程流程变得更适合 agent | 给 agent 套上强流程和强测试纪律 |
| 工作方式 | 像管理一个虚拟团队：产品、设计、工程、QA、发布各司其职 | 像给工程师工具箱加几把常用工具：需要哪个拿哪个 | 像安装一套流程护栏：agent 每步都要先检查该用什么 skill |
| 复杂度 | 最高，命令多，覆盖面广 | 最低，单个 skill 小，容易理解和改造 | 中等到偏高，流程强，自动触发多 |
| 对人的要求 | 需要会判断产品、设计和工程审查结果，适合管理多个并行任务 | 需要人主动选择何时用哪个 skill，适合有工程判断的人 | 适合把流程交给系统执行，人主要做批准和方向判断 |
| 最强场景 | 创业产品、快速迭代、并行 agent sprint、需要发布闭环 | 需求澄清、PRD、issue 拆分、TDD、架构改善、debug | 测试优先开发、长任务防跑偏、工作树隔离、任务间 review |
| 潜在代价 | 小任务可能显得重，学习成本较高 | 自动化程度较低，流程是否执行取决于调用者 | 简单任务可能被流程拉长，灵活性低一些 |
| 推荐落地方式 | 先只用 `/office-hours`、`/plan-ceo-review`、`/review`、`/qa`、`/ship`，确认收益后再扩展 | 先用 `/grill-with-docs`、`/to-prd`、`/to-issues`、`/tdd`、`/diagnose`，按项目需要补充 | 先在一个试验项目开启完整流程，观察 TDD、review、worktree 是否适配团队节奏 |

## 主要 skills 拆解

### GStack

- `/office-hours`：用于项目最早期。通过强问题重新定义产品和用户痛点，产出设计文档，供后续计划和实现使用。
- `/plan-ceo-review`：用于 feature idea 阶段。检查产品方向、范围、机会大小和用户价值，避免只按字面需求实现。
- `/plan-eng-review`：用于动手前。审查架构、数据流、边界、测试策略和隐藏假设。
- `/plan-design-review` / `/design-consultation`：用于 UI / 产品体验设计。前者审查计划中的界面状态和体验缺口，后者从零建立设计系统。
- `/review`：用于分支已有改动后。找 CI 可能发现不了的生产风险、完整性缺口和边界问题。
- `/investigate`：用于 bug / 性能 / 异常定位。先追踪数据流和假设，再修复。
- `/qa` / `/qa-only`：用于 staging 或本地可运行页面。真实浏览器测试，前者可修复，后者只出报告。
- `/ship` / `/land-and-deploy` / `/canary`：用于发布链路。负责测试、PR、合并、部署后验证和监控。
- `/cso` / `/benchmark`：用于安全和性能检查，覆盖 OWASP、STRIDE、Core Web Vitals 等方向。

### Matt Pocock Skills

- `/grill-me`：用于任何计划或设计早期。agent 连续追问，直到双方形成共享理解；如果问题能通过代码库回答，就先探索代码库。
- `/grill-with-docs`：用于项目级需求澄清。除了 grill，还会沉淀共享语言、`CONTEXT.md` 和 ADR，让后续 agent 少说废话、命名更一致。
- `/to-prd`：用于已有足够上下文后。把当前对话整理成 PRD，必要时探索 repo、补充用户故事，并提交为 issue。
- `/to-issues`：用于 PRD 后。把目标拆成可以独立执行的 vertical slice issues，适合并行 agent 或逐步交付。
- `/tdd`：用于实现 feature 或修 bug。确认行为、设计可测试接口、先写失败测试、最小实现、再重构。
- `/diagnose`：用于复杂 bug 或性能回归。复现、最小化、假设、插桩、修复、回归测试。
- `/improve-codebase-architecture`：用于周期性维护。找浅模块、边界混乱和耦合风险，让代码库更适合人和 agent 继续工作。
- `/zoom-out`：用于陌生代码区。让 agent 从系统层面解释当前代码，而不是陷入局部细节。

### Superpowers

- `brainstorming`：在写代码前触发。澄清真实目标、探索替代方案，并把设计分块展示给用户批准。
- `using-git-worktrees`：设计通过后触发。创建隔离工作区和分支，跑项目 setup，确认测试基线干净。
- `writing-plans`：规格批准后触发。把工作拆成非常小的任务，每个任务包含文件路径、代码方向和验证步骤。
- `executing-plans` / `subagent-driven-development`：计划通过后触发。按任务执行，必要时每个任务派 fresh subagent，并做两阶段审查。
- `test-driven-development`：实现时触发。要求 red-green-refactor，先看测试失败，再写最少代码让它通过。
- `requesting-code-review` / `receiving-code-review`：任务间触发。按计划审查并按 severity 分类，critical issue 阻塞继续。
- `systematic-debugging`：debug 时触发。用系统化根因分析代替猜测式修复。
- `verification-before-completion`：声明完成前触发。验证问题确实修好，避免只靠 agent 自述。
- `finishing-a-development-branch`：所有任务完成后触发。跑测试，给出 merge、PR、keep、discard 等收尾选项，并清理 worktree。

## 结论

一句话概括：

- GStack 是“虚拟软件团队”。
- Matt Pocock Skills 是“工程师可组合工具箱”。
- Superpowers 是“强流程护栏”。

如果只能选一套：

- 做产品、创业项目、需要从想法推进到上线：优先 GStack。
- 自己有工程判断，希望 agent 更好地配合现有工作流：优先 Matt Pocock Skills。
- 当前最大痛点是 agent 跑偏、跳测试、乱改：优先 Superpowers。

更务实的组合是：用 Matt Pocock 的 `/grill-with-docs` 和 `/tdd` 打好需求与实现基础；用 Superpowers 强制执行测试和 review；在需要产品、设计、QA、发布闭环时引入 GStack。

## 来源

- Garry Tan / GStack GitHub: <https://github.com/garrytan/gstack>
- GStack skills documentation: <https://github.com/garrytan/gstack/blob/main/docs/skills.md>
- Matt Pocock / Skills for Real Engineers GitHub: <https://github.com/mattpocock/skills>
- Matt Pocock / AI Hero: <https://www.aihero.dev/>
- Matt Pocock, "5 Agent Skills I Use Every Day": <https://www.aihero.dev/5-agent-skills-i-use-every-day>
- Matt Pocock, "Tracer Bullets: Keeping AI Slop Under Control": <https://www.aihero.dev/tracer-bullets>
- Matt Pocock, "My 'Grill Me' Skill Went Viral": <https://www.aihero.dev/my-grill-me-skill-has-gone-viral>
- Jesse Vincent / Superpowers GitHub: <https://github.com/obra/superpowers>
- Simon Willison, "Superpowers: How I'm using coding agents in October 2025": <https://simonwillison.net/2025/Oct/10/superpowers/>
