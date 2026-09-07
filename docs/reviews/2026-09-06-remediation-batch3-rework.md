# EquityLens 修复返工 Batch 3 证据记录

日期：2026-09-07。分支：`codex/remediation-rework`。执行计划：`docs/superpowers/plans/2026-09-06-remediation-batch3.md`。

## 当前状态

Batch 3 的 P02、P06、P08 已完成。

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

## P06 个人估值方案

- 创建普通参考价方案必须绑定同公司完整保存的 v2 run 与 `base|bear|bull` 情景；任意 `reference_value`/文字来源不再被信任。
- 服务端从已保存情景输出派生参考值与安全边际价格；非正结果保留研究原因，不生成普通买入参考价。
- 方案持久化 run ID、情景、输入指纹、财报/行情时间、注释、待验证条件、父版本、版本号与复核状态；关闭并重新打开 DuckDB 后字段保持。
- API 支持打开、复制与 2–5 个同公司方案比较；前端完成对应操作，并在未保存估值运行时禁用方案创建。

回归证据：

- API `plan_` 聚焦测试 4 passed，覆盖任意价格拒绝、服务端派生、非正结果、公司隔离、复制、比较与重启读取。
- TypeScript、ESLint、Playwright 收集通过。
- 通过 `PLAYWRIGHT_CHROME_PATH=/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` 使用系统 Chrome 实际执行 3 个浏览器用例，结果 **3 passed**。

## P08 四模块刷新与浏览器状态

- 刷新协调器分别执行 financials、segments、management、quotes；每个模块有独立事务、状态、变更标记与可重试错误。选择性重试只调用指定失败模块。
- 原始数据先写入私有暂存目录；模块成功后才发布不可变文件与 manifest。发布或数据库提交失败时恢复原 manifest，避免半完成快照成为最新版本。
- DuckDB 写入由全局锁与公司锁串行化；测试使用临时数据库对应的 raw 目录，不接触仓库现有快照。
- 财务 filing 或行情 observation 身份变化时，已保存方案只标记 `needs_review`，历史 run 与参考价保持不可变。
- 浏览器刷新后重新加载当前数据区，显示四模块结果，并为可重试失败提供单模块按钮。切换公司会关闭旧公司的指标/来源抽屉并清除刷新消息。
- 估值页保留用户草稿；影响估值输入的刷新会禁用保存并要求按当前草稿重算。每个估值请求绑定启动时的刷新代次，刷新前发出的晚到响应不能错误解除过期状态。
- 通用 `Card` 组件现会透传标准 DOM 属性，使现有 `data-testid` 可被真实浏览器测试定位。

回归证据：

- 刷新 API 聚焦测试 4 passed，覆盖部分失败、选择性重试、模块事务回滚和方案复核状态。
- 全量后端：**205 passed**，另有 1 条既有 Starlette/httpx 弃用警告。
- 前端 TypeScript `--noEmit` 与 ESLint 通过。
- 使用系统 Chrome 执行全部 Playwright：**5 passed**。其中新增 2 个刷新用例覆盖活动模块重载、失败模块单独重试、估值草稿保留、保存禁用和显式重算恢复。
- 全量回归首次发现 session 级 golden fixture 中测试行情泄漏；测试现用 `finally` 清理插入行情，随后全量 205 项通过。
