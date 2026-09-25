# EquityLens 修复返工 Batch 1 证据记录

日期：2026-09-06。分支：`codex/remediation-rework`。依据 `docs/superpowers/specs/2026-09-06-remediation-rework-design.md` 与 `docs/superpowers/plans/2026-09-06-remediation-batch1.md`，对照 `docs/reviews/2026-09-06-remediation-quality-review.md` 的 28 项审查结论逐项回填。

结论：Batch 1 设计中的四类“会算出错误数字 / 把结果关联到错误输入”路径已全部修复并有回归测试。后端 180 项通过；前端 TypeScript 与 ESLint 通过。Playwright 受控乱序测试已编写并通过收集/类型检查，但本环境无法下载 Chromium 浏览器二进制，故未实际执行（见文末“未闭环”）。

## 逐项状态

| ID | 本轮实现 | 回归测试 | 版本/持久化影响 | 剩余限制 |
| --- | --- | --- | --- | --- |
| D04 季度日期输入 | 财年期间匹配统一处理 `date`/`datetime`/ISO 字符串 | `test_q4_derivation_accepts_date_and_iso_periods`（tests/unit/test_fiscal_periods.py） | 无 | 52/53 周、财年变更的规定用例属后续核对 |
| D02 折旧基期 | `estimate_depreciation` 限定目标财年与单位；同财年分项相加；旧合并值不覆盖当前分项 | `test_depreciation_uses_requested_valuation_fiscal_year` 等（tests/golden/test_golden_valuation.py） | 无 | 租赁摊销是否属于最终公司口径仍属披露定义核对 |
| D06/D07 连续 TTM 契约 | `MetricEngine.current(metric, cid, "ttm")` 只返回最新预期季度末窗口，缺失即 `INCOMPLETE_PERIOD` 并带缺口原因 | `test_current_ttm_preserves_zero_in_latest_window`、`test_current_ttm_reports_latest_gap_instead_of_older_window`（tests/unit/test_metric_engine.py） | 历史序列接口不变 | 单位/期间校验已含，但风险与研究消费已改为复用该契约 |
| P07 市场倍数 | `market/service.py:_derived` 改用 `engine.current`，零/负返回 `UNSUPPORTED`，缺季返回 `INCOMPLETE_PERIOD`，不再 `if p.value` 回退旧窗口 | `test_market_multiples_do_not_fall_back_when_current_ttm_is_zero`、`...do_not_use_old_window_when_latest_is_incomplete`（tests/golden/test_golden_market.py） | 无 | 过期行情降级属 Batch 2 D10 |
| D06/U03/P05 风险与研究覆盖 | `risk_signals` 每个模块经 `record_check` 返回 OK/INCOMPLETE_PERIOD/ERROR + reason；现金流与净债务改用 `engine.current`，不再手算后四行；研究风险回答从 `checks` 生成覆盖文本 | `test_risks_report_incomplete_ttm_and_module_failure`（tests/golden/test_golden_research.py） | 风险响应新增 `checks` 数组（additive） | 结论模板的逐项证据 ID 全覆盖属 Batch 4 |
| V01 DCF 边界 | `ValuationError` 带 `code/field`；拒绝负 CapEx/D&A、WACC≤−1、非有限显式终值；−100% 增长释放营运资金（用前一年收入基期） | `test_minus_100_percent_growth_releases_working_capital`、`test_dcf_rejects_model_incompatible_inputs`、`test_explicit_terminal_values_must_be_finite`（tests/golden/test_golden_valuation.py） | 无（错误不再写库） | `fcff_dcf.v2` 显式终值算法属 Batch 3 |
| V03/V05 估值输入身份 | `valuation_input_fingerprint`（SHA-256 规范化输入）+ 响应带 `ticker`/`input_fingerprint`/完整 `assumptions.inputs`；`ValuationError` 在 API 边界返回 `{"error":{code,field,message}}` | `test_valuation_response_fingerprints_complete_executed_inputs`、`test_valuation_run_structured_error_body`（tests/integration/test_api.py） | `run_custom` 支持 `persist=False` 预览不落库；保存仍记录完整快照 | 保存 run 尚未写入情景/敏感性/完整事实 ID（V05 属 Batch 2） |
| U02/V03 前端草稿身份 | 单一完整 `ValuationDraft`，编辑同步更新草稿并每次请求发完整输入；响应仅当 ticker+序号匹配时应用；仅当 applied 输入等于当前草稿且无错误时允许保存；反推在假设/价格变更后标过期、ticker 变更清除；行情小数保留 | `apps/web/e2e/valuation-state.spec.ts`（收集/类型通过，未执行）+ `draftFingerprint`/`updateDraft` 纯函数 | 无 | 浏览器端受控乱序执行需 Chromium 二进制 |

## 关键提交

- `d645d13` fix: normalize fiscal period date inputs
- `0a68ffa` fix: align depreciation with valuation base period
- `bffbed5` fix: expose current TTM completeness
- `c3fea68` fix: prevent stale TTM multiple fallback (P07/D06)
- `ee85f76` fix: harden DCF input boundaries (V01)
- `3bb0c45` feat(valuation): complete service identity, plan persistence, and API errors
- `fbefbe4` fix: share TTM contract and failure coverage with risks/research
- `759132c` fix: bind valuation previews to one complete draft (V03/U02)

## 验证

- 后端：`.venv/bin/python -m pytest -q -p no:cacheprovider` → **180 passed**，1 条 Starlette/httpx 弃用警告。
- 前端：`pnpm exec tsc --noEmit --incremental false` 与 `pnpm lint` 均通过。
- Playwright：`pnpm exec playwright test --list` 收集 2 个用例成功；`pnpm exec playwright install chromium` 因网络受限超时，未执行浏览器测试。
- 所有新增测试使用临时数据库/夹具，未写入真实 `data/equitylens.duckdb`。

## 未闭环（后续批次）

1. **D08 快照 SHA 严格匹配**（Batch 2）：`raw_store.load_snapshot(sha=...)` 对未知/不匹配 SHA 仍回退固定文件名且不校验实际字节，审查第 6 条的严格匹配未完成。默认加载的 manifest/损坏检测已随本轮提交，但指定 SHA 的严格匹配仍待 Batch 2 补齐。
2. **D10 新鲜度**（Batch 2）：`freshness.py` 的行情观察时间/治理 proxy 改动已实现但尚未提交，quote 状态仍一律 OK 的降级未完成。
3. **V05 完整估值 run 持久化**（Batch 2）：保存 run 仍未写入情景/敏感性/完整事实 ID。
4. **P02/P03/P04/P06/P08**（Batch 3/4）：`fcff_dcf.v2`、个人方案闭环、新手引导、一键更新等未在本批处理。
5. 前端 U01/U03/U05 的其余 UI 改动（总览比例图单位、全局抽屉随公司重置、可选模块独立错误等）随本轮一并提交，属 Batch 1 之外的 UI 收敛，其完整验收留待后续批次。

## 后续闭环（2026-09-07）

以上后续批次依赖均已处理。原交接 §8.2 的 52/53 周、财年变更、同日多概念/重复期间、双快照端到端和失败恢复边界已补测，详见 `docs/reviews/2026-09-07-remediation-acceptance-matrix.md`。真实数据库迁移仍按单独的只读盘点与副本演练流程执行。
