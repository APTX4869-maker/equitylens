# EquityLens 真实库只读盘点报告

> **后续状态（2026-09-07）：** 本文记录的是迁移前历史盘点。真实库后来已包含 v2 规范化结果；副本重放、幂等验证和原子切换已完成，最终证据见 `docs/reviews/2026-09-07-real-db-migration-rehearsal.md`。

> 生成于代码修复完成后（基线 `418a8c6` → 修复后工作树）。本文只读检查 `data/equitylens.duckdb`，**未做任何写入**。
> 依据：修复规格 `docs/reviews/2026-09-05-equitylens-remediation-handoff.md` §8.3 第 1 步。

## 1. 数据路径与文件

| 项 | 值 |
| --- | --- |
| DB 路径 | `data/equitylens.duckdb` |
| 大小 | 54,276,096 bytes（约 51.8 MB） |
| mtime | 2026-09-03 22:30:23（修复前最后一次写入） |
| 原始快照目录 | `data/raw/sec/{0000320193,0000789019}/`（含 `companyfacts.json`、`submissions.json`、`filing_docs/`） |
| 行情快照目录 | `data/raw/market/` |
| 注册表 | `data/raw/sec/_registry/company_tickers.json` |

## 2. 表行数总览

| 表 | 行数 | 备注 |
| --- | --- | --- |
| `canonical_fact` | 11,165 | AAPL 5,567 / MSFT 5,598 |
| `raw_fact` | 57,806 | AAPL 25,135 / MSFT 32,671 |
| `source_document` | 42 | 快照 4 + 10-K 10 + 10-Q 10 + Form4 16 + DEF14A 2 |
| `segment_fact` | 528 | |
| `valuation_run` | 11 | 全部 `fcff_dcf.v1`（2026-09-02 ~ 09-03） |
| `market_quote` | 2 | 两家各 1 条（provider=nasdaq） |
| `ingestion_run` | 18 | 含 4 条 ERROR（早期 sync） |
| `company` | **0** | 公司身份未入库，ticker→CIK 映射在 `domain/companies.py`（设计如此，非缺陷） |
| `valuation_plan` | **不存在** | P06 新表，下次 `init_schema()` 幂等创建 |
| `executive` / `executive_compensation` / `board_member` / `insider_transaction` | 11 / 27 / 21 / 20 | 管理层数据 |
| `valuation_assumption_set` / `metric_value` / `market_observation` / `management_promise` / `evidence_span` | 0 | 未使用 |

## 3. 受各缺陷影响的数据（需重建的部分）

### D01 · 债务口径（需重规范化）
- 现状：`SHORT_TERM_DEBT` 425 条（AAPL 186 / MSFT 239）为旧“混装”口径；`LONG_TERM_DEBT` 416 条（AAPL 144 / MSFT 272）把 `LongTermDebt`(含流动) 与 `LongTermDebtNoncurrent` 当替代值。
- 新指标 `LONG_TERM_DEBT_CURRENT` / `SHORT_TERM_BORROWINGS` / `COMMERCIAL_PAPER`：**当前为 0（未规范化）**。
- 预期变化：重规范化后拆分为互不重叠组件，NET_DEBT 不再重复计入流动部分（MSFT 长期债 40.294B 不会再加 9.227B）。

### D02 · 折旧摊销（需重规范化）
- 现状：`DEPRECIATION_AMORTIZATION` 仅 AAPL 199 条；MSFT 为 **0**。
- `raw_fact` 中 MSFT 已有 `Depreciation`(91) 与 `AmortizationOfIntangibleAssets`(229)，但未映射。
- 预期变化：重规范化后生成 `DEPRECIATION` + `AMORTIZATION_OF_INTANGIBLE_ASSETS`，`estimate_depreciation` 由“收入×3%”回退改为 34.3B+4.7B=39B。

### D03 · 早期财年错归（需重规范化）
- 现状：AAPL 253 条 pre-2010 事实被压入 FY2015；MSFT 255 条压入 FY2020。
- 预期变化：下界修复后按 fallback 规则归入正确财年（如 2007→FY2007/2008），不再污染最早已知财年。

### D04/D05 · 派生季度（需重规范化）
- 现状：`status='CALCULATED'` 共 312 条（`standalone_quarter.ytd_diff.v1`），**其中 312/312 的 `as_known_at` 为 NULL**。
- 预期变化：重规范化后 Q4 派生不再误用单季当累计，且 `as_known_at` 传播为输入最晚披露时间（重述可区分）。

### D06/D07 · TTM（**无需重建**）
- TTM/频率分支在指标引擎内**即时计算**，不落库；新引擎代码已修复。旧数据无需迁移，读取时自动用新口径。

## 4. 版本指纹（重建后的版本跃迁）

- 现状全部为 `mapping_version='canonical-mappings.v1'`、`mapping_rule_id='*.usgaap.v1'`、`standalone_quarter.ytd_diff.v1`。
- 修复后代码使用 `canonical-mappings.v2`、`*.usgaap.v2`、`metric-engine.v2`。重规范化会把 `canonical_fact.mapping_rule_id/mapping_version` 更新到 v2，实现“旧版本名不代新逻辑”。

## 5. 既有个人记录（重建时需保留）

- `valuation_run`：11 条 `fcff_dcf.v1`（2026-09-02 ~ 09-03），均基于已知有误数据。按 §8.3.5 应标记“旧方法/受已知数据问题影响，需复核”，不原位改写。
- `valuation_plan`：当前 0 条（表尚不存在），无既有方案需迁移。
- `market_quote`：2 条，需保留（不可变快照语义）。

## 6. 原始快照可用性（可回放）

两家公司 `companyfacts.json` / `submissions.json` 均在盘且 `source_document.content_sha256` 已记录（AAPL `73a86c6a…`、`2503475b…`；MSFT `f8aae296…`、`ef3d1eed…`）。`filing_docs/` 下 10-K/10-Q/DEF14A/Form4 文档齐全。因此可在副本上做 hash 校验回放，无需重新联网抓取。

## 7. 当时建议的下一步（现已执行）

1. **备份**：复制 `data/equitylens.duckdb` 与 `data/raw/` 到带日期的副本路径。
2. **副本演练**：在副本上新建空库，用新 `mappings.v2` + 财年修复 + 派生传播，从 hash 校验的 `companyfacts.json`/`submissions.json` 重放并重规范化；分段/管理层/行情照旧回放。
3. **对比**：行数、期间分布、缺失状态、关键指标（净债务、D&A、财年、Q4 派生）差异，逐项对应 D01–D07。
4. **幂等**：第二次重放不重复新增有效事实；中途失败可恢复。
5. **旧运行**：11 条 valuation_run 显示“旧方法/需复核”，用户主动重算才生成新 run。
6. **切库**：确认副本对比通过后，替换真实库并保留回滚路径。

> 本文生成时仅完成盘点（第 1 步）；此历史说明不代表当前状态。当前状态以 2026-09-07 迁移演练与切换记录为准。
