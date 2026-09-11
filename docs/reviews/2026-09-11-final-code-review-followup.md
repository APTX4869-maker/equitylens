# EquityLens 合并前代码审查返工

日期：2026-09-11

状态：**进行中**

审查范围：`e8d32ca..f1fbca1`

## 返工顺序

### 第一组：摄取与刷新

- [x] 财务刷新以 `COMPANYFACTS_SNAPSHOT` 身份判断变化。
- [x] 分部离线重放解析 manifest 指向的确切版本文件。
- [x] SEC 离线重放保留原始抓取时间，迁移摘要校验时间与路径。
- [x] 刷新预检异常后释放公司锁和全局写锁。

### 第二组：估值后端

- [ ] DCF 流量输入按同一基准财年选择，时点输入采用明确日期策略。
- [ ] WACC 执行正数边界。
- [ ] 复制 `needs_review` 方案不能恢复为 `current`。
- [ ] Reverse DCF 对目标价格和假设执行结构化 400 错误契约。

### 第三组：前端状态

- [ ] 局部模块重试不能清除尚未重新计算的估值过期状态。
- [ ] Reverse DCF 响应绑定公司、输入指纹和目标价格，旧响应不得覆盖新状态。

### 第四组：数据与验收

- [ ] 恢复真实库中被离线重放覆盖的历史 `fetched_at`，核对来源路径。
- [ ] 更新迁移演练摘要和进度文档。
- [ ] 后端、TypeScript、ESLint、Playwright 全量通过后重新审查合并条件。

## 审查基线验证

- 后端：231 passed，1 条既有 Starlette/httpx 弃用警告。
- TypeScript 与 ESLint：通过。
- Playwright（系统 Chrome）：10 passed。

这些绿色结果没有覆盖上面的组合路径，因此不能作为合并依据。

## 第一组交付记录

- 快照 manifest 保存 provider `fetched_at`；旧快照使用文件 mtime 作为稳定回退。`load_snapshot_record` 一次返回校验后的内容、SHA、确切版本路径和抓取时间。
- Company Facts、10-K/10-Q、DEF 14A 和 Form 4 离线重放均使用该记录，不再把历史来源更新时间改为重放时间。
- 财务刷新身份改为最新 `COMPANYFACTS_SNAPSHOT`；预检被纳入锁释放 `finally`。
- 聚焦验证：`tests/unit/test_raw_store.py` + `tests/unit/test_replay_paths.py` 22 passed；刷新组合筛选 8 passed。
