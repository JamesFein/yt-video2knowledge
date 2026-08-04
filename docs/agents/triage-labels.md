# Triage label 映射

Agent Skill 使用五种 canonical triage 角色。下表把这些角色映射到本仓库约定的 GitHub label 字符串。

> **验证状态（2026-08-04）**：本机已安装 `gh 2.97.0`，但尚未登录 GitHub；以下映射是已确认的仓库约定，但尚未与远端 labels 核验。

| Skill 中的角色 | 本仓库 label | 含义 |
| --- | --- | --- |
| `needs-triage` | `needs-triage` | Maintainer 尚未评估 |
| `needs-info` | `needs-info` | 等待报告者补充信息 |
| `ready-for-agent` | `ready-for-agent` | 规格完整，可交给 AFK agent |
| `ready-for-human` | `ready-for-human` | 需要人类实现或判断 |
| `wontfix` | `wontfix` | 决定不处理 |

Skill 提到某种角色，例如“应用 AFK-ready label”时，使用表格右侧的精确字符串，不翻译 label 本身。

GitHub CLI 是独立前置工具。如果当前环境无法运行 `gh label list`，不要声称已经验证远端 label；先按 [Issue tracker 说明](issue-tracker.md) 准备并认证 `gh`。如果远端实际名称与本表不同，应更新本表，而不是让每个 agent 自行猜测。
