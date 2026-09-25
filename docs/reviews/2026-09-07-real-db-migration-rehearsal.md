# EquityLens 真实库迁移演练与切换记录

日期：2026-09-07

状态：**完成**

> **2026-09-11 纠正：** 合并前复审发现旧离线重放会覆盖 SEC 来源的 `fetched_at`，而本报告当时只比较来源 ID 与内容 SHA，未发现 22 条时间污染。现已恢复原时间、为旧快照补 manifest，并把时间与路径纳入演练摘要。最终复验见本文末尾“复审纠正”。

## 执行范围

按修复交接文档 §8.3 顺序完成真实库备份、副本离线重放、关键差异核对、第二次重放幂等验证和真实库原子切换。整个过程未联网抓取数据，原始快照未被改写。

演练工具：`scripts/rehearse_real_db_migration.py`

演练报告：`/Users/vincent/.local/share/equitylens-migration-rehearsal/20260907T144813Z/report.json`

## 备份与回滚

| 项目 | 路径 / 校验值 |
| --- | --- |
| 切换前数据库 SHA-256 | `63048c1120c77ffab37cfcf28fd49f5aa2d1b05324e83c5634fdb6e9430a94e3` |
| 外部数据库备份 | `/Users/vincent/.local/share/equitylens-migration-rehearsal/20260907T144813Z/source.duckdb` |
| 外部原始快照备份 | `/Users/vincent/.local/share/equitylens-migration-rehearsal/20260907T144813Z/raw` |
| 原始快照树摘要 | `9fb59ea4eb12660c47c305db26844bb1198e3e1263ab13d5e6df0dfdec9174ea`（46 个文件） |
| 同目录快速回滚库 | `data/equitylens.duckdb.pre-20260907T1453Z.bak` |
| 切换后数据库 SHA-256 | `659565323afad87e52f5874f962887db5a7c9bf8738d7b540fffd1d1b1878d1d` |

数据库和原始快照副本均在重放前逐文件校验。真实库切换前再次核对源数据库哈希，候选库只有在业务表摘要与已通过的演练候选完全一致后才通过同一文件系统上的原子改名替换。

回滚方法：停止本地 API，确认没有进程持有数据库文件后，将当前 `data/equitylens.duckdb` 移出，再把同目录 `.bak` 原子改名为 `data/equitylens.duckdb`。外部备份提供第二条恢复路径。

## 重放结果

源库在本轮开始前已经包含用户执行的 v2 规范化结果。本轮确认该结果质量合格，并补齐当前代码所需的幂等 schema 迁移；没有把旧研究运行重算为新版本。

| 业务表 | 基线 | 第一次副本重放 | 第二次副本重放 | 切换后 |
| --- | ---: | ---: | ---: | ---: |
| `raw_fact` | 57,806 | 57,806 | 57,806 | 57,806 |
| `canonical_fact` | 11,301 | 11,301 | 11,301 | 11,301 |
| `segment_fact` | 528 | 528 | 528 | 528 |
| `executive` / `executive_compensation` / `board_member` | 11 / 27 / 21 | 相同 | 相同 | 相同 |
| `insider_transaction` | 20 | 20 | 20 | 20 |
| `market_quote` | 2 | 2 | 2 | 2 |
| `valuation_run` | 11 | 11 | 11 | 11 |
| `valuation_plan` | 0 | 0 | 0 | 0 |

两次副本重放后，以上业务表的语义摘要完全一致。`canonical_fact.created_at` 记录每次规范化执行时间，按审计字段单独处理；去除该处理时间后，事实的 ID、值、期间、状态、映射和来源逐行一致。`ingestion_run` 每轮按设计新增两条成功审计记录，不参与“有效事实不重复”的判定。

11 条 `fcff_dcf.v1` 旧估值运行的原有十个字段摘要保持不变；新增的 v2 兼容字段全部为空，因此旧结果没有被新逻辑补造或覆盖。API 会将这类记录标记为 `legacy/incomplete`，用户主动重算时才创建 v2 run。

## D01–D07 对比

| 检查 | 切换后结果 |
| --- | --- |
| 映射版本 | 11,301 / 11,301 均为 `canonical-mappings.v2` |
| D01 债务拆分 | `LONG_TERM_DEBT_CURRENT` 206、`SHORT_TERM_BORROWINGS` 56、`COMMERCIAL_PAPER` 163 |
| D02 MSFT 折旧摊销 | `DEPRECIATION` 91、`AMORTIZATION_OF_INTANGIBLE_ASSETS` 229；FY2026 同期合计 39,000,000,000 美元 |
| D03 早期财年污染 | `period_end < 2010` 且错误落入 FY2015/FY2020：0 |
| D04/D05 派生季度披露时间 | `CALCULATED` 且 `as_known_at IS NULL`：0 |
| D06/D07 当前 TTM | AAPL 466,823,000,000；MSFT 331,839,000,000，均由 4 个连续季度输入生成 |
| 当前净债务 | AAPL 21,945,000,000；MSFT -36,549,000,000，公式 `net_debt.v2` |

离线同步报告中的 `unmapped_concept` 是完整 SEC Company Facts 中未纳入当前指标注册表的概念统计（AAPL 19,817、MSFT 27,000），与基线一致，不表示已映射事实丢失。

## 演练中修复的问题

管理层同步原先虽然接收 `raw_dir`，但 `list_filing_docs` 仍隐式读取默认真实目录，使副本演练不能证明自包含恢复。本轮增加回归测试并把代理文件与 Form 4 的选择都绑定到传入的副本目录。

失败恢复通过两层保证：抓取侧已有“相关快照全部落盘后再一次发布 manifest”的回归；迁移侧始终在独立候选库重放，任何失败都在原子改名前退出，旧真实库与已校验备份保持可读。

## 复审纠正（2026-09-11）

- 从切换前回滚库按来源 ID 与内容 SHA 恢复 22 条被覆盖的抓取时间，恢复后 42 条来源记录时间差异为 0。
- 42 个文件内容 SHA 与数据库完全一致；为 40 个旧快照目录创建本地 manifest，记录确切文件名、SHA 与原抓取时间。
- 修复前当前库备份：`/Users/vincent/.local/share/equitylens-migration-rehearsal/20260911-fetched-at-repair/source-before-repair.duckdb`，SHA-256 `659565323afad87e52f5874f962887db5a7c9bf8738d7b540fffd1d1b1878d1d`。
- 修复后真实库 SHA-256：`ebfbaf7374235d71b2a016b70f5bf9c83591e2408e3b868f3cd6b156b63bdfe5`。
- 新演练报告：`/Users/vincent/.local/share/equitylens-migration-rehearsal/20260911T010942Z/report.json`。数据库、86 个 raw/manifest 文件备份、业务表幂等、来源时间/路径幂等和 11 条旧估值运行保留全部通过。
