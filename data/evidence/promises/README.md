# Promise Tracker 证据卡

每条"承诺"必须有一张证据卡（`data/evidence/promises/{TICKER}/*.json`，`_` 开头的文件会被忽略），
包含**原话引用 + 发言人 + 日期 + 来源 URL** 与一个**可机器核对的声明**（metric/fiscal_year/operator/target）。
状态由系统在读取时用确定性规则 `promise_verify.v1` 对照 SEC 财报事实自动判定，绝不手填。

```json
{
  "promise_id": "aapl-fy2026-buyback",
  "speaker": "Tim Cook",
  "statement_date": "2025-11-02",
  "source_url": "https://www.sec.gov/Archives/edgar/data/0000320193/...",
  "source_label": "Apple Q4 FY2025 财报电话会（示例：请替换为真实转写来源）",
  "promise_text": "本财年我们将回购约 900 亿美元股票。",
  "normalized_claim": "FY2026 股票回购 ≥ $90B",
  "verification": {
    "metric": "SHARE_REPURCHASES",
    "frequency": "annual",
    "fiscal_year": 2026,
    "operator": "gte",
    "target": 90000000000
  },
  "verification_deadline": "2026-11-30"
}
```

- `metric`：指标引擎可算的 canonical metric（annual FY 口径，如 SHARE_REPURCHASES / CAPITAL_EXPENDITURES / REVENUE）。
- `operator`：`gte`（≥）/ `lte`（≤）/ `approx`（±5%）。
- 导入：`uv run equitylens ingest-promises AAPL`
- 读取：`GET /api/v1/companies/AAPL/promises` —— items 带 `computed_status`（VERIFIED/BROKEN/OPEN/UNVERIFIED）
  与 `status_note`（含披露值与承诺值对比）与 `evidence_ids`（指向 SEC 事实）。
- 承诺兑现率：在样本具备意义前不计算（Phase 7 纪律）。

> 反幻觉红线：证据卡里的 `promise_text` 必须可溯源到真实来源；不得编造未说过的承诺。
> Earnings-call/prepared-remarks 自动解析（Phase 7）未来会**生成**这些卡，而不是绕过它们。
