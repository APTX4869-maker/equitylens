# EquityLens 修复返工 Batch 2 证据记录

日期：2026-09-06。分支：`codex/remediation-rework`。依据 `docs/superpowers/specs/2026-09-06-remediation-rework-design.md` Batch 2 章节，对照 `docs/reviews/2026-09-06-remediation-quality-review.md` 的 D08/D09/D10/V05 四项审查结论。

结论：初次提交通过已有测试，但复核发现四个未覆盖边界；提交 `599ab10` 返工后，Batch 2 的四项验收目标才达到当前设计要求。后端 197 项通过；前端 TypeScript 与 ESLint 通过。

## 逐项状态

| ID | 本轮实现 | 回归测试 | 剩余限制 |
| --- | --- | --- | --- |
| D08 快照 SHA 严格匹配 | `load_snapshot(sha=...)` 仅接受完整 SHA 或 8 字符十六进制前缀；未知 SHA 返回 None；版本化文件名与内容不匹配即报损坏；快照和 manifest 写入后 `fsync`，manifest 原子替换；发布过程按目录加锁 | `test_load_unknown_sha_returns_none_not_legacy`、`test_load_corrupted_versioned_sha_raises`、`test_load_rejects_malformed_sha_selectors`（tests/unit/test_raw_store.py） | 8 字符前缀发生真实 SHA 碰撞时会以文件名冲突显式失败，不会覆盖旧内容 |
| D10 新鲜度语义 | SEC 财务年龄改用最近披露日期；行情观察时间由共享模块按 IANA 时区转换到 UTC；顶层 freshness 与 quote_block 使用同一状态；过期/降级报价不参与现价比较；回放保留原抓取时间 | `test_ingest_today_does_not_refresh_old_filing`、`test_quote_block_marks_stale_observation`、`test_provider_timezone_is_converted_to_utc`、`test_replay_keeps_original_fetch_time_from_name`（tests/unit/test_freshness.py） | 前端各页面的独立过期说明随 Batch 4 统一 |
| V05 完整估值 run 持久化 | `valuation_run` 保存输入指纹、情景、敏感性、质量块，并在 `fact_snapshot_json.source_fact_ids` 冻结所有事实派生输入的 canonical ID；覆盖项清除不再适用的事实身份；旧 run 原样读取并标记 `legacy/incomplete` | `test_saved_run_reads_back_full_scenarios_sensitivity` 同时验证所有冻结 ID 可在 canonical 表解析；`test_legacy_run_reads_as_incomplete`（tests/integration/test_api.py） | 真实库只在应用正常打开时执行幂等加列；历史行不会补造缺失身份 |
| D09 派生结果来源身份 | `result_id` 是带 SHA-256 校验的自包含结果身份，绑定公司、指标、值、频率、单位、状态、期间、公式和完整有序输入；来源读取不重新计算当前值，因此重述不会改写旧链接；每个输入可继续展开到 canonical fact 与 source document | `test_derived_metric_has_resolvable_result_identity`、`test_derived_result_identity_binds_value_formula_and_inputs`（tests/integration/test_api.py） | 总览 KPI 仍需在 Batch 4 改为传递实际 `result_id` |

## 关键提交

- D08: `fix: strict snapshot SHA lookup + atomic manifest (D08)`
- D10: `fix: freshness semantics — SEC age by disclosure, quote status by observation (D10)`
- V05: `feat(valuation): persist complete immutable runs (V05)`
- D09: `feat(provenance): stable derived-result identity and resolvable source tree (D09)`

## 验证

- 后端：`.venv/bin/python -m pytest -q -p no:cacheprovider` → **197 passed**，1 条 Starlette/httpx 弃用警告。
- 前端：`pnpm exec tsc --noEmit --incremental false` 与 `pnpm lint` 均通过。
- 新增测试均使用临时数据库/夹具，未写入真实 `data/equitylens.duckdb`。

## 未闭环（后续批次）

1. 前端 D09 的“总览 KPI 卡点击传 null”、Topbar/财务页对过期行情显示独立警告，属 UI 收敛项，随 Batch 4（解释质量）或单独 UI 任务处理。
2. 真实数据库 `valuation_run` 的 ALTER 迁移需单独评审后执行（设计明确要求只读保护）。
