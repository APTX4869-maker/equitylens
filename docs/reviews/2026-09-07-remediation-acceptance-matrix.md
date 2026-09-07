# EquityLens 原交接验收矩阵补测记录

日期：2026-09-07。分支：`codex/remediation-rework`。

## 结果

原交接文档 §8.2 的八组反例均已有明确自动化证据。本轮补测发现并修复四个此前没有被现有全量测试发现的根因：同日事实选择受插入顺序影响、离线重放读取最新字节却规范化旧固定文件、双文档抓取失败发布半套快照、零分母比率没有显式不可用结果。

## 新增边界证据

- 52/53 周与财年结束日变更：`test_52_and_53_week_fiscal_years_are_full_years`、`test_fiscal_year_end_change_uses_reported_calendar_boundaries`。
- 同日多概念与重复期间：`test_same_day_overlapping_revenue_concepts_are_order_independent`、`test_same_day_restatement_tie_is_insertion_order_independent`、`test_duplicate_quarter_is_selected_once_in_ttm`。
- 双快照、旧快照离线重放、幂等与中途失败：`test_two_snapshot_restatement_replays_latest_into_fresh_database`、`test_failed_multi_document_fetch_keeps_previous_latest_set`；原有 SHA 指定回放和损坏检测继续覆盖旧版本与内容完整性。
- 零分母：`test_ratio_zero_denominator_is_explicitly_unavailable` 要求保留输入身份并返回 `UNAVAILABLE`，不省略结果或伪装成零。

## 既有证据映射

- 零值、缺值、缺季度、单位冲突、FY/TTM 差异：`test_current_ttm_preserves_zero_in_latest_window`、`test_current_ttm_reports_latest_gap_instead_of_older_window`、`test_current_ttm_rejects_unit_mismatch`、`test_annual_and_ttm_fcf_differ`。
- 非法估值输入、合法基准但非法子情景、统一输入快照：估值 golden/API 的输入校验、完整指纹、情景独立状态、敏感性和反推回归。
- 公司切换、旧请求晚到、请求失败和局部模块失败：`valuation-state.spec.ts`、`refresh-state.spec.ts`。
- 更新后旧方案共存：`test_refresh_marks_existing_plan_for_review_without_recalculation` 与刷新浏览器回归。

## 验证

- 后端全量：**230 passed**，1 条既有 Starlette/httpx 弃用警告。
- TypeScript 与 ESLint：通过。
- 使用系统 Chrome 的 Playwright：**10 passed**。

所有新增写入型测试均使用临时 DuckDB 和临时 raw 目录，没有修改 `data/equitylens.duckdb` 或仓库真实快照。
