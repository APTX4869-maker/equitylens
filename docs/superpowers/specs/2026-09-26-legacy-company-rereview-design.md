# EquityLens 旧版公司新标准复核设计

**日期：** 2026-09-26  
**状态：** 已确认  
**依赖：** `docs/superpowers/plans/2026-09-11-company-onboarding.md` T01—T09 已完成；AAPL/MSFT 现有 publication 标记为 `LEGACY_UNREVIEWED`

## 1. 目标与问题

AAPL 和 MSFT 已有可读的 legacy publication、v2 发行人 profile 与独立 golden，但正式库没有对应建档任务、质量报告或审核记录。普通建档入口对已有 active publication 的证券固定返回 `ALREADY_PUBLISHED`，因此维护者无法使用既有 FETCH → BUILD → VALIDATE → REVIEW → PUBLISH 流水线完成新标准复核。

本阶段增加维护者专用 rereview 入口，使 `LEGACY_UNREVIEWED` 公司能够创建标准持久化任务。复核期间旧 publication 继续服务普通读取；只有新候选质量 PASS、人工批准精确指纹且活动 publication 仍等于任务创建时的基线，才原子切换到新 publication。

## 2. 范围

包含：

- 新增维护者 API 和 CLI，从已有 ticker/security 创建 rereview 任务；
- 任务显式绑定创建时的 `base_publication_id`；
- 复用现有采集、profile 导入、候选封存、质量、审核和发布流程；
- 发布事务比较当前活动 publication 与任务基线；
- 任务继续出现在已有建档中心和全局待关注入口，不新增另一套进度 UI；
- 先在隔离数据库完成 AAPL、MSFT 全流程验收，确认后再按备份流程处理正式库。

不包含：

- 不允许普通“添加公司”按钮启动旧版复核；
- 不允许 VERIFIED 公司借此重复复核；未来若需要主动重建 VERIFIED 数据，另行设计版本升级流程；
- 不允许跳过网络采集、质量检查或人工审核；
- 不改变 KO/COST 的证据阻塞状态；
- 不直接改写旧 publication、旧估值运行或旧来源记录。

## 3. 接口与持久化

### 3.1 API

新增：

```text
POST /api/v1/company-onboardings/rereview
Idempotency-Key: <required>
{
  "ticker": "AAPL"
}
```

响应沿用建档任务 payload，成功为 `202 Accepted`。ticker 使用现有证券注册表解析，不接受 company_id、publication_id 或本地路径等可伪造身份字段。

错误契约：

- `SECURITY_NOT_FOUND`：ticker 不存在或不是活动证券；
- `AMBIGUOUS_SECURITY`：ticker 无法唯一解析；
- `NO_ACTIVE_PUBLICATION`：公司没有当前 publication；
- `REREVIEW_NOT_ALLOWED`：公司不是 `LEGACY_UNREVIEWED`；
- `IDEMPOTENCY_CONFLICT`：同一幂等键对应不同请求；
- `TASK_CONFLICT`：并发状态变化使创建条件失效。

同公司已有活动建档任务时，返回并关联该任务；不能创建第二条并行任务。相同幂等键和请求返回同一任务；同一 ticker 使用不同幂等键时仍由“每发行人一个活动任务”约束收敛。

### 3.2 CLI

新增：

```bash
uv run equitylens onboarding rereview AAPL --idempotency-key legacy-aapl-v2
```

CLI 只调用本地 API，不在 API 不可用时直接写 DuckDB。输出完整任务 JSON，后续继续使用现有 `show`、`profile-import`、`export` 和 `review` 命令。

### 3.3 数据模型

`company_onboarding` 增加 nullable `base_publication_id`：

- 新公司首次建档为 `NULL`；
- rereview 创建时固定为当时的 `company.active_publication_id`；
- 字段进入任务视图、步骤输入哈希和审查包，使候选与批准记录可追溯到替换前版本；
- migration 有版本、checksum 与幂等测试，不能只修改新库 schema。

幂等请求哈希至少包含操作类型 `REREVIEW`、规范 ticker、security_id 和 `base_publication_id`，防止旧请求在活动 publication 改变后静默复用。

## 4. 数据流与原子性

