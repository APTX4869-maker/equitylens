# EquityLens 修复返工 Batch 2 证据记录

日期：2026-09-06。分支：`codex/remediation-rework`。依据 `docs/superpowers/specs/2026-09-06-remediation-rework-design.md` Batch 2 章节，对照 `docs/reviews/2026-09-06-remediation-quality-review.md` 的 D08/D09/D10/V05 四项审查结论。

结论：Batch 2 的四项验收目标（可复现、来源、新鲜度、完整估值记录）均已实现并有回归测试。后端 189 项通过；前端 TypeScript 与 ESLint 通过。

## 逐项状态

| ID | 本轮实现 | 回归测试 | 剩余限制 |
| --- | --- | --- | --- |
| D08 快照 SHA 严格匹配 | `load_snapshot(sha=...)` 仅当字节 SHA 匹配请求的完整/8 字符前缀时才返回；未知 SHA 返回 None（不回退旧固定文件）；版本化文件名与内容不匹配即报损坏；manifest 用临时文件 + `os.replace` 原子替换 | `test_load_unknown_sha_returns_none_not_legacy`、`test_load_corrupted_versioned_sha_raises`、`test_load_8char_prefix_matches_versioned`（tests/unit/test_raw_store.py） | 无 |
| D10 新鲜度语义 | SEC 财务年龄改用最近披露（filed/published）日期，ingest 完成时间仅作“最近同步”附注；行情观察时间解析下沉到共享 `market/age.py`，顶层 freshness 与 quote_block 返回同一状态；`quote_block` 对过期/降级观察返回 STALE（`valuation_market_block` 因此不再对过期行情算现价溢价）；回放保留快照文件名中的原始抓取时间 | `test_ingest_today_does_not_refresh_old_filing`、`test_quote_block_marks_stale_observation`、`test_replay_keeps_original_fetch_time_from_name`（tests/unit/test_freshness.py） | 前端仅估值页显示过期警告；Topbar/财务页仍按 `status==="OK"` 排除过期行情（方向正确但无独立警告） |
| V05 完整估值 run 持久化 | `valuation_run` 新增可空 `input_fingerprint`/`scenarios_json`/`sensitivity_json`/`model_quality_json` 列（幂等 additive 迁移）；`run_custom` 保存完整执行快照（指纹、全部情景状态/输出、敏感性单元、模型质量块）；override meta 覆盖 `op_margin_start`/`nwc_pct`；读取原样返回，缺新字段的旧 run 标记 `legacy/incomplete` 并保留 v1 输出 | `test_saved_run_reads_back_full_scenarios_sensitivity`、`test_legacy_run_reads_as_incomplete`（tests/integration/test_api.py） | 真实库 `data/equitylens.duckdb` 的 ALTER 迁移按设计留待单独评审后执行（当前只读） |
| D09 派生结果来源身份 | `MetricPoint` 增加可逆 `result_id`（`derived:{company}:{metric}:{freq}:{period_end}`）；`/metrics` 返回 `result_id`；`/provenance/{result_id}` 解析出 `metric_value` 根（携带结果值/频率/单位/状态/公式 + 完整有序输入列表，每个输入可展开到 canonical fact + source document）；MetricDrawer 把“派生自 N 个事实”展开为可点击来源列表 | `test_derived_metric_has_resolvable_result_identity`（tests/integration/test_api.py） | 总览页 KPI 卡点击仍传 `null`（未携带结果身份），属 UI 收敛项 |

## 关键提交

- D08: `fix: strict snapshot SHA lookup + atomic manifest (D08)`
- D10: `fix: freshness semantics — SEC age by disclosure, quote status by observation (D10)`
- V05: `feat(valuation): persist complete immutable runs (V05)`
- D09: `feat(provenance): stable derived-result identity and resolvable source tree (D09)`

## 验证

- 后端：`.venv/bin/python -m pytest -q -p no:cacheprovider` → **189 passed**，1 条 Starlette/httpx 弃用警告。
- 前端：`pnpm exec tsc --noEmit --incremental false` 与 `pnpm lint` 均通过。
- 新增测试均使用临时数据库/夹具，未写入真实 `data/equitylens.duckdb`。

## 未闭环（后续批次）

1. 前端 D09 的“总览 KPI 卡点击传 null”、Topbar/财务页对过期行情显示独立警告，属 UI 收敛项，随 Batch 4（解释质量）或单独 UI 任务处理。
2. 真实数据库 `valuation_run` 的 ALTER 迁移需单独评审后执行（设计明确要求只读保护）。
