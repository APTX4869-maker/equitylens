# 公司建档真实接入与迁移验收记录

日期：2026-09-12（Asia/Shanghai）

## 官方来源与独立核对

| 公司 | CIK / 证券 | 最新年度申报 | 固定快照 | 结果 |
|---|---|---|---|---|
| The Coca-Cola Company | 0000021344 / KO / NYSE | 2025-12-31；10-K `0001628280-26-010047`；2026-02-20 filed | submissions `f3e144fdab520ef86dc9aea18d5b93485df2aceababe570cae9084a675beb652`；companyfacts `53d363a9aa3071406cda9857654358f4dca42e174a1defb8cc1ce9ad2a4c9e40` | 身份、14 个必需指标和 CapEx 通过 |
| Costco Wholesale Corporation | 0000909832 / COST / Nasdaq | 2025-08-31；10-K `0000909832-25-000101`；2025-10-08 filed | submissions `1cb27b4fe2b9c1b3d2886f8f1673a5a33e0f880ccd191b8ed84303bc1973f7e9`；companyfacts `71a4fd99c86f27c3aa27b8f05b3a9705c16f0060b425395bb1a367ce239b7d1f` | 52 周财年、身份、14 个必需指标和 CapEx 通过 |
| Apple Inc. | 0000320193 / AAPL / Nasdaq | 2025-09-27；10-K `0000320193-25-000079` | 复用已固定且重新验 hash 的 SEC fixture | profile v2 核心指标通过 |
| Microsoft Corporation | 0000789019 / MSFT / Nasdaq | 2026-06-30；10-K `0001193125-26-323660` | 复用已固定且重新验 hash 的 SEC fixture | profile v2 核心指标通过 |

KO/COST 预期数值按官方 10-K 的 income statement、balance sheet 和 cash-flow statement 手工转录；每个值在 manifest 中带表名/行项目 locator、期间、单位和 accession。COST 的 REVENUE 为净销售额 269,912 百万美元加会员费 5,323 百万美元，即总收入 275,235 百万美元；不是只取“Net sales”。

离线命令：`uv run pytest tests/golden/test_onboarding_issuers.py -q`。它不访问网络，也不从待测解析器生成预期。

## 真实候选构建结果

首次使用完整 KO/COST Company Facts 封存 dataset 时发现派生季度的 lineage 写入了 canonical fact ID，发布构建器正确拒绝了这些非 raw 引用。修复后，所有派生季度引用展开为原始 SEC fact ID，四家公司均通过 lineage golden。

通用 mapping 升级为 `canonical-mappings.v3`，新增 total liabilities、total equity、投资/融资现金流、汇率影响和 cash-plus-restricted-cash。质量引擎按最新完整财年选择同一口径，并在发行人没有单独披露负债时仅用“负债及权益合计减总权益”这一可证据化恒等式生成 TOTAL_LIABILITIES。

KO/COST 的核心数值、覆盖期、单位、accession 与 Company Facts raw lineage 已通过 golden。当前环境访问两份 SEC Archives iXBRL 年报均得到 `403 Your Request Originates from an Undeclared Automated Tool`，而 `data.sec.gov` 的 submissions/companyfacts 可正常获取。由于 Company Facts 不含真实报表行级 context/locator 和维度上下文，不能据此伪造 filing 或 segment rows；两家质量报告保留 `LINEAGE.filing_context` 与 `SEGMENTS.reconciliation` 两个 BLOCKER，没有批准和 publication。

审查加固后，生产标准化只接受不可变 profile 明列的 concept；年度资产负债、现金与 EPS 检查必须落在同一财年、期末和 `as_known_at`，负债差额也必须来自同 accession/单位/申报版本。submissions 与 companyfacts 都作为独立 source document 封存，证券身份和适用性声明只接受 source ID 与 SHA-256 都能在该 dataset 解析的专属证据。缺少已命名 iXBRL 分部解析器时任务停在 `NEEDS_ADAPTATION`，不会进入可批准状态。

真实后端与独立 `/tmp/equitylens-t10-online.kQww7F` 数据目录的页面验收中，`www.sec.gov/files/company_tickers.json` 同样返回 403。修复后的边界将其转换为 `SEC_UNAVAILABLE` / HTTP 503，添加公司对话框清楚显示“temporarily unavailable; retry later”，KO 未进入公司目录。截图：`/tmp/equitylens-onboarding-live.png`。这验证了在线失败闭环，不等同于成功发布闭环；成功候选路径由离线官方快照、集成测试和浏览器 API fixture 覆盖。

## 迁移与故障恢复

- 正式源库：`/Users/vincent/workspace/equitylens/data/equitylens.duckdb`，34 MB；演练前 `lsof` 无持有进程。
- 原始证据：`/Users/vincent/workspace/equitylens/data/raw`，96 MB。
- 演练目录：`/Users/vincent/.local/share/equitylens-migration-rehearsal/20260912T090430Z/`。
- 主报告：`report.json`；双次 material table 回放与 source identity 幂等，数据库/原始目录备份哈希一致，历史估值运行保真。
- 故障报告：`failure-recovery.json`；事务内把 Apple 名称改为故障标记后主动抛错，回滚前后均为 `Apple Inc.`；从备份恢复数据库的 SHA-256 与源备份均为 `ebfbaf7374235d71b2a016b70f5bf9c83591e2408e3b868f3cd6b156b63bdfe5`。

仓库内的可移植证据位于 `tests/fixtures/onboarding/`、`tests/golden/test_onboarding_issuers.py` 和 `config/issuers/`；上述绝对路径仅记录本机历史演练。验收环境关键版本：DuckDB 1.5.5、Pydantic 2.13.5、FastAPI 0.141.1、HTTPX 0.28.1。T10 开始基线提交为 `e25673711fbbc67fa24455a109cf22e58de96f8f`，实现与全量验收提交为 `e6fc9af`。

正式数据库和正式 raw 目录在本次验收中均未写入；没有覆盖用户数据。

## 结论

身份、官方数据快照、核心数值、期间/单位、Company Facts raw lineage、生产任务流水线和迁移恢复路径已达到“候选可审查、证据不足即阻断”的目标。当前记录没有完成任何真实发行人的成功 publication：KO/COST 的报表行级 context 与分部 iXBRL 原件仍受外部证据阻塞，AAPL/MSFT 也未把 legacy 状态冒充新标准批准。解除阻塞后必须重新生成固定审查包并用当前 revision/fingerprint 批准。
