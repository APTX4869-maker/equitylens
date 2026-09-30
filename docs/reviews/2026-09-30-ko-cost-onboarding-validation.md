# KO/COST 正式建档验证（2026-09-30）

## 结论

KO 与 COST 已完成真实 SEC 采集、发行人专属 Profile v2 适配、不可变数据集构建、质量门禁、维护者审核和正式原子发布。两家公司最终质量均为 `PASS`、BLOCKER 为 0，公司目录状态均为 `VERIFIED`，`overview` 与 `freshness` API 均返回 200。

## 数据口径与证据

- KO 最新年度证据为 2025-12-31 10-K，accession `0001628280-26-010047`。五个经营分部收入合计 48.806B，Corporate 0.144B 标为 `unallocated`，Consolidation Eliminations -1.009B 标为 `elimination`，与合并收入 47.941B 精确对账。
- COST 最新年度证据为 2025-08-31 10-K，accession `0000909832-25-000101`。United States 200.046B、Canada 36.923B、Other International 38.266B，与合并收入 275.235B 精确对账。
- KO 债务口径使用 `LongTermDebtAndCapitalLeaseObligationsCurrent` 与 `LongTermDebtAndCapitalLeaseObligations`；COST 使用 `LongTermDebtCurrent` 与 `LongTermDebtNoncurrent`，并单列 1.123B 短期投资。mapping v5 的边界测试确保债务组成不重叠。
- Profile evidence 对固定 filing 哈希逐项解析 XPath；指标节点必须匹配 concept，证券节点必须同时证明 ticker 与交易所，分部 evidence 必须以收入/利润节点证明声明轴下的已配置成员，不能用无关节点冒充。

隔离验证最初生成 profile/bundle v2。正式抓取时 SEC 对相同 accession 返回不同字节，哈希门禁正确把任务暂停在 `NEEDS_ADAPTATION`；随后创建不可变 profile/bundle v3 并重新验证，未覆盖旧版本、未复用旧审核指纹。

## 备份与正式发布

正式写入前 `lsof data/equitylens.duckdb` 无 writer。备份目录为 `/Users/vincent/.local/share/equitylens-backups/20260930T142331Z-ko-cost-onboarding/`：

- 正式数据库与备份 SHA-256 均为 `622ae59c567abf8a50aa880bb8e6035481dce1ae6ee0e448d59b97dc9ec9e1aa`。
- 源与备份 raw 均为 238 个文件，排序内容清单摘要均为 `771d8094a87525b9c9c35b91812745bb23326f8e487f84f1a50fd834e29ac0e6`。

正式记录：

| 公司 | 任务 | 质量报告 | 审核 | Publication |
|---|---|---|---|---|
| KO | `9a730f85-a712-43db-934b-2a0ef2045240` | `140de485-f01b-4cbd-8771-0e2969da2595` | `1e442d44-091e-441f-bc7c-5a00f853095e` | `04df30fc-e9ba-4fc2-a9ff-be65642fd61c` |
| COST | `918b1191-df46-41a3-8403-fc1eb4b1e9ef` | `c9534acb-887d-439a-9b75-47979c8ca7e8` | `4d88f634-f7e8-47f5-8c16-7245d2e1caf3` | `be258aac-5991-4a1b-9359-14fb4832d493` |

## 测试与审查

- v3 固定 bundle 在临时数据库逐文件校验 SHA-256、真实 BUILD 并运行质量引擎，两家公司均 PASS。
- Golden 逐项断言最新年度 canonical 核心值、债务/短投组成、分部值、成员 kind 和分部精确加总，不以质量引擎的内部自洽替代人工预期。
- 独立审查未发现 Critical；“缺人工值断言”和“分部 evidence 未证明配置成员”两项 Important 已修复并由审查者确认关闭。
- 最终后端全量测试和 `git diff --check` 的结果记录在主进度文档提交收尾处。
