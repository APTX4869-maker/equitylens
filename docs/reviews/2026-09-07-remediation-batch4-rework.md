# EquityLens 修复返工 Batch 4 证据记录

日期：2026-09-07。分支：`codex/remediation-rework`。执行计划：`docs/superpowers/plans/2026-09-07-remediation-batch4.md`。

## 当前状态

P01、P03 已完成；P05、P04 待按顺序执行。

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
