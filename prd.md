# Knowledge Site 自动同步 PRD

## 问题陈述（Problem Statement）

用户已经完成了 2026-06-07 的 YouTube knowledge digest 运行，目标日期的 run 目录中已经生成了 daily overview、manifest、22 个 ready 视频摘要、metadata、transcript 和 thumbnail 产物。但 Knowledge Site 使用的 SQLite 读模型仍只同步到 2026-06-06，导致站点首页和日期详情页看不到 2026-06-07 的内容。

从用户视角看，digest 跑完应该意味着 Knowledge Site 也已经展示最新日期的数据。现在「处理完成」和「站点可见」之间存在手动同步步骤，而且同步缺失没有被纳入运行结果，容易造成静默的数据滞后。

## 解决方案（Solution）

在 digest 成功写完目标日期产物后，自动触发 Knowledge Site 的目标日期同步。同步应只刷新本次目标日期，把 `data/runs/YYYY-MM-DD` 作为源数据，把 SQLite 作为可重建的站点读模型，并复制必要的 transcript 和 thumbnail asset。

如果 digest 本身失败，不触发同步。如果 digest 成功但 Knowledge Site 同步失败，本次 CLI 应返回失败状态，并在输出中明确说明同步失败原因、目标日期、数据库路径和后续可重试方式。这样用户不会误以为「视频已跑完」就等同于「站点已更新」。

## 用户故事（User Stories）

1. 作为 knowledge digest 操作者，我希望在某个日期成功运行后 Knowledge Site 自动更新，这样我不必记住一条单独的同步命令。
2. 作为 Knowledge Site 读者，我希望最新处理完成的日期出现在站点首页，这样我可以立即阅读最新的每日知识摘要。
3. 作为操作者，我希望目标日期页面包含所有成功生成摘要的视频，这样站点能反映完整的运行产出。
4. 作为操作者，我希望 pending（待生成摘要）的视频被排除在公开视频列表之外，这样未完成的内容不会被当成成品展示。
5. 作为操作者，我希望 transcript 失败的视频被排除在公开视频列表之外，这样失败的处理不会产生破损的站点条目。
6. 作为操作者，我希望即使同一天的其他视频处于 pending 或 failed，ready 视频也能被导入，这样部分失败不会阻塞有用的已完成内容。
7. 作为读者，我希望每个导入的视频展示其最新的摘要 markdown，这样重跑和摘要修订能在站点上体现。
8. 作为读者，我希望同步后 transcript 和 thumbnail asset 可用，这样视频页面保持有用且视觉完整。
9. 作为读者，我希望同一天内视频保持稳定排序，这样每日页面在多次访问之间是可预测的。
10. 作为 meta-summary 编辑者，我希望手写的 meta summary 在重复同步后依然保留，这样运维同步永远不会覆盖用户撰写的笔记。
11. 作为操作者，我希望对同一日期重跑同步是幂等的，这样不会产生重复行或残留的 date-video 关联。
12. 作为操作者，我希望同步失败会让整条命令失败，这样自动化不会在站点仍然陈旧时静默报告成功。
13. 作为操作者，我希望每次运行后有清晰的同步报告，这样我能看到目标日期的导入、pending、failed 计数。
14. 作为操作者，我希望能对指定日期手动重跑同步，这样我能在不重跑视频处理的前提下从短暂的数据库或文件系统问题中恢复。
15. 作为操作者，我希望保留全量同步模式，这样在需要时能从历史 run 目录重建站点读模型。
16. 作为维护者，我希望 SQLite 写入是事务性的，这样畸形的源数据不会让站点停留在半更新状态。
17. 作为维护者，我希望 SQLite 锁竞争被优雅处理，这样运行中的 web app 和同步命令能共存。
18. 作为维护者，我希望 asset 复制避免半成品文件，这样被中断的同步不会留下损坏的 transcript 或 thumbnail。
19. 作为维护者，我希望同步使用与 web app 相同的数据库和 asset 配置，这样本地和部署视图不会漂移。
20. 作为维护者，我希望同步运行可审计，这样我能检查每个日期何时被导入、跳过了多少视频。
21. 作为未来的 agent，我希望 PRD 定义模块边界和数据更新规则，这样实现可以不必重新发现产品意图。
22. 作为未来的 agent，我希望 PRD 记录边缘情况，这样实现能有意识地处理常见失败模式。

