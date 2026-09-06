# EquityLens 修复返工 Batch 3 证据记录

日期：2026-09-06。分支：`codex/remediation-rework`。执行计划：`docs/superpowers/plans/2026-09-06-remediation-batch3.md`。

## 当前状态

Batch 3 的 P02 已完成；P06、P08 按顺序执行中。

## P02 `fcff_dcf.v2`

- 新计算默认版本为 `fcff_dcf.v2`，历史 v1 只允许显式调度，已保存 v1 继续原样读取。
- 五年显式经营预测之后单独构造 year 6：收入按稳定增长推进一次，EBIT 使用稳定利润率，终值年度 FCFF 为 `NOPAT × (1 − terminal_growth / terminal_roic)`。
- 显式终值入口把提供的 terminal 输入定义为 year-6 金额，终值直接使用 `terminal_fcff / (WACC − g)`，不会再乘一次 `(1+g)`。
- `terminal_roic` 已进入配置、默认元数据、完整输入、指纹、覆盖输入、情景、敏感性、反推、保存快照、前端草稿与编辑控件。
- API 返回 `terminal_forecast`，含 year-6 收入、利润率、EBIT、NOPAT、ROIC、再投资率、再投资额、FCFF 与定义。

回归证据：

- `test_explicit_terminal_year_cash_flow_is_not_grown_twice`：terminal FCFF 100、WACC 10%、g 2% 时终值严格为 1250；旧实现返回 1275。
- `test_production_v2_terminal_uses_stable_roic_reinvestment`：收入 100、稳定增长 2%、利润率 25%、税率 20%、ROIC 20% 时，year-6 NOPAT 20.4、再投资 2.04、FCFF 18.36。
- `test_all_new_valuation_paths_report_v2_terminal_contract`：默认、预览、情景和反推统一报告 v2；保存读取保留相同终值块。
- 估值 golden + API：74 passed；前端 TypeScript、ESLint 与 2 个 Playwright 用例收集通过。

浏览器执行限制：本机缺少 Playwright Chromium；再次下载 182.1 MiB 运行时后仍停在 0%，因此实际浏览器执行尚无通过证据。
