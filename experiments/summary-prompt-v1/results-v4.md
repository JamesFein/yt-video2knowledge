# Summary Prompt V4 Results

## 范围

v4 只验证新增的代价与教训、人物背景和 Markdown 强调能力。共生成 12 篇，不重新生成或展示 v3。

- 12/12 篇请求均读取唯一配置模型 `claude-sonnet-5-cc`；API 响应模型标识为 `claude-sonnet-5`。
- 12/12 篇使用同一提示词哈希：`b19b341a6fda7dfab647213e0e2b4d28d09e53b240184154001abc63e989bf2c`。
- 元数据仅记录模型、提示词哈希、耗时、生成参数和 token 用量，不记录 API 密钥。

## 自动检查

- 全部自动条件通过：3/12
- 位于 600–1,500 字符：11/12
- 至少两处加粗：12/12
- 至多一处块引用：11/12
- 不含引用时间戳：12/12
- 自动引语匹配只验证同语种逐字片段；英文 transcript 的中文翻译引语仍需人工核对。

| 样本 | 字符数 | 加粗 | 块引用 | 自动失败 | 助手定向核对 |
| --- | ---: | ---: | ---: | --- | --- |
| S027-TUWDpYDTQEk | 938 | 4 | 1 | 无 | 有问题 |
| S036-MvjjO5wgUsE | 875 | 6 | 1 | untraceable_direct_quote | 通过 |
| S010-PnwOldwLuVM | 1063 | 3 | 1 | requires_two_to_four_h2、untraceable_direct_quote | 功能通过／格式失败 |
| S052-c-MnSFGTSN8 | 931 | 2 | 2 | more_than_one_blockquote、untraceable_direct_quote | 功能通过／格式失败 |
| S019-C0gErQtnNFE | 1420 | 4 | 1 | untraceable_direct_quote | 通过 |
| S045-08SVa45XimY | 1834 | 5 | 1 | outside_600_1500_chars、untraceable_direct_quote | 功能通过／长度失败 |
| S046-WL3AGmQBJLQ | 1288 | 11 | 1 | untraceable_direct_quote | 背景通过／负例未验证 |
| S022-rQKis2Cfpeo | 1139 | 7 | 0 | untraceable_direct_quote | 有问题 |
| S005-fDQaadKysSA | 1451 | 7 | 0 | 无 | 通过 |
| S013-501pDaIMCQw | 969 | 7 | 0 | untraceable_direct_quote | 通过（背景略密） |
| S002-7I3G21RyARs | 993 | 7 | 1 | untraceable_direct_quote | 通过 |
| S003-TD4S8dj8D70 | 1048 | 18 | 0 | 无 | 通过（加粗偏密） |

## 逐篇来源核对（助手）

- **S027-TUWDpYDTQEk · 有问题**：成功保留了关系、债务、过劳、抑郁和身体损伤构成的具体代价链，也提炼出原文明确给出的‘学会选择、敢于摆脱不利处境’。但人物介绍中的‘从2005年就开始做这类节目’不受 transcript 支持：原文只说‘我跟2005年状态又不一样了’，属于身份经历扩写。
- **S036-MvjjO5wgUsE · 通过**：完整保留了扣款后验证失败、白跑邮局、等待约6小时、故障持续数周的经历—代价链；教训与原文对上线前测试和破坏性变更的批评一致。人物背景未被强行添加。
- **S010-PnwOldwLuVM · 功能通过／格式失败**：年化54亿美元现金消耗、约1%留存率和迪士尼合作未落地构成了清楚的产品失败与商业代价，结论也由 transcript 明确支持；主播大飞的身份来自 transcript 开头。但文章只有1个二级标题，未满足2–4个二级标题要求。
- **S052-c-MnSFGTSN8 · 功能通过／格式失败**：人物姓名、清华经历、港科大角色和WiCi均来自 transcript；20份基金申请仅1份获批及‘主动求助’的后续改变也准确保留。但输出用了2处块引用，超过至多1处的约束。
- **S019-C0gErQtnNFE · 通过**：Demis Hassabis 的角色、诺贝尔奖、国际象棋与认知神经科学经历均由 transcript 前部明确介绍，并与理解其AI科学路线直接相关；正文对AlphaFold、AlphaGo和风险判断的归属清楚。
- **S045-08SVa45XimY · 功能通过／长度失败**：N同学的身份和向量模型经历来自 transcript 明确介绍；十几个AI编程窗口产出多数垃圾、收缩到两三个窗口并保护判断力的经历—代价—改变也被保留。但文章1834字符，超过1500字符上限。
- **S046-WL3AGmQBJLQ · 背景通过／负例未验证**：Christina、HBS senior lecturer、创业课及每年900多名学生都在 transcript 开头明确出现，输出没有证据表明来自标题补全。正因 transcript 已提供背景，本样本实际上不构成‘脚本未介绍人物’的负例，克制能力仍待另找样本确认。
- **S022-rQKis2Cfpeo · 有问题**：职业经理人失败、解雇两人并改用Debby Coleman的代价与教训均受原文支持；但 transcript 只出现姓氏‘Jobs’，输出补成‘史蒂夫·乔布斯’，严格按唯一事实来源规则属于借助常识或标题补全姓名。
- **S005-fDQaadKysSA · 通过**：没有强行增加人物背景或惨痛教训；KV cache、prefill/decode及各压缩方案的加粗能帮助扫读，7处强调没有整段加粗，结构和长度均合格。
- **S013-501pDaIMCQw · 通过（背景略密）**：Garry Tan的YC角色、投资和创业经历均可在 transcript 中追溯，GBrain等关键概念的加粗有效；人物履历略多，但没有压过系统的核心机制。
- **S002-7I3G21RyARs · 通过**：普通观点脚本没有被强行改写成惨痛教训；关键学习动作、人物与概念加粗清楚，一处块引用用于收束核心流程，格式回归正常。
- **S003-TD4S8dj8D70 · 通过（加粗偏密）**：多资讯结构仍能保留独立信息，没有强行添加人物介绍；关键产品、功能与数字可快速扫读。共18处加粗，视觉强调稍密，但没有整句或整段加粗。

以上是助手逐篇对照 transcript 的核对结果，不等于用户已经完成人工确认。

## 阅读入口

完整 12 篇文章见 `data/experiments/summary-prompt-v1/v4-review.md`。
用户确认前，v4 仍是研究候选，不接入生产。
