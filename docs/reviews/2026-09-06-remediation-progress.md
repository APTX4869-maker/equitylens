# EquityLens 修复返工进度

日期：2026-09-06

执行分支：`codex/remediation-rework`

依据：

- `docs/reviews/2026-09-05-equitylens-remediation-handoff.md`
- `docs/reviews/2026-09-06-remediation-quality-review.md`
- `docs/superpowers/specs/2026-09-06-remediation-rework-design.md`
- `docs/superpowers/plans/2026-09-06-remediation-batch1.md`

## 当前状态

Batch 1 已完成 2/9 个任务。当前完成的是季度日期输入和估值 D&A 基期选择。TTM、市场倍数、风险覆盖、DCF 边界、API 输入身份和前端乱序仍在本批后续任务中。

## 已完成

### Task 1 / D04：季度日期输入统一

- 在财务期间边界统一处理 `datetime`、`date` 和 ISO 日期字符串。
- 季度桶匹配与派生结果输出均使用规范化 ISO 日期。
- 新回归先复现：字符串用例通过、DuckDB 风格 `date` 对象无法得到 Q4。
- 修复后：`tests/unit/test_fiscal_periods.py` 共 12 项通过。
- 提交：`d645d13 fix: normalize fiscal period date inputs`。

结论：审查记录中的 D04 `date` 对象缺陷已修复。D04 的跨快照/期间边界完整验收仍随 D05 和后续批次继续核对，因此暂不把整项标为完全闭环。

### Task 2 / D02：D&A 与估值收入基期对齐

- `estimate_depreciation` 现在要求明确目标财年，并只在该财年选择合并值或相加分项。
- 合并值只在目标财年和目标单位一致时优先。
- 分项必须同财年、同单位且两项齐全；否则返回缺失，由默认假设路径显式降级。
- 默认估值使用收入基准的财年选择 D&A，并记录 `combined`、`split` 或 `assumption` 来源类型。
- 新回归先复现：FY2020 合并值错误覆盖 FY2026 分项；函数也无法接收目标财年。
- 修复后：`tests/golden/test_golden_valuation.py` 共 30 项通过，包括 MSFT FY2026 34.3B + 4.7B。
- 提交：`0a68ffa fix: align depreciation with valuation base period`。

结论：审查记录中的“历史 combined 覆盖当前 split”已修复；租赁摊销是否属于最终公司口径仍属于原 D02 的披露定义核对，不用代码猜测，因此整项仍保留“部分完成”直至来源核验闭环。

## 基线验证

- 后端全量：163 passed，1 条 Starlette/httpx 弃用警告，49.46 秒。
- 前端：TypeScript `--noEmit --incremental false` 通过；ESLint 通过。
- 所有新增测试使用临时测试数据库，没有写入真实 `data/equitylens.duckdb`。

## 下一步

执行 Task 3–5：建立当前 TTM 完整性契约，让市场倍数、风险和研究统一消费该契约，消除最新值为零或缺季时回退旧窗口的问题，并将失败覆盖状态返回给页面。
