# AAPL/MSFT 旧版公司新标准复核验收

日期：2026-09-26

结论：复核入口、幂等任务、旧发布基线、质量门禁和页面身份展示均已实现并通过自动化验证。AAPL 与 MSFT 在正式数据隔离副本中都完成真实 SEC FETCH、BUILD 和 VALIDATE，但质量报告各有四个 BLOCKER，因此没有批准或发布，也没有修改正式数据库。T10 真实发布项继续保持未完成。

## 副本与正式数据保护

- 演练目录：`/tmp/equitylens-legacy-rereview.dNlaWD`
- 建立副本前 `lsof data/equitylens.duckdb` 无输出，没有进程持有正式库。
- 正式数据库复制前 SHA-256：`5eaa4a8626ef4a0da29d875bef4831d1d3637d88f884540f09a76dacb433cc1c`
- 副本复制后、首次打开前 SHA-256：`5eaa4a8626ef4a0da29d875bef4831d1d3637d88f884540f09a76dacb433cc1c`
- 正式 raw 与副本复制前均为 181 个文件；相对路径及逐文件内容组成的清单 SHA-256 均为 `c9bab267c2da4a9baa259524939ad4c4c95298b9c157d7f8415143cc937ffa81`。
- 复制前正式表计数：`company=3`、`publication=3`、`company_onboarding=1`、`issuer_profile_version=4`、`valuation_plan=0`。
- 隔离演练后副本数据库 SHA-256：`816da8f1ff669102bd95a6b7caf5f5ee856b72b867f08a8391b198287660a662`；隔离 raw 增至 238 个文件，证明网络结果只写入副本。
- 演练结束后正式数据库 SHA-256 仍为 `5eaa4a8626ef4a0da29d875bef4831d1d3637d88f884540f09a76dacb433cc1c`，正式 raw 仍为 181 个文件且清单哈希不变；`lsof` 再次无输出。
- 因两家公司均未通过质量门槛，没有创建正式备份或进入正式迁移步骤；正式 AAPL/MSFT 都保持原 active publication 和 `LEGACY_UNREVIEWED`。

## 真实 API/CLI 演练

隔离 API 使用 `EQUITYLENS_DATA_DIR=/tmp/equitylens-legacy-rereview.dNlaWD/data`、已配置的识别性 SEC User-Agent 和端口 18000 启动。联系方式不写入报告。调用命令：

```bash
EQUITYLENS_API_URL=http://127.0.0.1:18000/api/v1 \
  equitylens onboarding rereview AAPL \
  --idempotency-key legacy-aapl-isolated-20260926

EQUITYLENS_API_URL=http://127.0.0.1:18000/api/v1 \
  equitylens onboarding rereview MSFT \
  --idempotency-key legacy-msft-isolated-20260926
```

本机配置了 HTTP 代理；第一次诊断探针未设置 `NO_PROXY`，状态查询在代理中超时，但服务端任务实际正常完成。之后本地 API 查询显式设置 `NO_PROXY=127.0.0.1,localhost`，不得把该诊断超时记为建档任务失败。

### AAPL

- onboarding：`fdbaff91-ff07-4ab0-9c4f-a31af16e50e6`
- revision/state/step：`7 / NEEDS_ADAPTATION / BUILD`
- base publication：`legacy-publication-0000320193-v1`
- fetch bundle：`62602633-4a09-4310-9fd8-973545952e29`
- profile：`f336ccc0-b76a-4348-9abd-b721dd4431e8`
- dataset：`edb11057-e156-43ba-aa63-056814ed8cc8`
- quality report：`3b9fe63c-924e-4db6-a476-f67b4844a889`
- review/publication：均为空，没有批准或切换。
- BLOCKER：`CASH.bridge / CASH_BRIDGE_INPUT_MISSING`、`LINEAGE.filing_context / FILING_CONTEXT_MISSING`、`SECURITY.identity / SECURITY_EVIDENCE_MISSING`、`SEGMENTS.reconciliation`。
- 演练后公司仍为 `LEGACY_UNREVIEWED`，active publication 仍为 `legacy-publication-0000320193-v1`，publication 数仍为 1。

### MSFT

- onboarding：`f66d3a30-622d-47ff-ab4b-4021dd0709c3`
- revision/state/step：`7 / NEEDS_ADAPTATION / BUILD`
- base publication：`legacy-publication-0000789019-v1`
- fetch bundle：`d46aede1-0063-4af6-a4da-6d1ff4b379fb`
- profile：`14db16ed-fe98-4455-9e5c-7f23708c3107`
- dataset：`44f59d92-c26e-4e02-b714-4786c172a2ec`
- quality report：`de8a7c5f-2e52-4b1b-9e6f-bff567b4cfbe`
- review/publication：均为空，没有批准或切换。
- BLOCKER：`CASH.bridge / CASH_BRIDGE_INPUT_MISSING`、`LINEAGE.filing_context / FILING_CONTEXT_MISSING`、`SECURITY.identity / SECURITY_EVIDENCE_MISSING`、`SEGMENTS.reconciliation`。
- 演练后公司仍为 `LEGACY_UNREVIEWED`，active publication 仍为 `legacy-publication-0000789019-v1`，publication 数仍为 1。

## 自动化验证

```text
.venv/bin/python -m pytest
436 passed, 1 warning in 124.29s

pnpm --dir apps/web exec tsc --noEmit
passed

pnpm --dir apps/web lint
passed

pnpm --dir apps/web build
passed

PLAYWRIGHT_CHROME_PATH=... pnpm --dir apps/web e2e
44 passed in 21.9s
```

唯一后端 warning 仍是 Starlette TestClient/httpx 的上游弃用提示。浏览器测试中对未启动真实 8000 API 的代理连接拒绝是确定性 mock 场景的预期日志，44 项测试全部通过。

## 最终整支审查

独立只读审查没有发现 Critical。两项 Important 已用 RED→GREEN 测试修复：`profile-import` CLI 现在强制并转发 API 所需的 `Idempotency-Key`；`rereview` 在 writer 事务内重新查询当前有效 ticker 别名，只允许唯一且仍指向原 security/company/基线的身份创建任务。新增聚焦回归为 `41 passed, 1 warning`，随后重新执行上述完整验证。

一项 Minor 暂缓：同一幂等键在目标公司资格状态或 active publication 已变化后，可能返回资格/基线错误而不是 `IDEMPOTENCY_CONFLICT`。当前路径仍然安全失败，不会创建或发布任务；后续若要稳定错误码契约，应把历史 key 检查提前并补充状态变化测试。

## 后续条件

只有补齐并复核以下证据后，才能从新任务重新构建并批准：现金桥完整输入、官方 filing/iXBRL 行级 context、证券身份原始证据、分部及抵销对账证据。不得复用本次失败质量报告的指纹，不得手工把报告改为 PASS，也不得绕过 active publication 冲突。两家公司都通过隔离验收前，不进入正式数据写入。
