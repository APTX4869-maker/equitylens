# EquityLens 修复批 1 交付记录

> 对应修复规格：`docs/reviews/2026-09-05-equitylens-remediation-handoff.md`。
> 批 1 范围：D01–D07 + V01–V04 + U01–U03（P1 财务/估值/交互正确性）。
> 基线提交：`418a8c6`。本记录为代码修复后的实际结果，不代表批 2（V05、D08–D10、P01–P08）已完成。

## 结果摘要

- 后端：`.venv/bin/python -m pytest -q -p no:cacheprovider` → **139 passed**（基线 111 passed，新增 28 个回归用例）。
- 前端：`pnpm exec tsc --noEmit --incremental false` 通过；`pnpm lint` 通过。
- 实库数字已只读核对，全部与规格一致（D01 40.294/31.067/9.227B、D02 34.3B+4.7B/3%→9.95517B、D03 AAPL 2015/MSFT 2020、D06 8.44、D07 98.767B/0.46905）。

## 各任务状态与根因

| 任务 | 状态 | 根因与修复 |
| --- | --- | --- |
| D01 | 完成 | `LONG_TERM_DEBT` 混入 `LongTermDebt`(含流动) 与 `LongTermDebtNoncurrent`，`SHORT_TERM_DEBT` 又含 `LongTermDebtCurrent`，同日并列被 `_latest_instant` 取单值。拆分为 `LONG_TERM_DEBT`(非流动)/`LONG_TERM_DEBT_CURRENT`/`SHORT_TERM_BORROWINGS`/`COMMERCIAL_PAPER`，净债务桥接按单一资产负债表日求和，核心四组件缺失/日期不一致报缺口。 |
| D02 | 完成 | 映射缺 `Depreciation`/`AmortizationOfIntangibleAssets`，`estimate_depreciation` 的 fallback 死代码查询同一指标。补映射 + 同财年分项求和 + MSFT fixture 补概念。 |
| D03 | 完成 | `fiscal_year_of` 对最早已知年末之前的日期无下界判断。显式判断已知区间外，走 fallback 规则或标未解析。 |
| D04 | 完成 | `pick` 找不到 YTD 桶时退回同日 Q_STANDALONE。移除该退回（Q1 的显式等价保留）。 |
| D05 | 完成 | 年度输入取首条、派生值 `as_known_at` 写空。FY 取最新重述、派生值传播 `as_known_at`。 |
| D06 | 完成 | `ttm`/passthrough 只取最近四条，缺连续性检查。新增 `_trailing_window`/`_ttm_window` 连续四季度校验。 |
| D07 | 完成 | FCF/利润率/YOY 的 `freq=="ttm"` 落入 FY 分支。按频率显式分支：TTM 利润率=四季度分子合计/分母合计，TTM FCF=四季 OCF 合计−四季 CapEx 合计。 |
| V01 | 完成 | `shares or 1`/`net cash 缺=0`/`op_margin or .25`/零税额与 CapEx 被回退；`validate` 只查少数条件。显式 None 判断、缺股数/净现金桥接报错、`validate` 加有限性与边界校验。 |
| V02 | 完成 | `runReverse` 只传 target_price，后端重读默认。前端发送当前确认输入快照，后端固定其余变量只解恒定增速；`run_custom`/`reverse_dcf` 统一 `risk_free_rate()`。 |
| V03 | 完成 | `recompute` 每次从首年重建增长路径。新增 `growthPath` 状态，仅显式编辑增长时重建路径。 |
| V04 | 完成 | `scenario_valuation` 自动偏移触发护栏使整请求失败；`run_custom` 在情景计算前已持久化。逐情景独立校验（UNAVAILABLE+原因）、先算全量再原子持久化、护栏文案与比较符号统一。 |
| U01 | 完成 | 页面组件无公司 key，`ValuationSection` 不随 ticker 重置。`page.tsx` 为所有 ticker 相关 section 加 `key={company}` 强制重挂载。 |
| U02 | 完成 | `recompute` 每次 change POST 并持久化、无序号/取消、finally 提前关 loading。加单调请求序号 + 预览(persist=false)/显式保存(persist=true)分离。 |
| U03 | 完成 | `FinancialsSection` FCF/TTM 卡取单季、前端把 null 当 0；`_answer_compare`/`_answer_cash` 把季度称 TTM；总览手动求和。统一走后端 `frequency="ttm"` 口径。 |

## 修改文件

- 后端：`config/mappings/canonical_mappings.yaml`、`equitylens/config.py`、`equitylens/normalization/fiscal_periods.py`、`equitylens/normalization/normalize.py`、`equitylens/normalization/taxonomy/mappings.py`、`equitylens/metrics/engine.py`、`equitylens/valuation/dcf.py`、`equitylens/valuation/defaults.py`、`equitylens/valuation/service.py`、`equitylens/api/routes.py`、`equitylens/research/engine.py`。
- 前端：`apps/web/src/app/page.tsx`、`apps/web/src/components/sections/ValuationSection.tsx`、`apps/web/src/components/sections/FinancialsSection.tsx`、`apps/web/src/components/sections/OverviewSection.tsx`。
- 测试/fixture：`tests/unit/test_metric_engine.py`、`tests/unit/test_fiscal_periods.py`、`tests/golden/test_golden_facts.py`、`tests/golden/test_golden_valuation.py`、`tests/golden/test_golden_research.py`、`tests/integration/test_api.py`、`tests/fixtures/sec/0000789019/companyfacts.json`。

## 版本升级

- `MAPPING_VERSION` → `canonical-mappings.v2`（mapping 变更）。
- `METRIC_ENGINE_VERSION` → `metric-engine.v2`（引擎变更）。
- 公式版本：`net_debt.v2`、`ttm.v2`、`{margin}.ttm.v1`、`fcf.ttm.v1`、`fcf_margin.ttm.v1`、`revenue_growth_yoy.ttm.v1`。

## 数据迁移影响

- 代码修复不会自动纠正现有 `data/equitylens.duckdb` 中已规范化的错误财年、错误债务指标、旧派生季度或旧估值运行（符合规格 8.3）。
- 债务指标拆分、折旧分项映射、财年下界修复需在副本上重放原始快照并重新规范化后才会反映到真实库。
- 本次未执行真实库重建/迁移（规格 8.3 要求先做只读盘点并在副本上演练，且需用户授权）。

## 剩余限制

- `tests/e2e/smoke.py`（Playwright，会写库）未运行；按规格 8.1 需在指向临时测试库的后端上验证滑杆/保存/反推流程。
- V05（估值元信息/保存声明/历史复查）、D08–D10、P01–P08 属于批 2，未开始。
- 前端 `FinancialsSection` 的“财务质量 85/90 分（Demo）”属于 U04（批 2），本批未移除。
