# EquityLens 合并前代码审查返工

日期：2026-09-11

状态：**已完成，可进入分支集成选择**

审查范围：`e8d32ca..f1fbca1`

## 返工顺序

### 第一组：摄取与刷新

- [x] 财务刷新以 `COMPANYFACTS_SNAPSHOT` 身份判断变化。
- [x] 分部离线重放解析 manifest 指向的确切版本文件。
- [x] SEC 离线重放保留原始抓取时间，迁移摘要校验时间与路径。
- [x] 刷新预检异常后释放公司锁和全局写锁。

### 第二组：估值后端

- [x] DCF 流量输入按同一基准财年选择，时点输入采用明确日期策略。
- [x] WACC 执行正数边界。
- [x] 复制 `needs_review` 方案不能恢复为 `current`。
- [x] Reverse DCF 对目标价格和假设执行结构化 400 错误契约。

### 第三组：前端状态

- [x] 局部模块重试不能清除尚未重新计算的估值过期状态。
- [x] Reverse DCF 响应绑定公司、输入指纹和目标价格，旧响应不得覆盖新状态。

### 第四组：数据与验收

- [x] 恢复真实库中被离线重放覆盖的历史 `fetched_at`，核对来源路径。
- [x] 更新迁移演练摘要和进度文档。
- [x] 后端、TypeScript、ESLint、Playwright 全量通过后重新审查合并条件。

### 第五组：独立复审补修

- [x] Reverse DCF 请求被输入编辑作废时同步解除加载状态，按钮可再次计算。
- [x] 税率只有单边事实或税前利润为零时，数值与来源元数据一致采用配置回退。
- [x] 公司切换期间隔离迟到的刷新响应。
- [x] Reverse DCF 拒绝非对象 `assumptions` 并返回结构化 400。
- [x] 完成最终全量验证。
- [x] 完成第二轮独立复审。

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

## 第二组交付记录

- 最新年度收入确定 DCF 流量输入基准 FY；营业利润和稀释股数缺少同年事实时明确阻止估值，税率、CapEx 与 D&A 只在同年事实完整时计算，否则使用有标签的配置回退。
- 净债务采用最新可用资产负债表时点，并在元数据中记录该实际日期，不再伪装为收入财年。
- WACC 必须为正；Reverse DCF 在求根前验证完整假设，目标价格必须为有限正数，错误统一返回 `error.code/field/message` 的 400。
- 复制待复核方案继承 `needs_review` 和原因，不能通过复用旧 run 洗回 current。
- 新增失败反例 8 passed；完整估值 golden 与 API 回归 95 passed。

## 第三组交付记录

- 父页面为每家公司维护估值复核代数；只有财务或行情身份真正变化才递增。局部重试只合并被重试模块，不能用 `review_required=false` 覆盖仍待重新计算的状态。
- Reverse DCF 使用独立请求序号，并绑定 ticker 组件实例、完整草稿指纹、目标价格和复核代数；编辑期间返回的旧响应被忽略。
- TypeScript 与 ESLint 通过；刷新重试和估值竞态组合 Playwright 5 passed。

## 第四组交付记录

- 对比切换前回滚库后确认 22/42 条来源记录曾被旧离线逻辑改写抓取时间；按相同 `source_document_id + content_sha256` 恢复后，时间差异为 0。
- 42 个原始文件逐一通过 SHA-256 与数据库校验，为 40 个旧布局目录创建带原始抓取时间的 manifest；数据库、确切路径、内容 SHA 和 manifest 时间 42/42 一致。
- 修复前备份：`/Users/vincent/.local/share/equitylens-migration-rehearsal/20260911-fetched-at-repair/source-before-repair.duckdb`，SHA-256 `659565323afad87e52f5874f962887db5a7c9bf8738d7b540fffd1d1b1878d1d`。
- 修复后真实库 SHA-256：`ebfbaf7374235d71b2a016b70f5bf9c83591e2408e3b868f3cd6b156b63bdfe5`。
- 严格副本演练：`/Users/vincent/.local/share/equitylens-migration-rehearsal/20260911T010942Z/report.json`；业务表、来源时间/路径、旧估值运行、DB 与 raw 备份 5 项全部通过，两轮来源摘要均为 `7bf861ac936a46826f8aeb27464b31af695edb2addc75ec76d30010aba0b2d4e`。
- 最终验证：后端 245 passed；TypeScript、ESLint 通过；系统 Chrome Playwright 11 passed。

## 当前结论

原 10 个 Important 审查项和独立复审确认的 4 个 Important 均已返工并有反例覆盖。最终全量验证：后端 251 passed，TypeScript 与 ESLint 通过，系统 Chrome Playwright 12 passed，Git 差异检查通过；仅有 1 条既有 Starlette/httpx 弃用警告。第二轮独立复审未发现新的 Critical 或 Important，独立聚焦验证为后端 10 passed、系统 Chrome 竞态 6 passed，当前可以进入分支集成选择。
