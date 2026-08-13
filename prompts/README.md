# Prompt Registry

这个目录是项目中应用级 system prompt 的唯一管理入口。生产提示词与历史实验提示词分开保存；视频标题、transcript、候选文章等动态 user message 仍由代码拼装。

## 当前生产提示词

| 文件 | 用途 | 调用位置 |
| --- | --- | --- |
| `production/summary-article-v5.md` | 根据完整 transcript 生成最终简体中文文章 | `src/yt_video2knowledge/digest/summary.py` |

`summary-article-v5.md` 是当前正式生产版本，包含 `中文标题：...` 输出协议和隐藏的 `<!-- SUMMARY_COMPLETE -->` 完成标记。修改完成标记时必须同时修改生产验证代码和测试。

## 实验提示词

`experiments/summary-prompt-v1/` 保存提示词研究的历史版本、分类器、类别增量和评审指令。这里的 `general-v5.md` 是 GPT‑5.6 Sol 对比实验使用的历史版本，不等于当前 `production/summary-article-v5.md`，不得用它覆盖生产提示词。

- `classifier.md`：实验样本分类。
- `general-v1.md` 至 `general-v5.md`：历次通用候选。
- `current-production.md`：实验开始时保存的历史生产基线，不代表当前生产提示词。
- `final-candidate.md`：v3 阶段的人工复核候选。
- `categories/`：四类压缩策略增量。
- `judge-pair.md`：匿名成对评审。
- `judge-stability.md`：重复生成稳定性评审。

生产提示词使用版本化文件名。升级时新增版本文件并显式更新代码引用，不静默覆盖旧版本。模型配置、API 密钥、运行输出和 transcript 不得放入本目录。
