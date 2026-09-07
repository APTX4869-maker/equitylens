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

**Batch 1、Batch 2、Batch 3 与 Batch 4 的全部修复项均已完成；最终全量验证已通过，正在执行分支收尾。**

- Batch 1（正确数字与输入身份）：当前 TTM 契约、市场倍数回退、风险/研究失败覆盖、DCF 边界、估值输入指纹与结构化错误、前端完整草稿身份。
- Batch 2（可复现/来源/新鲜度）：D08 快照 SHA 严格匹配、D10 新鲜度语义、V05 完整估值 run 持久化、D09 派生结果来源身份。
- Batch 3 P02：新估值默认使用 `fcff_dcf.v2`；稳定期单独构造 year-6 NOPAT/再投资/FCFF，终值不再重复增长；默认、预览、情景、敏感性、反推、保存和前端草稿使用同一模型输入。
- Batch 3 P06：个人方案必须绑定同公司已保存 v2 run 与 base/bear/bull 情景；后端派生参考值，持久化来源指纹、注释、验证条件、版本与复核状态；前端可保存、打开、复制和比较。
- Batch 3 P08：四模块刷新独立提交并报告状态，失败模块可单独重试；活动页面读取刷新后的数据。财务或行情身份变化后，既有方案标记为 `needs_review`，未保存估值草稿保留但必须重新计算，刷新前启动的晚到请求不能解除过期状态。
- Batch 4 P01：每个 DCF 输入都有统一的来源类型、证据 ID 或配置版本、期间/日期、计算规则、采用理由及回退原因；AAPL/MSFT 增长路径有独立版本与理由。用户覆盖清除旧事实身份，股数口径由实际选择策略标记，不再按数量大小推断。
- Batch 4 P03：AAPL/MSFT 使用版本化公司情景故事与明确输入路径；AAPL Bear 支持首年 −5% 压力。Bear 不再把亏损利润率截到零，响应和页面列出完整投入/终值假设及相对草稿的精确差异。旧 run 缺新解释字段时明确显示旧版本缺口，不崩溃或补造故事。
- Batch 4 P05：风险 API/页面展示实际检查覆盖与失败原因，零命中不再掩盖未完成模块；风险严重度与证据置信度分离。所有数字风险和研究 claim 的证据 ID 可由 provenance API 解析；行情观察也成为可解析来源。规则检索助手对不支持问题返回能力边界，不再回退到无关总览。
- Batch 4 P04：新手估值按经营证据、数据期间、不确定性、参数调整、反推、安全边际、保存与复核顺序呈现；高级矩阵及原始元数据默认折叠。参数解释包含方向影响，WACC 不再被表述为承诺收益率；模式切换保留草稿。财务图表标题和可见单位随指标切换，切换公司会关闭指标与来源抽屉。

本轮复核发现原 Batch 2 记录的测试没有覆盖四个边界，并已在提交 `599ab10` 修复：

- SHA 选择器现在只接受 8 位十六进制前缀或完整 64 位 SHA；快照与 manifest 在发布前 `fsync`，并用进程锁避免并发发布丢失指针。
- ET/PT/CT/MT 行情时间按 IANA 时区转换为 UTC，夏令时和冬令时不再被误当 UTC 文本。
- 保存的估值 run 新增 `source_fact_ids`，冻结实际使用且可在 `canonical_fact` 中解析的事实身份；用户覆盖项会清除原事实身份。
- 派生结果 ID 改为带 SHA-256 校验的自包含内容身份，绑定值、公式、期间和有序输入；同期间重述会生成新 ID，旧 ID 仍解析原始根。

批次证据与逐项状态见 `docs/reviews/2026-09-06-remediation-batch1-rework.md` 与 `docs/reviews/2026-09-06-remediation-batch2-rework.md`。

## 验证

- 最终全量后端：**220 passed**，1 条既有 Starlette/httpx 弃用警告。
- Batch 3 P02 聚焦验证：估值 golden + API 共 74 passed；新增非法稳定期 ROIC API 回归 7 passed（聚焦集）。
- Batch 4 P01/P03：完整估值 golden + API **84 passed**；前端全部 Playwright **5 passed**。
- Batch 4 P05：研究 golden **16 passed**；风险/研究/API 聚焦 **12 passed**；新增边界浏览器测试 **2 passed**。
- Batch 4 P04：新增新手估值路径与财务/抽屉隔离浏览器验收，聚焦执行 **2 passed**。
- 前端：TypeScript `--noEmit --incremental false` 与 ESLint 通过。
- Playwright：使用系统 Chrome 实际运行 **9 passed**，覆盖受控乱序、失败草稿不可保存、方案保存/打开/复制/比较、刷新重载与单模块重试、刷新后强制重算、风险/研究边界、新手估值阅读路径、财务单位和抽屉公司隔离。

## 下一步

完成分支状态核对并按开发分支收尾流程选择集成方式。
