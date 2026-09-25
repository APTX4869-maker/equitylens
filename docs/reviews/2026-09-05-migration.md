# EquityLens 真实库迁移执行记录

> 执行时间：2026-09-05。依据 `2026-09-05-equitylens-remediation-handoff.md` §8.3 第 2–6 步，
> 在用户授权后完成。前置只读盘点见 `2026-09-05-real-db-inventory.md`。

## 结论

真实库 `data/equitylens.duckdb` 已用**新 mappings.v2 + 财年修复 + 派生传播**重建并切换到位。
旧库保留两份回滚副本；11 条旧估值运行已复制并标记“旧方法/需复核”。全程未联网（`fetch=False` 从 hash 校验的本地快照回放）。

## 执行步骤

### 2. 备份
- `data/equitylens.duckdb.bak-20260905-224016`（时间戳备份，MD5 `a024b312…`）
- `data/equitylens.duckdb.pre-migration`（回滚用，与 .bak 内容一致）
- 原始快照 `data/raw/` 未改动（`save_snapshot` 不可变语义）。

### 3. 副本上重放重建
在 `data/equitylens.rebuilt.duckdb`（副本，非真实库）上，`fetch=False` 回放：
`sync_company` → `sync_segments` → `sync_management` → `sync_quotes`（AAPL/MSFT）。
> 期间发现并修复一个迁移阻断 bug：`sync_management` 的 `fetch=False` 路径把 Form 4 的
> `fetched_at` 写成空串导致 `upsert_source_documents` 时间戳转换失败（已改为合法 UTC 时间戳）。

### 3. 对比（旧 vs 新，逐项对应 D01–D07）

| 缺陷 | 旧库 | 新库 | 结论 |
| --- | --- | --- | --- |
| D01 债务 | MSFT 总债务 49.521B（40.294+9.227 重复） | 40.294B；净债务 −27.322B → **−36.549B** | 9.227B 重复消除 |
| D02 折旧 | MSFT 无 D&A 指标 | `DEPRECIATION` 70 + `AMORTIZATION_OF_INTANGIBLE_ASSETS` 205；合计 **39.0B** | 34.3+4.7=39B |
| D03 财年 | AAPL 253 条→FY2015；MSFT 255 条→FY2020 | AAPL →FY2007/08/09/10；MSFT →FY2008/09/10 | 旧事实归入正确财年 |
| D04/D05 派生 | 312 条 `as_known_at` 全为 NULL | 312 条 **全部非 NULL** | 重述可区分 |
| D06/D07 TTM | 引擎即时计算 | 无需迁移，新引擎读取即生效 | — |
| 基准不变 | AAPL FY2025 收入 416.161B | 416.161B（一致） | 正常数据未漂移 |

### 4. 幂等与恢复
- 幂等：对副本重新 `sync_company(AAPL)`，canonical=5558 / raw=25135 前后一致（`replace_*` 按 source_document_id DELETE+INSERT，天然幂等）。
- 恢复：整个重建在副本上进行，真实库始终未动；中途失败只需删除半成品副本重跑。

### 5. 旧估值运行
- 11 条 `valuation_run`（`fcff_dcf.v1`）复制入新库，`warnings_json` 追加“旧方法 · 受已知数据问题影响，需复核后重算”，输入/输出快照原样保留（可回放）。

### 6. 切库与回滚
- 旧 `data/equitylens.duckdb` → `data/equitylens.duckdb.pre-migration`。
- `data/equitylens.rebuilt.duckdb` → `data/equitylens.duckdb`。
- **回滚**：`mv data/equitylens.duckdb.pre-migration data/equitylens.duckdb` 即还原。

## 验证

- 新库 `mapping_version = canonical-mappings.v2`（唯一）；`LONG_TERM_DEBT_CURRENT` 206 条；`valuation_plan` 表已创建；11 条 run 全部 legacy-marked。
- 全量 `pytest -q` → **160 passed**（代码回归无退化）。
- 前端 `tsc --noEmit` + `lint` 通过（此前已验证）。

## 遗留说明

- 旧估值运行仍标“旧方法”，用户在前端重算后才会生成新 `valuation_run`（新旧关系未自动关联，符合最小交付）。
- 新库文件 26.4 MB（旧 54.2 MB）——DuckDB 重建后 checkpoint 更紧凑，非数据缺失。