## 实现决策（Implementation Decisions）

- digest workflow 仍然是已产出内容的事实来源（source of truth）。Knowledge Site 的 SQLite 数据库是一个可以从 run 目录重建的读模型。
- 自动同步只应在 digest workflow 成功写完目标日期的 daily overview 和 manifest 之后发生。
- 自动同步应适用于普通的日期运行、pending-summary 重试，以及更新某个目标日期 run 目录的单视频重跑。
- 自动同步不应适用于认证、登录引导、profile 播种，或其他不产生目标日期内容运行的模式。
- 同步接口应接受一个可选的目标日期。提供目标日期时只同步该日期；省略时保留现有的全量历史同步行为，用于恢复和重建。
- 同步 CLI 应在保留当前全量同步默认行为的同时，暴露目标日期同步能力。
- 同步输出应包含目标日期、数据库路径、导入视频数、pending 数、failed 数，以及本次是自动还是手动。
- digest 命令在 digest 生成成功后若自动同步失败，应返回非零退出码。
- 同步应在每个目标日期一个 SQLite 事务内运行，使 `days`、`videos`、`day_videos`、`video_meta_summaries`、`sync_runs` 保持一致。
- `days` 应按日期 upsert，写入最新的 daily overview markdown 和同步时间戳。
- `videos` 应按 video ID upsert，写入 title、channel、URL、duration、upload date、摘要 markdown、transcript asset 路径、thumbnail asset 路径和更新时间戳。
- `day_videos` 应在每次同步时按目标日期重建，使被移除、重排或新就绪的视频被准确反映。
- `video_meta_summaries` 应仅在缺失时插入。已有内容绝不能被同步覆盖。
- `sync_runs` 应为每次成功的日期同步追加一条审计行，包含导入、pending、failed 计数。
- ready 视频由 `processing_status = summary_ready` 且存在预期的摘要 markdown 文件共同决定。
- pending 视频和缺摘要的 ready 记录不应导入视频列表；它们在审计中计为 pending。
- transcript 失败的视频不应导入视频列表；它们在审计中计为 failed。
- 缺失的 transcript 或 thumbnail asset 不应阻塞视频导入。对应的 asset 路径应保持为空。
- 畸形的 manifest 或 metadata JSON 应使该目标日期同步失败，并回滚该日期的 SQLite 变更。
- SQLite 连接应被配置为能容忍来自运行中 web app 的正常读写竞争。
- asset 复制应使用安全写入策略，避免在中断后留下半成品目标文件。
- 除非锁处理或审计正确性需要，否则实现应避免 schema 变更。现有表已经表达了所需的领域模型。
- 当前 2026-06-07 的缺口应在该机制存在后，通过运行目标日期同步来修复，而不重跑视频处理。
- 将本 PRD 发布到 issue tracker 被有意推迟，因为本上下文中没有仓库 issue tracker 配置和分诊标签词表。

## 数据流（Data Flow）

源数据布局（每个 run 目录）：

```
data/runs/2026-06-07/
├── daily-overview.zh-CN.md          # days.daily_summary_markdown 的来源
├── manifest.json                    # processed_videos / pending_summary_videos / failed_videos 等
└── videos/<video_id>/
    ├── metadata.json                # 与 manifest 记录合并，metadata 优先
    ├── summary.zh-CN.md             # videos.summary_markdown 的来源；缺失 → 计为 pending
    ├── transcript.original.txt      # 复制到 assets_dir/transcripts/<id>.txt
    └── thumbnail.webp|jpg|jpeg|png  # 复制到 assets_dir/thumbnails/<id>.<ext>
```

端到端流程（单个目标日期）：

