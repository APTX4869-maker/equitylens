# EquityLens 修复返工 Batch 4 证据记录

日期：2026-09-07。分支：`codex/remediation-rework`。执行计划：`docs/superpowers/plans/2026-09-07-remediation-batch4.md`。

## 当前状态

P01、P03、P05、P04 均已完成。总览趋势标题/单位及 KPI 来源入口的复核缺口已补齐；下一步补原交接验收矩阵的剩余边界。

## P01 默认假设来源

- `DcfInputs` 的每个字段都有同名元数据。统一字段包括 `source_type`、`source`、`source_ids`、`as_of`、`version`、`rule`、`reason` 与 `fallback_reason`。
- SEC 事实、确定性公式、配置假设与用户覆盖使用不同来源类型。保存 run 继续从 `fact_ids` 兼容字段冻结实际 canonical fact 身份。
- 配置升级为 `valuation-defaults.v4`，记录增长、利润率路径、税率/D&A/CapEx 回退、营运资金、资本权重、永续增长、ERP、beta、债务成本和稳定期 ROIC 的规则与理由。
- AAPL 与 MSFT 使用不同的发行人增长路径、版本和业务理由；历史 CAGR 仅作参考，不直接变成未来预测。
- 税率明确使用最新同财年有效税率，无法识别一次性项目时不会声称已经正常化；事实不足时才使用带原因的 17% 配置回退。
- 估值页面在五个可编辑假设旁显示公司默认理由、来源类型、期间或版本、计算规则和回退原因。
- 股数口径来自已选择的 FY 稀释加权股数策略。用户覆盖股数时标签变为 `user-supplied share count`，不再按股数大小猜测。

回归证据：

- 新增默认元数据 golden/API 契约与用户覆盖身份测试。
- `tests/golden/test_golden_valuation.py` + `tests/integration/test_api.py`：**82 passed**，1 条既有 Starlette/httpx 弃用警告。
- 前端 TypeScript `--noEmit` 与 ESLint 通过。

## P03 可解释压力情景

- 配置升级到 v5；AAPL/MSFT 分别有版本化的悲观、中性、乐观公司故事、五年收入路径、利润率变化、WACC 变化与稳定增长变化。
- AAPL 悲观情景首年收入增长为 −5%，模型会实际降低收入。情景名称描述预先定义的经济假设，不依据输出价格排序或重新命名。
- 悲观利润率直接在当前基准上减少 3 个百分点。合成基准第五年利润率为 −10% 时，Bear 为 −13%，不会通过 `max(0, …)` 把亏损改善成零。
- 每个响应返回 `story`、`scenario_version`、`changed_fields` 和完整输入。页面可展开查看 D&A、CapEx、营运资金、稳定期 ROIC 和精确差异字段。
- 无法通过模型校验的情景继续返回 `UNAVAILABLE` 与原因，不拖垮合法基准。
- 历史 run 缺少新增解释字段时，页面显示“旧版本未记录”，不崩溃，也不为历史结果补造当前故事。

回归证据：

- 新增 −5% 收入压力和亏损利润率回归；估值 golden + API：**84 passed**。
- TypeScript、ESLint 通过；使用系统 Chrome 执行全部 Playwright：**5 passed**。

## P05 证据与结论边界

- 风险结果新增实际 coverage：总检查数、成功数、是否完整及不可用模块。页面显示失败状态与原因；零风险时只说明已完成规则未超阈值，不把未检查模块当作安全。
- 风险严重度与证据置信度继续独立。`HIGH` 严重度不会自动变成 `HIGH` 置信度。
- 增长、利润率、现金流、资产负债表、估值和集中度的数字风险均引用可解析的 canonical fact 或 source document；原先不可解析的 `segment:*`、`valuation_model:*` 伪身份已移除。
- provenance API 新增 `market_observation` 节点，使行情数字可以追溯到 provider、观察时间、价格、币种、来源 URL 与抓取时间。
- 研究助手所有带数字的 claim 都有可解析证据。DCF 结论报告实际 `fcff_dcf.v2`，终值结论使用实际占比，不再无条件套用“>60% 敏感”模板。
- 未支持问题返回 `intent=unsupported`、支持主题和下一步，不附带当前公司总览数字。页面明确当前能力是规则检索，确定性只表示可复现，不承诺结论正确。
- 风险与研究页的证据可点击打开来源抽屉；切换 ticker 时父页面卸载旧状态并关闭旧来源抽屉。

回归证据：

- 研究 golden：**16 passed**，覆盖 AAPL/MSFT 数字风险和六类研究问题的证据解析。
- 风险/研究/API 聚焦：**12 passed**。
- TypeScript、ESLint 通过；新增 `research-boundaries.spec.ts`：**2 passed**。

## P04 新手阅读路径

- 新手估值页先展示公司经营基准、数据期间与假设不确定性，再依次进入参数调整、反推估值、安全边际和保存/复核。
- 收入增长同时显示历史 CAGR 参照、未来默认路径的独立理由与规则，明确历史增速不会被机械外推。
- 五项可编辑参数都说明调高或调低对估值的方向影响；WACC 明确为公司现金流折现率，不描述为投资者的承诺收益率。
- 高级敏感性矩阵和完整原始元数据默认折叠，初学者可按需展开；专业/初学者模式切换共用同一份已编辑草稿。
- 财务趋势标题与可见单位跟随当前指标切换：金额使用 `$B`，比率和增长率使用 `%`。
- 切换公司会关闭指标与来源抽屉，避免继续显示上一家公司的解释或证据。

复核补修：

- `OverviewSection` 的标题、可见单位和 ECharts 格式随收入、增长率、利润率及 FCF 指标变化。
- Overview API 为 KPI 返回完整指标身份；当前 TTM 使用共享 `current()` 契约，不会在最新窗口缺失时回退旧窗口。
- KPI 抽屉优先打开带值、公式、期间和完整输入的 `result_id`；来源抽屉明确显示“派生指标”。

聚焦回归证据：

- 新增 `beginner-valuation.spec.ts` 两条端到端验收：估值完整阅读路径；财务标题/单位及两类抽屉的公司隔离。
- 使用系统 Chrome 执行该文件：**2 passed**。
- 新增 `overview-provenance.spec.ts`：**1 passed**；对应 Overview API 聚焦回归：**1 passed**。TypeScript 与 ESLint 通过。

## 最终全量验证

- 后端 `.venv/bin/python -m pytest -q -p no:cacheprovider`：**220 passed**，1 条既有 Starlette/httpx 弃用警告。
- 前端 `pnpm exec tsc --noEmit --incremental false`：通过。
- 前端 `pnpm lint`：通过。
- 使用系统 Chrome 执行全部 Playwright：**9 passed**。
- README 已移除“全部标签页均为真实数据”的绝对表述，改为分别说明事实、计算、配置假设和证据缺口；同时更新 DCF v2、五项可编辑参数及测试命令说明。
