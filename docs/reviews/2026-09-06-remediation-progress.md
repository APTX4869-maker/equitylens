# EquityLens 修复返工进度

日期：2026-09-07

执行分支：`codex/remediation-rework`

依据：

- `docs/reviews/2026-09-05-equitylens-remediation-handoff.md`
- `docs/reviews/2026-09-06-remediation-quality-review.md`
- `docs/superpowers/specs/2026-09-06-remediation-rework-design.md`
- `docs/superpowers/plans/2026-09-06-remediation-batch1.md`
- `docs/reviews/2026-09-06-remediation-batch1-rework.md`
- `docs/reviews/2026-09-06-remediation-batch2-rework.md`
- `docs/reviews/2026-09-06-remediation-batch3-rework.md`
- `docs/reviews/2026-09-07-remediation-batch4-rework.md`

## 当前状态

**修复已无冲突快进合并到本地 `main`。合并后后端 251 passed、TypeScript/ESLint 通过、Playwright 12 passed；第二轮独立复审未发现新的 Critical 或 Important。本机仓库尚未配置 Git 远端，因此推送和 PR 等待远端配置。**

- Batch 1（正确数字与输入身份）：当前 TTM 契约、市场倍数回退、风险/研究失败覆盖、DCF 边界、估值输入指纹与结构化错误、前端完整草稿身份。
- Batch 2（可复现/来源/新鲜度）：D08 快照 SHA 严格匹配、D10 新鲜度语义、V05 完整估值 run 持久化、D09 派生结果来源身份。
- Batch 3 P02：新估值默认使用 `fcff_dcf.v2`；稳定期单独构造 year-6 NOPAT/再投资/FCFF，终值不再重复增长；默认、预览、情景、敏感性、反推、保存和前端草稿使用同一模型输入。
- Batch 3 P06：个人方案必须绑定同公司已保存 v2 run 与 base/bear/bull 情景；后端派生参考值，持久化来源指纹、注释、验证条件、版本与复核状态；前端可保存、打开、复制和比较。
- Batch 3 P08：四模块刷新独立提交并报告状态，失败模块可单独重试；活动页面读取刷新后的数据。财务或行情身份变化后，既有方案标记为 `needs_review`，未保存估值草稿保留但必须重新计算，刷新前启动的晚到请求不能解除过期状态。
- Batch 4 P01：每个 DCF 输入都有统一的来源类型、证据 ID 或配置版本、期间/日期、计算规则、采用理由及回退原因；AAPL/MSFT 增长路径有独立版本与理由。用户覆盖清除旧事实身份，股数口径由实际选择策略标记，不再按数量大小推断。
- Batch 4 P03：AAPL/MSFT 使用版本化公司情景故事与明确输入路径；AAPL Bear 支持首年 −5% 压力。Bear 不再把亏损利润率截到零，响应和页面列出完整投入/终值假设及相对草稿的精确差异。旧 run 缺新解释字段时明确显示旧版本缺口，不崩溃或补造故事。
- Batch 4 P05：风险 API/页面展示实际检查覆盖与失败原因，零命中不再掩盖未完成模块；风险严重度与证据置信度分离。所有数字风险和研究 claim 的证据 ID 可由 provenance API 解析；行情观察也成为可解析来源。规则检索助手对不支持问题返回能力边界，不再回退到无关总览。
- Batch 4 P04：新手估值按经营证据、数据期间、不确定性、参数调整、反推、安全边际、保存与复核顺序呈现；高级矩阵及原始元数据默认折叠。参数解释包含方向影响，WACC 不再被表述为承诺收益率；模式切换保留草稿。财务图表标题和可见单位随指标切换，切换公司会关闭指标与来源抽屉。
- 总览补修：趋势标题、可见单位和图表格式随指标切换；Overview KPI 返回并打开匹配的派生结果身份。TTM KPI 使用当前窗口契约，来源树展示结果值、公式、期间与完整输入。
- 验收矩阵补测：补齐 52/53 周、财年变更、同日多概念、重复期间、双快照端到端、失败不发布半套快照和零分母状态；修复同日选择、离线重放路径、快照组原子发布与零分母缺失状态。
- 真实库迁移：对 25 MiB 数据库和 46 个原始快照做 SHA-256 校验备份；财务、分部、管理层和行情在副本连续重放两次，11 个业务表语义摘要幂等，11 条旧 v1 估值运行原字段不变。候选库与演练摘要一致后已原子切换，外部备份和同目录回滚库均保留。
- 迁移链路补修：管理层离线重放现在完整使用调用方传入的 `raw_dir`，副本恢复不再隐式依赖真实原始数据目录。

本轮复核发现原 Batch 2 记录的测试没有覆盖四个边界，并已在提交 `599ab10` 修复：

- SHA 选择器现在只接受 8 位十六进制前缀或完整 64 位 SHA；快照与 manifest 在发布前 `fsync`，并用进程锁避免并发发布丢失指针。
- ET/PT/CT/MT 行情时间按 IANA 时区转换为 UTC，夏令时和冬令时不再被误当 UTC 文本。
- 保存的估值 run 新增 `source_fact_ids`，冻结实际使用且可在 `canonical_fact` 中解析的事实身份；用户覆盖项会清除原事实身份。
- 派生结果 ID 改为带 SHA-256 校验的自包含内容身份，绑定值、公式、期间和有序输入；同期间重述会生成新 ID，旧 ID 仍解析原始根。