```
digest 成功写完目标日期产物
        │
        ▼
自动同步（仅目标日期）── 失败 ──► CLI 返回非零，打印目标日期 + db_path + 重试命令
        │ 成功
        ▼
打开 1 个 SQLite 事务（per 目标日期）
   1. 读 manifest.json → 构建 records 索引（processed_videos / failed_videos）
   2. 读 daily-overview.zh-CN.md → upsert days 行
   3. DELETE FROM day_videos WHERE day_date = 目标日期   # 重建排序，清掉残链
   4. 按 videos/ 子目录名排序遍历，逐个判定状态：
        pending_summary          → 计入 pending，跳过
        transcript_failed        → 计入 failed，跳过
        summary_ready 但缺 summary.zh-CN.md → 计入 pending，跳过
        summary_ready 且有 summary → 导入：
            - 复制 transcript / thumbnail asset（缺失则路径留空）
            - upsert videos 行
            - INSERT OR IGNORE video_meta_summaries（保护用户笔记）
            - upsert day_videos(day_date, video_id, position)
   5. INSERT sync_runs 审计行（imported / pending / failed 计数）
        │
        ▼
提交事务 → web app 下次读到的就是该日期的完整读模型
```

关键不变量（invariants）：

- **源是真相，DB 可重建**：任意时刻删库后从 `data/runs/` 全量同步应得到等价读模型（用户笔记除外，见下）。
- **目标日期隔离**：目标日期同步只触碰该 `day_date` 的行，其他日期不受影响。
- **顺序由目录名决定**：`position` 来自 `videos/` 子目录排序，保证页面排序稳定且可预测。

## 表的变化（Table Changes）

本节分两部分：A. 现有 schema 下每次同步引发的**行级数据变化**（不改 DDL，与现有代码一致）；B. 可选的 **schema 增强建议**（默认不采纳，除非锁处理/审计需要）。

### A. 每次目标日期同步的行级变化

现有 5 张表（见 `knowledge_site/database.py`，`SCHEMA_VERSION = 1`），同步对每张表的写法：

| 表 | 操作 | 键 | 语义 | 幂等性 |
|----|------|----|------|--------|
| `days` | UPSERT | `day_date` (PK) | 写入最新 daily overview 与 `synced_at` | 是，重跑覆盖同一行 |
| `videos` | UPSERT | `video_id` (PK) | 全量字段刷新（title/channel/url/duration/upload_date/summary/asset 路径/`updated_at`） | 是，重跑覆盖同一行 |
| `day_videos` | DELETE 整段 + 重新 INSERT | `(day_date, video_id)` (PK) | 先 `DELETE WHERE day_date=?` 再按新顺序插入，反映移除/重排/新就绪 | 是，重建即幂等 |
| `video_meta_summaries` | INSERT OR IGNORE | `video_id` (PK) | 仅在缺失时建空行；**已有内容永不覆盖** | 是，且保护用户撰写内容 |
| `sync_runs` | INSERT（追加） | `id` AUTOINCREMENT | 每次成功同步追加一条审计行 | **否（有意为之）**：每次运行都新增一行，形成历史 |

要点：

- 同一目标日期重跑同步是幂等的（`days`/`videos`/`day_videos` 收敛到同一状态），唯一单调增长的是 `sync_runs` 审计历史——这是设计意图，用于审计「何时同步、跳过多少」。
- `day_videos` 采用「先删后建」而非纯 upsert，是为了让**从源中消失的视频**（例如某视频从 ready 退回 pending，或被移出当天）能从当天列表中正确移除——纯 upsert 做不到删除。
- `video_meta_summaries` 是唯一对同步「只读保护」的表：同步只会 `INSERT OR IGNORE` 占位空行，用户后续手写的 `content` 在任何重同步中都保留。

### B. 可选的 Schema 增强建议（默认不采纳）

以下变更**不属于本次范围**，仅在「锁处理或审计正确性」确有需要时引入，并且要走迁移 + `SCHEMA_VERSION` 升级（`database.py` 已有版本校验，不匹配会抛 `SchemaVersionError`）。每条都附 UP/DOWN 思路：

