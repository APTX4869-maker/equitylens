# EquityLens 修复返工进度

日期：2026-09-06

执行分支：`codex/remediation-rework`

依据：

- `docs/reviews/2026-09-05-equitylens-remediation-handoff.md`
- `docs/reviews/2026-09-06-remediation-quality-review.md`
- `docs/superpowers/specs/2026-09-06-remediation-rework-design.md`
- `docs/superpowers/plans/2026-09-06-remediation-batch1.md`
- `docs/reviews/2026-09-06-remediation-batch1-rework.md`
- `docs/reviews/2026-09-06-remediation-batch2-rework.md`

## 当前状态

**Batch 1 与 Batch 2 已完成；Batch 3 已完成 P02，正在执行 P06。**

- Batch 1（正确数字与输入身份）：当前 TTM 契约、市场倍数回退、风险/研究失败覆盖、DCF 边界、估值输入指纹与结构化错误、前端完整草稿身份。
- Batch 2（可复现/来源/新鲜度）：D08 快照 SHA 严格匹配、D10 新鲜度语义、V05 完整估值 run 持久化、D09 派生结果来源身份。
- Batch 3 P02：新估值默认使用 `fcff_dcf.v2`；稳定期单独构造 year-6 NOPAT/再投资/FCFF，终值不再重复增长；默认、预览、情景、敏感性、反推、保存和前端草稿使用同一模型输入。

本轮复核发现原 Batch 2 记录的测试没有覆盖四个边界，并已在提交 `599ab10` 修复：

- SHA 选择器现在只接受 8 位十六进制前缀或完整 64 位 SHA；快照与 manifest 在发布前 `fsync`，并用进程锁避免并发发布丢失指针。
- ET/PT/CT/MT 行情时间按 IANA 时区转换为 UTC，夏令时和冬令时不再被误当 UTC 文本。
- 保存的估值 run 新增 `source_fact_ids`，冻结实际使用且可在 `canonical_fact` 中解析的事实身份；用户覆盖项会清除原事实身份。
- 派生结果 ID 改为带 SHA-256 校验的自包含内容身份，绑定值、公式、期间和有序输入；同期间重述会生成新 ID，旧 ID 仍解析原始根。

批次证据与逐项状态见 `docs/reviews/2026-09-06-remediation-batch1-rework.md` 与 `docs/reviews/2026-09-06-remediation-batch2-rework.md`。

## 验证

- 最近全量后端：197 passed，1 条 Starlette/httpx 弃用警告（Batch 2 返工后）。
- Batch 3 P02 聚焦验证：估值 golden + API 共 74 passed；新增非法稳定期 ROIC API 回归 7 passed（聚焦集）。
- 前端：TypeScript `--noEmit` 与 ESLint 通过。
- Playwright：2 个受控乱序用例通过收集/类型检查；实际执行确认本机缺 Chromium。再次下载 182.1 MiB 运行时后长时间停在 0%，已中止，浏览器测试仍未执行。

## 下一批次

Batch 3 剩余顺序：个人估值方案闭环（P06）→ 一键更新（P08）。随后 Batch 4（解释与新手质量）：默认假设逐项溯源（P01）、情景负增长与公司故事（P03）、新手引导（P04）、证据与结论（P05）。
