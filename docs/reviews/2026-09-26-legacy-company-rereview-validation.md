# AAPL/MSFT 旧版公司新标准复核验收

日期：2026-09-26（最后更新：2026-09-30）

结论：复核入口、幂等任务、旧发布基线、质量门禁和页面身份展示均已实现并通过自动化验证。首次隔离复核正确暴露四项 BLOCKER；补齐 profile v2 filing 证据、现金桥、证券和分部配置并修复 iXBRL 单位引用解析后，AAPL 与 MSFT 在隔离库及完整 API 副本中均达到 `PASS`/0 BLOCKER。正式写入前完成无 writer 检查和数据备份，随后顺序将两家公司发布为 `VERIFIED`，且保留旧 publication 作为基线。T10 合并项仍未完成，仅因 KO/COST 尚未完成同等的真实 filing 复核与发布。

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

## 2026-09-30 证据适配复验

新增 AAPL/MSFT profile v3（schema v2）后，以此前真实 FETCH 固定的完整 3×10-K + 8×10-Q bundle 在全新临时 DuckDB 重建并运行同一生产质量引擎。AAPL 与 MSFT 均得到 `PASS`、0 BLOCKER；原 `CASH_BRIDGE_INPUT_MISSING`、`FILING_CONTEXT_MISSING`、`SECURITY_EVIDENCE_MISSING` 和 `SEGMENTS.reconciliation` 阻断全部消失。MSFT 暴露并以 RED→GREEN 修复了 iXBRL 任意 unit ID 未解析 `<xbrli:unit>` 声明的问题。临时验收目录为 `/tmp/equitylens-rereview-full-v3.DOtNnY`，聚焦回归为 `75 passed in 68.90s`。

本节更新只证明 profile、解析器和质量规则已满足发布前数据门禁；尚未执行复核批准或正式 publication 切换。后续仍须先在正式库副本走完整 API/审核/发布链，再按备份和 writer 检查流程处理正式数据。

### 完整 API 演练与正式发布

在正式库副本 `/tmp/equitylens-rereview-api-v3.Pg5EVk` 上，AAPL 和 MSFT 均完成真实 FETCH、当前哈希 profile v4 导入、BUILD、VALIDATE、审查批准与 PUBLISH，任务最终均为 `PUBLISHED`。SEC 当前字节哈希与旧快照不同，系统先以 `ADAPTATION_REQUIRED` 安全暂停；fact catalog 和全部 locator 核对一致后才创建新版本配置，未修改旧版本。

正式写入前没有 writer，且数据库/raw 已备份到 `/Users/vincent/.local/share/equitylens-backups/20260930T023000Z-aapl-msft-rereview/`。数据库来源与备份 SHA-256 均为 `5eaa4a8626ef4a0da29d875bef4831d1d3637d88f884540f09a76dacb433cc1c`；181 个 raw 文件清单哈希均为 `c18cc29330b66dacb8560d5fb33c17432fa9d01c8980a677de8234383077da31`。

- AAPL：任务 `c55d43bc-097c-4bb9-8ad1-d4a28821784d`，quality `2cbb670a-3df5-46dc-b007-dc6eb1b4bb33` 为 PASS，新 publication `1d3d7c88-60c3-4195-913a-70a323543741`。
- MSFT：任务 `cf06bf00-77cc-4825-ac20-3fad7dda3cb5`，quality `41b8b565-c987-4ab9-8cb5-ef73774b3e8b` 为 PASS，新 publication `0805471a-f420-4473-815c-631814cb9c72`。

发布后两家公司均为 `VERIFIED`；目录、overview 与 freshness 接口均返回成功并固定到新 publication。完整后端验证 `439 passed, 1 warning in 127.43s`，聚焦回归 `48 passed in 57.85s`。AAPL/MSFT 的旧版公司新标准复核至此完成。

### 提交前审查补强与 profile v5

独立只读审查无 Critical，但发现两项 Important：v4 的官方 filing 原文只存在本机 raw，clean checkout 无法复核哈希与 XPath；证券身份复用了 locator `/` 的整文档证据，没有精确证明 ticker、交易所和股类。修复后，BUILD 会对不可变 bundle 中的每个 profile XPath 做实际解析，并对证券证据文本执行 ticker/交易所/股类声明校验；XPath 必须返回非空元素节点集，metric evidence 节点还必须声明对应的配置 concept。错误、标量或语义无关的 locator 均停在 `NEEDS_ADAPTATION`，不能进入质量 PASS。仓库固定 AAPL/MSFT 各自完整 3×10-K + 8×10-Q bundle 以及 submissions、Company Facts/history 字节，clean checkout 自动化会解压、逐文档验 SHA-256、实际 BUILD 并重跑质量引擎，两家都必须 PASS/0 BLOCKER。单位解析回归也补齐 divide `USD/shares`、`fact_catalog()` 和残缺声明回退。

已发布的 v4 保持不可变；新证据用 profile v5 表达。为支持已验证公司的后续 profile/规则升级，版本化复核入口现允许 `VERIFIED` 公司从当前 active publication 建立新基线任务，仍保留事务内身份重验和发布冲突保护。正式写入前再次确认无 writer，并备份到 `/Users/vincent/.local/share/equitylens-backups/20260930T025500Z-aapl-msft-v5/`；来源与备份数据库 SHA-256 均为 `de79602f7089310446eae2bab67af424a5c2595ff58993f0cff0923ce4a83ed0`。

- AAPL：任务 `3e4fb2e4-ba77-4a0f-b083-e5540608f711`，quality `f52b560b-09f7-468d-b58a-1be52d6fddc5` 为 PASS/0 BLOCKER，publication `2a09e38d-c8f5-4a46-8e52-076b322c8da2`。
- MSFT：任务 `05777c34-886e-4f23-8f18-4d9c5781b1f4`，quality `09922413-187b-4bd5-9af3-9bd36ea987c2` 为 PASS/0 BLOCKER，publication `cfaea199-58c8-42cc-a3d9-f47028d7bff3`。

两个任务均从各自 v4 publication 建立基线并完成 FETCH→BUILD→VALIDATE→review→PUBLISH，最终仍为 `VERIFIED`；overview 和 freshness 在线读取均返回 200。

修复涉及的全量后端回归为 `442 passed, 1 warning in 133.44s`，唯一 warning 为既有 Starlette TestClient/httpx 弃用提示；`git diff --check` 通过。