1. **`day_videos(day_date)` 索引** — 当前 `day_videos` 的 PK 是 `(day_date, video_id)`，按 `day_date` 前缀查询已可用复合主键，**无需额外索引**。仅当出现按 `video_id` 单独查询的热点时，才考虑 `CREATE INDEX idx_day_videos_video ON day_videos(video_id)`。
2. **`sync_runs.mode` 字段** — 区分本次是自动（auto）还是手动（manual）。审计需求若要可查询，可加 `mode TEXT NOT NULL DEFAULT 'auto'`。
   - UP：`ALTER TABLE sync_runs ADD COLUMN mode TEXT NOT NULL DEFAULT 'auto';`
   - DOWN：SQLite 不支持 DROP COLUMN（旧版本），需重建表回退。
   - 注意：用 `DEFAULT 'auto'` 保证旧行可读，符合「加 NOT NULL 必带默认值」原则。
3. **`sync_runs.status` 字段** — 当前只在成功路径写审计行；若希望失败也留痕（便于「同步失败可重试」排查），可加 `status TEXT NOT NULL DEFAULT 'success'`，并在回滚前写一条 `failed` 行（需放在事务外或独立连接，避免被回滚）。
   - 这是真正需要权衡的点：审计行如果在同一事务里，回滚会连审计一起回滚；要留失败痕迹必须用独立写入路径。
4. **`days.video_count` 去规范化列** — 若首页需要展示每日视频数且 JOIN `day_videos` 成为读热点，可加缓存列。但这违反「源是真相」的简洁性，**不建议**，除非有实测性能问题。

结论：遵循现有「除非锁/审计必要否则不改 DDL」的决策，**默认只发生 A 节的行级变化，不引入 B 节**。B 节作为有意识的预案记录在此，避免未来重新发现。

## 边缘情况与容错处理（Edge Cases & Fault Tolerance）

| 边缘情况 | 检测点 | 处理策略 | 对计数/状态的影响 |
|----------|--------|----------|--------------------|
| digest 失败 | CLI 调用前 | 不触发同步 | 站点保持原状，不产生 sync_run |
| digest 成功但同步失败 | 同步异常向上抛出 | 事务回滚；CLI 返回非零，打印目标日期 + `db_path` + 重试命令 | 该日期无任何 DB 变更落地 |
| `manifest.json` 缺失 | `_load_json` 返回 `{}` | 视为无 manifest 记录；仍可凭 `videos/` 下 metadata 导入 | 仅凭 metadata 判定状态 |
| `manifest.json` 畸形 JSON | `json.loads` 抛异常 | 异常冒泡 → 事务回滚 → 该日期同步失败 | 该日期回滚，不留半更新 |
| `metadata.json` 畸形 JSON | `json.loads` 抛异常 | 同上，该日期回滚 | 该日期回滚 |
| `daily-overview.zh-CN.md` 缺失 | `_read_text` 返回 `""` | `days.daily_summary_markdown` 写空串（列为 NOT NULL，空串合法） | days 行仍 upsert |
| `summary.zh-CN.md` 缺失（但状态 ready） | `summary_path.exists()` 为假 | 跳过导入，计入 pending | imported 不增，pending +1 |
| 视频状态 `pending_summary` | manifest/metadata 状态 | 跳过，不进视频列表 | pending +1 |
| 视频状态 `transcript_failed` | 状态或 `failure_stage` | 跳过，不进视频列表 | failed +1 |
| 状态既非 ready/pending/failed | `status != READY_STATUS` | 静默跳过（既不导入也不计 pending/failed） | 不计数（潜在盲区，见下注） |
| transcript asset 缺失 | `source.exists()` 为假 | `transcript_path` 留空，不阻塞导入 | 仍 imported +1 |
| thumbnail asset 缺失（所有扩展名都没有） | 遍历 `THUMBNAIL_EXTENSIONS` 未命中 | `thumbnail_path` 留空，不阻塞导入 | 仍 imported +1 |
| asset 复制中断 | 复制使用安全写入策略 | 避免留下半成品目标文件（不产生损坏 asset） | 不影响 DB 一致性 |
| 同一日期重复同步 | `day_videos` 先删后建 + 各表 upsert | 幂等收敛，无重复行、无残留链 | `sync_runs` 仍追加审计行 |
| 视频从 ready 退回 pending（重跑后） | `day_videos` 整段重建 | 该视频从当天列表移除 | 下次 imported 反映减少 |
| 用户手写 meta summary | `INSERT OR IGNORE` | 已有内容永不覆盖 | `content` 保留 |
| SQLite 被 web app 占用（锁竞争） | 连接配置容忍正常读写竞争 | 优雅处理，避免与运行中 web app 冲突 | 同步与 web app 共存 |
| 目标日期 run 目录不存在 | `_iter_day_dirs` 不含该日期 | 该日期不产生任何变更 | 无 sync_run |
| run 目录名非 `YYYY-MM-DD` | `re.fullmatch` 过滤 | 忽略该目录 | 不参与同步 |

