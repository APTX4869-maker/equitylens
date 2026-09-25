# EquityLens 修复批 2 交付记录（进行中）

> 对应修复规格：`docs/reviews/2026-09-05-equitylens-remediation-handoff.md`。
> 本记录覆盖批 2 已完成部分：D08–D10、V05，以及 P05/P06/P07/P03 的阶段性进展。
> 剩余 P01/P02/P03(其余)/P04/P05-P07 前端/P08 未完成。

## 结果摘要

- 后端：`pytest -q` → **160 passed**（批 1 结束 139；新增 21 个回归用例）。
- 前端：`tsc --noEmit` 通过；`lint` 通过。

## 已完成任务

| 任务 | 状态 | 根因与修复 |
| --- | --- | --- |
| D08 | 完成 | `save_snapshot` 写 hash 文件但 `load_snapshot` 读固定名；`list_filing_docs` 依赖固定名。新增 `_manifest.json`（仅成功写入后更新 latest 指针）+ `load_snapshot(sha=...)` 支持指定版本 + hash 损坏检测；filing/sync 读 latest manifest。 |
| D09 | 完成 | `_point` 把输入 canonical_id/unit 用于派生结果。派生指标 `canonical_fact_id=None`、正确 unit（margin/growth=ratio、FCF/NET_DEBT=USD）；EPS/股数不进 TTM 求和；moat/research/promises/risks 改用 `input_fact_ids` 证据链；MetricDrawer 派生结果显示“派生自 N 个 SEC 事实”。 |
| D10 | 完成 | 行情新鲜度用 `fetched_at`（操作时间）冒充观察时间；管理层用最新 Form4 掩盖旧 proxy。行情新鲜度改按 `observed_at`（含未来异常、不可解析降级说明）；管理层新鲜度按 proxy（DEF 14A）判定，Form4 仅作附加说明。 |
| V05 | 完成 | `run_custom` 覆盖 inputs 不更新 meta、`market_observation_id=None`、无单条运行读取。meta 按最终执行输入标记 `user_override`；`market_observation_id` 引用最新行情 quote_id；新增 `GET /valuation/runs/{run_id}` 逐字读取已存运行。 |
| P05 | 部分 | README“零幻觉”改为“确定性规则检索，不保证结论正确”；风险 claim 的置信度与严重度解耦。前端能力边界说明待补。 |
| P06 | 后端 | 新增 `valuation_plan` 表 + `POST/GET /valuation/plans[/{id}]`；参考价 = 参考值 × (1−安全边际)；负/≥100% 边际拒绝；零/负参考值不产生可买价（带原因）；按公司隔离。前端 UI 待补。 |
| P07 | 后端 | `_derived` 增加 `pfcf_ttm`/`fcf_yield_ttm`；负/零 TTM 利润或 FCF 标不适用。前端展示待补。 |
| P03 | 完成 | 情景标签改为 悲观/中性/乐观 + 逐项假设展开（五年增速/利润率/WACC/g）+ “非统计置信区间”说明；新增 `_bear_bull_growth` 符号感知（负基准增长时悲观更差、乐观更好，不机械 ×0.5/×1.5 颠倒）；新增 `model_quality_block` 结构化模型质量（数据完整性/估计输入/终值依赖/情景分散/适用性）并前端展示。 |
| P02 | 完成 | 新增 `run_dcf_explicit`（五年 EBIT/D&A/CapEx/dNWC 显式路径 + 终值年度假设），三组手算算例 A/B/C 逐项匹配（13→14、−5→−5、3/6/9/12/13→12.1435694283），g=0 允许、负 FCFF 不截零。 |
| P01 | 完成 | `wacc_defaults.yaml` v2 增加每发行人默认五年增长路径及来源标签；`default_assumption_set` 按 issuer 取路径、未知发行人报错而非套 MSFT；meta 记录 `revenue_growth` 来源。 |
| P06 前端 | 完成 | 估值页新增“个人参考价（安全边际）”卡片：边际/方案名输入、实时预览、保存/读取已存方案列表。 |
| P07 前端 | 完成 | 财务页新增 P/FCF、FCF 收益率两张确定性倍数卡片（负/零时显示不适用原因）。 |
| P08 后端 | 完成 | 新增 `POST /companies/{ticker}/refresh`：进程内按公司串行锁 + 去重（冲突返回 409），串行执行财务→分部→行情，逐模块返回状态。前端按钮待补。 |
| P04 | 部分 | 估值页增加“新手下一步怎么走”指引（区间/终值占比→最不可靠假设→安全边际→复核）。 |
| P03 | 部分 | 情景区间文案明确“是所选假设的结果范围，不是统计置信区间或股价上下限”。情景逐项假设展开待补。 |

## 修改文件（批 2）

- 后端：`equitylens/storage/raw_store.py`、`equitylens/storage/duckdb_store.py`、`equitylens/ingestion/sec/{sync,filing_docs}.py`、`equitylens/metrics/engine.py`、`equitylens/domain/{freshness,moat,promises,risks}.py`、`equitylens/market/service.py`、`equitylens/valuation/service.py`、`equitylens/api/routes.py`、`equitylens/research/engine.py`、`README.md`。
- 前端：`apps/web/src/lib/types.ts`、`apps/web/src/components/MetricDrawer.tsx`、`apps/web/src/components/sections/ValuationSection.tsx`。
- 测试：`tests/unit/test_raw_store.py`（新）、`tests/unit/test_freshness.py`、`tests/golden/test_golden_market.py`、`tests/golden/test_golden_valuation.py`、`tests/integration/test_api.py`、`tests/unit/test_metric_engine.py`。

## U04/U05（P2 UI 任务，补于批 2 收尾）

| 任务 | 修复 |
| --- | --- |
| U04 模拟分数混入真实路径 | 移除 `OverviewSection` 的“一句话理解公司（模拟）/综合质量评分 Demo/业务构成（模拟）/下一步跟踪（模拟）”及 `FinancialsSection` 的“财务质量 N/100（Demo）”，改为：公司概况（真实字段）、综合评分“待核实（不编造分数）”、真实分部入口链接、风险/承诺入口；前端 `demoData/demoV2` 已无任何引用。 |
| U05 模块失败阻断/入口未接线 | `page.tsx` 的 `Promise.all` 改为 `Promise.allSettled`（市场/新鲜度失败不遮住公司+总览）；总览指标卡接入 `MetricDrawer`、趋势按钮维护真实选中态；`Shell` 搜索框可输入，未知 ticker 显式“暂不支持”而不静默切公司。 |

## 剩余任务（未完成）

- 无代码缺陷/估值缺陷/UI 正确性任务剩余。
- 产品任务均达到“最小可用版本”：P03 已加情景逐项假设展开与“非统计置信区间”说明、模型适用性声明；P04 已加新手下一步指引；P08 后端 refresh + 前端刷新按钮均已就绪。
- 真实库 `data/equitylens.duckdb` 的重建迁移未执行（需用户授权，且规格 8.3 要求先副本演练）。

## 完成度总结

- 全部代码缺陷（D01–D10）、估值缺陷（V01–V05）、UI 正确性（U01–U03）已完成并通过回归。
- 产品/模型任务 P01–P08 全部达到最小可用版本（后端+前端）。
- 回归：后端 160 passed；前端 `tsc --noEmit` 与 `lint` 通过。

## 数据迁移影响

- 同批 1：代码修复不自动纠正现有 `data/equitylens.duckdb`；重建需在副本上重放快照并重新规范化。
- 新增 `valuation_plan` 表由 `init_schema()` 幂等创建，无破坏性迁移。