1. API 解析 ticker，读取活动 security、company quality status 和 active publication。
2. 在统一 writer 事务内再次验证三者未变化，并创建或复用任务；任务状态从 `QUEUED/FETCH` 开始。
3. 现有执行器从 SEC 重新采集不可变 submissions、Company Facts 和所需 filing 文档。网络失败保留结构化错误并允许重试，旧 publication 始终可读。
4. 维护者导入已复核的 v2 profile；流水线构建独立 dataset、运行质量规则并生成固定审查包。
5. 质量 PASS 后，维护者批准精确 fingerprint，任务进入 `PUBLISHING`。
6. 发布事务把 `base_publication_id` 传给现有 `expected_active_publication_id` 门禁。当前指针不一致时返回 `PUBLICATION_CONFLICT`，不插入新 publication、不改变旧指针、不把任务标记为已发布。
7. 成功时插入不可变 publication/capabilities，使旧估值计划进入 `needs_review`，原子更新活动指针和公司质量状态为 `VERIFIED`。

旧 publication 永不删除，显式指定旧 publication_id 的历史读取仍可解析。新 publication 成为默认读取版本。

## 5. 页面与用户体验

本阶段不增加普通用户按钮。任务创建后直接进入现有建档中心，沿用五阶段进度、失败原因、重试、profile 导入、质量报告和审核动作。公司侧栏继续显示旧版公司；复核未发布前不会出现数据半更新，也不会暂时移除公司。

任务详情应显示“旧版公司新标准复核”和基线 publication，避免维护者误以为正在新增证券。普通用户看到的公司质量状态在原子发布前仍为 `LEGACY_UNREVIEWED`，发布后统一变成 `VERIFIED`。

## 6. 测试与验收

测试必须先失败再实现，至少覆盖：

- legacy 公司能创建带 `base_publication_id` 的 rereview 任务；
- VERIFIED、无 active publication、未知/歧义 ticker 被拒绝；
- 幂等键重放与冲突、不同键并发创建收敛到同一活动任务；
- 普通新增公司仍对已发布证券返回 `ALREADY_PUBLISHED`；
- 任务运行期间默认读取仍指向旧 publication；
- 当前 publication 在审核或发布前变化时，原子发布返回 `PUBLICATION_CONFLICT`，旧指针和候选状态不被伪装为成功；
- 成功发布后公司变为 `VERIFIED`、旧 publication 可显式读取、估值计划进入待复核；
- CLI 只调用 API，连接失败不直接写库；
- 建档中心能显示 rereview 任务及基线信息；
- AAPL/MSFT golden、全量后端、TypeScript、ESLint、生产构建和 Playwright 全部回归。

真实数据验收顺序：复制正式数据库和 raw 到明确的临时目录并校验摘要；在副本逐一完成 AAPL、MSFT 采集、v2 profile、质量报告、审查包、批准和发布；核对新旧 publication、来源、关键财务、分部、页面与估值门禁。只有副本结果完整通过，且正式服务停止写入并完成可恢复备份，才允许对正式库重复相同受支持流程。

## 7. 失败与恢复

- FETCH/BUILD/VALIDATE 失败：保留旧 publication，使用已有重试或 profile 修正流程恢复；
- 质量 BLOCKER：停在维护者处理状态，禁止审核通过；
- 审核指纹过期：返回 `REVIEW_STALE`，重新导出审查包；
- 活动 publication 改变：返回 `PUBLICATION_CONFLICT`，当前任务不得继续发布；维护者取消旧任务后从新基线创建新任务；
- 进程中断：沿用持久化 attempt 和启动恢复；
- 正式执行异常：停止服务，从已校验备份恢复，不对旧 publication 做逆向删除。

## 8. 完成条件

- 维护者能够通过 API/CLI 为 AAPL、MSFT 创建可恢复、可审计的 rereview 任务；
- 任一未通过质量或审核门槛的候选都不能切换活动 publication；
- AAPL、MSFT 在隔离副本完成新标准全流程后，正式库按相同流程切换为 `VERIFIED`；
- KO/COST 的现有证据阻塞保持不变；
- 实现、真实验收、备份位置、publication/quality/review 标识和测试结果写回进度文档。
