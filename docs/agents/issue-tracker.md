# Issue tracker：GitHub

本仓库的 Issue 和 PRD 使用 GitHub Issues，repository 由当前 clone 的 `git remote -v` 决定。

> **验证状态（2026-08-04）**：本机已安装 `gh 2.97.0`，但尚未登录任何 GitHub host；tracker 配置已确认，远端 Issue 和 labels 尚未核验。完成 `gh auth login` 后才能执行或声称完成远端操作。

## 前置条件

Issue 操作使用 GitHub CLI `gh`。它不是 Digest 或 Knowledge Site 的运行依赖，也没有由当前 `Brewfile` 安装；只有执行 Issue/PR 工作流时才需要单独准备：

```bash
brew install gh
gh auth login
```

在 `gh` 不存在或未认证时，只报告前置条件缺失，不要假装已经读取或修改 GitHub Issue。

## 常用操作

- 创建 Issue：`gh issue create --title "..." --body "..."`。多行 body 使用 heredoc。
- 阅读 Issue：`gh issue view <number> --comments`，同时读取 labels。
- 列出 Issue：`gh issue list --state open --json number,title,body,labels,comments`，按任务需要增加 `--label` 或 `--state`。
- 评论：`gh issue comment <number> --body "..."`。
- 添加或移除 label：`gh issue edit <number> --add-label "..."` / `--remove-label "..."`。
- 关闭：`gh issue close <number> --comment "..."`。

在 clone 内运行时，`gh` 会根据 git remote 推断 repository。不要在脚本中重复硬编码 owner/repo，除非操作目标不是当前仓库。

## PR 是否作为需求入口

**否。** 当前 PR 不作为 feature request 的常规入口。

如果未来明确改变这一约定，PR 才与 Issue 使用相同的 triage 状态。对应命令包括：

- 阅读：`gh pr view <number> --comments` 和 `gh pr diff <number>`；
- 列表：`gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments`；
- 评论、label 和关闭：`gh pr comment`、`gh pr edit`、`gh pr close`。

GitHub 的 Issue 与 PR 共用编号空间。遇到裸编号 `#42` 时，先确认它是哪一种对象，再执行写操作。

## Skill 约定

- Skill 说“发布到 issue tracker”时：创建 GitHub Issue。
- Skill 说“读取相关 ticket”时：运行 `gh issue view <number> --comments`。
- Triage 使用的 label 映射见 [triage-labels.md](triage-labels.md)。

## Wayfinding 操作

Wayfinding 用一个 map Issue 管理一组 child Issue：

- **Map**：label 为 `wayfinder:map` 的单个 Issue，body 保存 Notes、Decisions-so-far 和 Fog。
- **Child ticket**：优先使用 GitHub sub-issue；不可用时，在 map task list 中链接，并在 child 顶部写 `Part of #<map>`。
- **类型 label**：`wayfinder:research`、`wayfinder:prototype`、`wayfinder:grilling`、`wayfinder:task`。
- **阻塞关系**：优先使用 GitHub native issue dependencies；不可用时，在 child 顶部写 `Blocked by: #<n>`。
- **可领取 frontier**：仍然 open、没有 open blocker、没有 assignee，并且在 map 顺序中最靠前的 child。
- **领取**：`gh issue edit <n> --add-assignee @me`；这是该流程第一次写操作。
- **完成**：先评论结论，再关闭 child，最后把稳定的上下文链接写回 map 的 Decisions-so-far。

使用 dependency API 时，`issue_id` 指 blocker 的 numeric database id，不是 `#number` 或 GraphQL `node_id`：

```bash
gh api repos/<owner>/<repo>/issues/<n> --jq .id
gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-database-id>
```

任何创建、评论、label、指派或关闭操作都会改变外部状态。除非用户请求或 Skill 工作流明确授权，否则只做读取。