**注（潜在盲区）**：当前实现中「状态既非 ready 也非 pending/failed」的视频会被静默跳过且不计入任何审计计数（`sync.py:110-111`）。这意味着 `imported + pending + failed` 不一定等于目录中视频总数。实现/测试时应留意：要么把未知状态归入某一计数桶，要么在报告中显式标注「未分类」数量，以免审计出现「凭空消失」的视频。

## 测试决策（Testing Decisions）

- 测试应验证外部行为：数据库行、被保留的 meta summary、CLI 退出码、同步报告。测试应避免断言私有 helper 的实现细节。
- 现有 Knowledge Site 同步测试是导入行为、asset 复制、重复视频、重同步行为、meta-summary 保留的主要先例（`tests/test_knowledge_site_sync.py`）。
- 为目标日期同步增加测试：验证定向同步只更新请求的日期，其他日期保持不变。
- 为 ready/pending/failed/缺摘要混合记录增加测试：验证导入、pending、failed 计数。
- 为重复目标日期同步增加测试：验证幂等性和用户撰写 meta summary 内容的保留。
- 为畸形 JSON 或不可读源数据增加测试：验证事务回滚和非成功报告。
- 为缺失 transcript 和 thumbnail asset 增加测试：验证 ready 视频仍以空 asset 路径导入。
- 增加 CLI 级测试：验证手动目标日期同步报告正确的计数。
- 增加 CLI 级测试：验证 digest 成功后同步失败返回非零状态。
- 增加 CLI 级测试：验证非内容模式不会尝试自动站点同步。
- 手动验证应在同步 2026-06-07 后查询 SQLite，确认该日期有 1 条 `days` 行和 22 条 `day_videos` 行。
- 手动验证应加载运行中的 Knowledge Site，确认 2026-06-07 作为最新日期出现在首页。

## 范围之外（Out of Scope）

- 对历史视频重新处理、重新转写或重新生成摘要。
- 改变 Knowledge Site 的视觉设计或页面导航。
- 用其他数据库替换 SQLite。
- 增加后台调度器、守护进程、webhook 或文件监听器。
- 在未确认 issue tracker 配置的情况下将本 PRD 发布到 issue tracker。
- 为 Knowledge Site 构建新的部署流水线。
- 把 VTT 字幕文件导入 SQLite。
- 在存在规范摘要 markdown 时导入遗留的重复报告文件。
- 覆盖或重新生成用户撰写的 meta summary。
- 让 failed 或 pending 视频以正常完成视频的形式可见。
- 增加超出同步机制所需的新公开 API。

## 补充说明（Further Notes）

当前观察到的缺口是具体的：2026-06-07 的 run 目录存在并包含 22 个 summary-ready 视频，而 Knowledge Site 数据库只有到 2026-06-06 的日期。本 PRD 将其视为一次**同步契约失败**，而非内容生成失败。

期望的长期契约很简单：某个日期的一次成功 digest 运行，应当让对应的 Knowledge Site 读模型对同一日期保持最新。如果做不到，命令应当让失败可见、可重试。
