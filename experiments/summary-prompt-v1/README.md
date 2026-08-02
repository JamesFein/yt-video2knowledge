# Summary Prompt V1

这个目录只保存可版本控制的提示词、评价标准和研究结论。原 transcript、历史总结、模型响应及评分位于 Git 忽略的 `data/experiments/summary-prompt-v1/`。

所有模型调用都从仓库根目录的 `新的文字简写模型.txt` 读取唯一的模型配置。不得把其中的密钥复制到本目录、日志或结果文件。

## 执行顺序

```bash
uv run python experiments/summary-prompt-v1/run_experiment.py sample
uv run python experiments/summary-prompt-v1/run_experiment.py classify --allow-config-key
uv run python experiments/summary-prompt-v1/run_experiment.py generate --allow-config-key
uv run python experiments/summary-prompt-v1/run_experiment.py evaluate --allow-config-key
uv run python experiments/summary-prompt-v1/run_experiment.py report
uv run python experiments/summary-prompt-v1/run_experiment.py generate-v2 --allow-config-key
uv run python experiments/summary-prompt-v1/run_experiment.py evaluate-v2 --allow-config-key
uv run python experiments/summary-prompt-v1/run_experiment.py report-v2
uv run python experiments/summary-prompt-v1/run_experiment.py generate-v3 --allow-config-key
uv run python experiments/summary-prompt-v1/run_experiment.py evaluate-v3 --allow-config-key
uv run python experiments/summary-prompt-v1/run_experiment.py report-v3
```

各阶段均跳过已经存在的成功结果，方便在人工讨论分类或提示词后继续。`sample` 不调用模型；其余阶段会使用配置文件中的唯一模型。

## 人工检查点

1. `classify` 后先阅读 `classification-report.md`，确认类别及合并方向。
2. `generate` 后抽查每类输出，必要时新增 `v2` 提示词；最多修订两轮。
3. `report` 后按 `review-index.jsonl` 匿名复核每类 2–3 篇典型文章。

v1 若证明类别增量没有稳定收益，则用 `v2` 验证自适应通用提示词；若规则过多损害质量，再用 `v3` 做最后一次精简修订。所有旧产物保持不变。

只有在用户明确授权使用配置文件中的当前密钥后，才可给联网阶段传入 `--allow-config-key`。
