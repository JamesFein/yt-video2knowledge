# yt-video2knowledge

Local-first YouTube playlist digest workflow with a FastAPI Knowledge Site exposed through Cloudflare Tunnel.

## Quick Reference

- Test: `uv run python3 -m unittest discover -s tests -t .`
- Digest: `uv run yt-video2knowledge digest --target-date YYYY-MM-DD`
- Sync Knowledge Site: `uv run yt-video2knowledge sync-site --target-date YYYY-MM-DD`
- Run Knowledge Site: `uv run uvicorn yt_video2knowledge.site.app:create_app --factory --host 127.0.0.1 --port 8000`

## Repository Map

- `src/yt_video2knowledge/`: formal implementation; `digest/` produces artifacts and `site/` serves them.
- `tests/`: mirrors `digest`, `site`, and repository-local experiments.
- `prompts/production/`: prompts used by production code.
- `experiments/`: isolated prototypes and prompt research; production code must not import it.
- `integrations/`: thin external adapters; `tools/`: repository maintenance commands.
- `docs/`: guides, operations, plans, archive, ADRs, and agent instructions; `data/`: local runtime state.

Dependency direction: `cli → digest.run / site.sync`, `digest.run → digest domain modules`, `site.sync → digest.manifest`. Lower modules do not import orchestration or CLI.

## AI 代理工作原则

- **Think Before Coding:** 不要假设，不要隐藏困惑。先说清假设；多种解释并存时列出来；有更简单方案时指出；不清楚就停下并提问。
- **Simplicity First:** 用能解决问题的最少代码。不要加未请求的功能、单次使用抽象、投机式配置，或不可能场景的错误处理。
- **Surgical Changes:** 只碰必须改的地方。匹配现有风格；不要顺手重构；只清理自己改动产生的未用代码；每一行变更都应能追溯到用户请求。
- **Goal-Driven Execution:** 把任务转成可验证目标。修 bug 先复现，改验证先补测试，多步骤任务给出简短计划并循环到验证完成。

## Detailed Instructions

- [Knowledge Site Deployment](docs/agents/knowledge-site-deployment.md)

## Agent skills

### Issue tracker

Issues and PRDs are tracked in GitHub Issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Triage uses the five default canonical labels. See `docs/agents/triage-labels.md`.

### Domain docs

This repository uses a single-context domain documentation layout. See `docs/agents/domain.md`.
