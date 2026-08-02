# GPT-5.6 Sol V5 Comparison Results

## 结论边界

本轮只生成 GPT‑5.6 Sol v5，并与已有 Claude v4 并排展示。由于模型和提示词版本同时变化，结果只能用于选择更喜欢的最终产物，不能把差异严格归因于模型。没有使用 LLM 评分。

- 请求模型：`gpt-5.6-sol`；API 响应模型：`gpt-5.6-sol`。
- 12 篇使用同一 v5 提示词哈希：`9f0202d42517bd8e0b7815bc11d0397abbaffb98584fc73632bb78743c5347df`。
- GPT 文章保留原始输出，没有执行 OpenCC 转换。

## 自动检查

- 全部 v5 格式条件通过：2/12
- 完全使用简体中文：12/12
- 位于 600–1,500 字符：12/12
- 一级/二级标题符合要求：12/12
- 至多一处块引用：12/12
- 不含引用时间戳：12/12
- 全文有 10–18 处加粗：12/12
- 每个实质段落有 2–4 处加粗：3/12
- GPT v5 加粗数高于对应 Claude v4：11/12
- 平均加粗数：Claude v4 6.75 → GPT v5 13.58

| 样本 | GPT 字符 | 简体 | 加粗 Claude→GPT | 实质段落密度 | GPT 格式失败 |
| --- | ---: | --- | ---: | --- | --- |
| S027-TUWDpYDTQEk | 1226 | 是 | 4→11 | 3, 2, 1, 1, 0, 1, 1, 2 | paragraph_bold_density_outside_2_4 |
| S036-MvjjO5wgUsE | 937 | 是 | 6→12 | 2, 2, 2, 2, 2, 1 | entire_sentence_bolded、paragraph_bold_density_outside_2_4 |
| S010-PnwOldwLuVM | 1178 | 是 | 3→13 | 2, 3, 1, 3, 1, 1, 2 | paragraph_bold_density_outside_2_4 |
| S052-c-MnSFGTSN8 | 1349 | 是 | 2→17 | 3, 1, 2, 1, 3, 2, 1, 2, 2 | entire_sentence_bolded、paragraph_bold_density_outside_2_4 |
| S019-C0gErQtnNFE | 1413 | 是 | 4→16 | 2, 1, 3, 2, 4, 2, 2 | paragraph_bold_density_outside_2_4 |
| S045-08SVa45XimY | 1366 | 是 | 5→13 | 2, 1, 1, 2, 2, 1, 1, 2 | entire_sentence_bolded、paragraph_bold_density_outside_2_4 |
| S046-WL3AGmQBJLQ | 1110 | 是 | 11→15 | 4, 2, 1, 2, 3, 2 | entire_sentence_bolded、paragraph_bold_density_outside_2_4 |
| S022-rQKis2Cfpeo | 1087 | 是 | 7→15 | 3, 2, 3, 2, 3, 2 | 无 |
| S005-fDQaadKysSA | 1274 | 是 | 7→16 | 3, 3, 3, 3, 3 | entire_sentence_bolded |
| S013-501pDaIMCQw | 999 | 是 | 7→11 | 2, 2, 2, 3, 2 | 无 |
| S002-7I3G21RyARs | 987 | 是 | 7→10 | 2, 2, 2, 2, 1, 1 | paragraph_bold_density_outside_2_4 |
| S003-TD4S8dj8D70 | 956 | 是 | 18→14 | 5, 2, 3, 2, 2 | paragraph_bold_density_outside_2_4 |

## 阅读入口

双栏全文对比见 `data/experiments/summary-prompt-v1/gpt-v5-vs-claude-v4.html`。
用户选定模型和提示词前，本实验不接入生产。