批次证据与逐项状态见 `docs/reviews/2026-09-06-remediation-batch1-rework.md` 与 `docs/reviews/2026-09-06-remediation-batch2-rework.md`。

## 验证

- 切换后全量后端：**231 passed**，1 条既有 Starlette/httpx 弃用警告；新增用例验证管理层离线重放只读取指定副本目录。
- Batch 3 P02 聚焦验证：估值 golden + API 共 74 passed；新增非法稳定期 ROIC API 回归 7 passed（聚焦集）。
- Batch 4 P01/P03：完整估值 golden + API **84 passed**；前端全部 Playwright **5 passed**。
- Batch 4 P05：研究 golden **16 passed**；风险/研究/API 聚焦 **12 passed**；新增边界浏览器测试 **2 passed**。
- Batch 4 P04：新增新手估值路径与财务/抽屉隔离浏览器验收，聚焦执行 **2 passed**。
- 前端：TypeScript `--noEmit --incremental false` 与 ESLint 通过。
- Playwright：切换后使用系统 Chrome 实际运行 **10 passed**，覆盖总览指标/来源、受控乱序、失败草稿不可保存、方案保存/打开/复制/比较、刷新重载与单模块重试、刷新后强制重算、风险/研究边界、新手估值阅读路径、财务单位和抽屉公司隔离。未指定系统 Chrome 的首次命令因 Playwright 缓存浏览器不存在而在启动前失败，不属于产品测试失败。

## 下一步

1. 修复摄取与刷新身份、时间、版本路径和锁释放问题。
2. 修复估值年度一致性、输入边界、方案复核与 Reverse DCF API 契约。
3. 修复前端局部重试和 Reverse DCF 竞态。
4. 恢复真实库来源时间并重新执行迁移核对、全量验证和合并前审查。

2026-09-11 第一组已完成：财务刷新身份、分部版本路径、SEC 离线抓取时间与刷新锁释放均已有失败回归和修复；聚焦验证 22 + 8 passed。下一步执行估值后端组。

2026-09-11 第二组已完成：DCF 同财年输入、最新资产负债表桥接、正 WACC、待复核方案复制和 Reverse DCF 结构化错误契约已修复；新增反例 8 passed，估值 golden + API 95 passed。下一步执行前端状态组。

2026-09-11 第三组已完成：局部模块重试保持估值复核代数，Reverse DCF 响应绑定完整请求身份；TypeScript、ESLint 和组合 Playwright 5 passed。下一步恢复真实库来源时间并做最终验收。

2026-09-11 第四组已完成：恢复真实库 22 条来源抓取时间，为 42 个快照补齐可回放 manifest，严格副本演练 5 项通过；最终后端 245 passed、TypeScript/ESLint 通过、Playwright 11 passed。下一步独立复审 `d3cf2c2..HEAD`。

2026-09-11 独立复审补修 1 已完成：Reverse DCF 请求进行中修改假设或目标价时，旧请求保持作废且同步解除加载状态；新增按钮恢复断言先失败、修复后聚焦 Playwright 1 passed。下一步核对独立复审剩余边界并做最终全量验证。

2026-09-11 独立复审补修 2 已完成：税率只有税费、只有税前利润或税前利润为零时，数值和来源元数据统一采用带原因的配置回退；聚焦测试 3 passed。下一步隔离公司切换期间迟到的刷新响应。

2026-09-11 独立复审补修 3 已完成：刷新响应绑定发起公司和请求序号，切换公司会作废旧请求且迟到响应不再写入当前公司的消息、失败模块和重试入口；聚焦竞态 Playwright 1 passed。下一步补齐 Reverse DCF 非对象 `assumptions` 的结构化 400。

2026-09-11 独立复审补修 4 已完成：Reverse DCF 显式提供的 `assumptions` 必须为 JSON 对象，字符串、数组和 `null` 统一返回 `field=assumptions` 的结构化 400；非法输入聚焦测试 7 passed。下一步最终全量验证和第二轮独立复审。

2026-09-11 独立复审补修全量验证已完成：后端 251 passed，TypeScript 与 ESLint 通过，系统 Chrome Playwright 12 passed，Git 差异检查通过；仅有 1 条既有 Starlette/httpx 弃用警告。下一步第二轮独立复审 `edb0e1c`。

2026-09-11 第二轮独立复审已完成：4 个 Important 均关闭，未发现新的 Critical 或 Important；独立聚焦验证后端 10 passed、系统 Chrome 竞态 6 passed，TypeScript、ESLint 和 `git diff --check` 通过，工作树干净。当前进入分支集成选择。

2026-09-11 本地集成进行中：`codex/remediation-rework` 已无冲突快进合并到 `main`。合并后验收发现行情黄金测试依赖真实当前日期，MSFT 的固定 2026-09-03 快照跨过 7 天边界后由 `OK` 变为 `STALE`；黄金测试现固定在快照捕获次日，生产新鲜度逻辑不变，行情聚焦测试 9 passed。下一步重新执行合并后全量验收。

2026-09-11 本地集成已完成：合并后的 `main` 后端 251 passed，TypeScript 通过，ESLint 串行复跑通过，系统 Chrome Playwright 12 passed；仅有 1 条既有 Starlette/httpx 弃用警告。本机没有配置 Git 远端，暂不能推送或创建 PR；保留 `codex/remediation-rework` 作为后续 PR 源分支。
