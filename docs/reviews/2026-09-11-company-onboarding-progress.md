# 高质量公司建档开发进度

主文档：`docs/superpowers/plans/2026-09-11-company-onboarding.md`

状态：T01—T10 已按顺序执行；T10 可独立完成的实现、迁移演练、教程、审查与全量验证已完成，真实发布因官方 iXBRL 证据不可取得而保持阻塞。用户接受系统采集校验 + 维护者专属适配复核，要求顺序执行并逐阶段更新本文。

| 阶段 | 实现 | 验证 | 复核 | 证据/阻塞 |
|---|---|---|---|---|
| T01 身份注册与迁移 | 已完成 | 5 passed；真实库副本双次迁移通过 | 已自检 | `docs/reviews/2026-09-11-company-onboarding-pre-migration-inventory.md` |
| T02 发布版本隔离 | 已完成 | 5 passed；真实库副本双次迁移通过 | 已自检 | `docs/reviews/2026-09-11-company-onboarding-publication-rehearsal.md` |
| T03 持久化任务与写入 | 已完成 | 7 passed；T01—T03 回归 20 passed | 已自检 | writer 跨进程、恢复、取消、重试和真实刷新/估值互斥测试 |
| T04 发现采集与候选 | 已完成 | 12 passed；T01—T04 回归 29 passed | 已自检 | SEC 身份快照、历史分页、严格 profile 与候选反例 |
| T05 质量门槛 | 已完成 | 9 passed；T01—T05 回归 38 passed | 已自检 | 舍入区间、期间口径、规则调度及持久化报告反例 |
| T06 维护者复核闭环 | 已完成 | 6 passed；T01—T06 回归 47 passed | 已自检 | 固定审查包、旧批准失效、质量阻断、CLI API-only 与原子发布反例 |
| T07 API 与版本读取 | 已完成 | 7 passed；T01—T07 回归 54 passed | 已自检 | 幂等、分页、超期、歧义、publication 隔离、能力门禁及完整 API 闭环 |
| T08 估值门禁 | 已完成 | 6 passed；T01—T08 回归 66 passed；现有 API 56 passed | 已自检 | 确认指纹、模型/币种/ADR/股类门禁、证券行情隔离与旧运行保真 |
| T09 页面流程 | 已完成 | 6 个新增浏览器路径、18 个全量浏览器路径、类型和 lint 均通过 | 已自检并视觉巡检 | 动态公司目录、固定版本请求、防迟到覆盖、质量门禁、移动端与焦点恢复 |
| T10 真实接入及完整验收 | 可独立部分已完成 | 75 个聚焦测试、348 个全量后端测试、18 个浏览器测试通过；前端类型/lint/build 通过 | 三轮审查收口，无 Critical/Important 遗留 | KO/COST 缺官方 filing/iXBRL 行级 context 与分部证据，未批准、未发布；迁移演练和失败恢复通过 |

## 每阶段记录格式

阶段与提交号：
实际改动：
测试命令及结果：
证据文件/报告：
遗留问题与下一步：

不得将旧基线 251 个后端测试和 12 个浏览器测试的历史记录当作新功能已验证的证据。没有执行过的测试保持未运行。

## T01 身份注册与迁移

阶段与提交号：T01；提交在本阶段记录更新后创建。

实际改动：新增发行人/证券类型和事务型注册表；ticker 别名具有有效期且重叠被拒绝；歧义 ticker 返回 `AMBIGUOUS_SECURITY`；新增有序迁移、不可变 checksum、AAPL/MSFT 确定性证券种子和 `LEGACY_UNREVIEWED` 标记；新库 schema 同步加入身份表。

测试命令及结果：

- RED：`uv run pytest tests/integration/test_company_registry.py tests/integration/test_onboarding_migration.py -q`，因新增模块不存在而 collection 失败，符合未实现契约。
- GREEN：同一命令，`5 passed in 0.28s`。
- 真实库副本：第一次迁移应用 `[1]`、第二次 `[]`；原有 18 张表除空 `company` 加入两条种子外，行摘要无变化。

证据文件/报告：`docs/reviews/2026-09-11-company-onboarding-pre-migration-inventory.md`。

遗留问题与下一步：真实库保持只读、尚未切换行为；T02 建立固定 dataset/publication 版本并迁移 legacy publication。

## T02 固定数据版本和发布隔离

阶段与提交号：T02；提交在本阶段记录更新后创建。

实际改动：新增类型化 dataset 行、候选封存器、固定 `PublicationContext` 读取和原子发布事务；payload SHA-256、raw fact 引用、profile/company 归属与 publication 归属均在边界验证；迁移为 AAPL/MSFT 封存完整 legacy 行并保留 `LEGACY_UNREVIEWED`。

测试命令及结果：

- RED：`uv run pytest tests/integration/test_publication.py -q`，因 publication 包尚不存在而 collection 失败。
- GREEN：同一命令，`5 passed in 0.55s`。
- 回归组合：`uv run pytest tests/integration/test_publication.py tests/integration/test_onboarding_migration.py -q`，`7 passed in 0.57s`。
- 真实库副本：迁移 34.11 秒；第二次无操作；旧表除空 company 种子外摘要不变；分别封存 31,044/38,633 行。

证据文件/报告：`docs/reviews/2026-09-11-company-onboarding-publication-rehearsal.md`。

遗留问题与下一步：旧测试 fixture 在 schema 初始化后才写入事实，因此其 legacy publication 不自动包含后写数据；正式迁移对已有真实数据正确封存，T07 测试 fixture 将显式使用 publication 构建路径。T03 开始实现统一 writer 与持久化任务。

## T03 统一写入与持久化任务

阶段与提交号：T03；提交在本阶段记录更新后创建。

实际改动：新增进程级文件锁和可重入线程串行 writer；DuckDBStore、身份、dataset/publication、refresh、估值运行和估值方案写入统一经过该入口；新增持久化任务、证券关联、attempt、expected revision、取消边界、三次总尝试退避、中断恢复和 lifespan 执行器。

测试命令及结果：

- RED：`uv run pytest tests/integration/test_onboarding_runner.py -q`，因 onboarding 包尚不存在而 collection 失败。
- GREEN：同一命令，`7 passed in 0.61s`；覆盖完成步骤不重复、revision 冲突、同发行人任务复用、发布边界取消、三次重试上限、第二进程拒绝以及 refresh/valuation 实际写路径互斥。
- 回归：T01—T03 专属测试及 `tests/unit/test_replay_paths.py`，`20 passed in 1.46s`。
- API/刷新回归：`56 passed, 3 failed`；三项失败与开发前基线相同，均为 2026-09-03 行情 fixture 在当前日期被判 `STALE`，无新增失败。

证据文件/报告：`tests/integration/test_onboarding_runner.py`；知识库记录 `20260911233000`。

遗留问题与下一步：任务子表未声明指向高频可变 parent 的 DuckDB 外键，改由统一 writer 事务校验，原因和复现已记录。T04 接入真实发现、来源缓存和严格 profile。

## T04 真实发现、采集和专属候选

阶段与提交号：T04；提交在本阶段记录更新后创建。

实际改动：新增 ticker 输入校验、SEC registry/submissions 固定快照与 24 小时来源缓存、15 分钟持久化 discovery、创建前实时身份哈希复核、历史 submissions 文件分页、资格/模板判定和多股类候选；新增严格 data-only profile v1、safe YAML、确定性内容哈希、iXBRL locator 目录和只基于已出现 concept 的候选生成。

测试命令及结果：

- RED：`uv run pytest tests/unit/test_issuer_profile.py tests/integration/test_company_discovery.py -q`，两个新增包不存在而 collection 失败。
- GREEN：同一命令，`12 passed in 0.42s`。
- T01—T04 回归组合：`29 passed in 1.84s`。

证据文件/报告：`tests/unit/test_issuer_profile.py`、`tests/integration/test_company_discovery.py`、`config/issuers/schema-v1.json`。

遗留问题与下一步：默认 SEC 网络发现要求配置真实 `EQUITYLENS_USER_AGENT` 联系方式，拒绝示例占位地址；自动候选始终为 `NEEDS_ADAPTATION`。T05 实现质量报告和强制规则。

## T05 质量规则和可解释报告

阶段与提交号：T05；提交在本阶段记录更新后创建。

实际改动：新增检查状态/严重度模型、基于 XBRL decimals 的舍入区间、资产负债勾稽、同定义现金桥、同财年/同 restatement set 季度差分、显式 EPS 方法、分部抵销、期间覆盖与 N/A 证据规则；QualityEngine 调度第 7 节规则族并持久化固定指纹报告及逐项证据。

测试命令及结果：

- RED：`uv run pytest tests/unit/test_onboarding_quality.py -q`，因 quality 包不存在而 collection 失败。
- GREEN：同一命令，`9 passed in 0.19s`。
- T01—T05 回归组合：`38 passed in 1.87s`。

证据文件/报告：`tests/unit/test_onboarding_quality.py`、`config/quality/us_gaap_operating_v1.yaml`。

遗留问题与下一步：缺必需输入、未知精度、未证明 EPS 方法和不支持模板均保持 BLOCKER，不做运行时降级；真实发行人可能因此在 T10 保留阻塞。T06 实现审查包、复核指纹与发布闭环。

## T06 维护者复核和发布闭环

阶段与提交号：T06；提交在本阶段记录更新后创建。

实际改动：新增 onboarding 候选产物指针 migration、完整 profile 导入与旧候选失效、固定审查包及安全 raw locator、批准/拒绝留痕和精确候选指纹；质量未通过时批准和发布均被阻断，任务 revision/取消/候选在 publication 指针切换事务内重验并原子转为 PUBLISHED。新增 OnboardingService 及 `onboarding` CLI 子命令组，维护者读写只调用本地 API，连接失败不旁路写 DuckDB。

测试命令及结果：

- RED：`uv run pytest tests/integration/test_issuer_review.py -q`，因 `equitylens.issuers.review` 尚不存在而 collection 失败。
- GREEN：同一命令，`6 passed in 0.53s`；覆盖旧批准失效、质量失败阻断、任意路径不导出、精确候选自动发布、profile 导入失效旧候选和 CLI 审查请求。
- T01—T06 回归组合及 replay 路径：`47 passed in 2.44s`。
- 静态核验：`uv run python -m compileall -q equitylens` 与 `git diff --check` 均通过。

证据文件/报告：`tests/integration/test_issuer_review.py`。

遗留问题与下一步：CLI 已固定使用第 9 节 API 契约，实际 HTTP 路由将在 T07 接入；T07 同时补齐持久化幂等并把所有正式读取绑定 publication/security 标识。

## T07 API 和固定版本读取

阶段与提交号：T07；提交在本阶段记录更新后创建。

实际改动：新增公司列表、发现、申请、任务列表/详情、重试、取消、审查包、profile 导入、复核和已发布质量报告 API；`Idempotency-Key` 持久化请求哈希，相同键不同输入返回冲突。正式公司读取解析注册表 security，接受固定 publication，响应携带 company/security/publication 标识；事实读取直接来自封存 dataset，跨公司 publication 被拒绝，请求期间 active pointer 切换不改变已捕获上下文。发布写入核心能力状态，缺事实或分部披露时分析入口被后端阻断。旧采集、分部、管理层、行情、刷新与 CLI 的公司解析均改为使用注入数据库注册表，歧义 ticker 必须传 security_id。

测试命令及结果：

- RED：`uv run pytest tests/integration/test_onboarding_api.py -q`，因 `equitylens.api.company_routes` 尚不存在而 collection 失败。
- GREEN：同一命令，`7 passed in 1.02s`；覆盖持久化幂等、同键异参、过期 discovery、分页、取消终态、歧义 ticker、profile/复核/质量 API、能力门禁、候选隔离、跨公司 publication 和读取期间发布切换。
- T01—T07 回归组合及 replay 路径：`54 passed in 3.45s`。
- 现有完整 API：`53 passed, 3 failed`；失败仍是开发前已记录的 2026-09-03 行情 fixture 随当前日期变为 `STALE`，无新增失败。
- 静态核验：`uv run python -m compileall -q equitylens` 与 `git diff --check` 均通过。

证据文件/报告：`tests/integration/test_onboarding_api.py`。

遗留问题与下一步：迁移前创建、随后才注入 legacy facts 的测试/开发库保留显式 `legacy` 兼容读取；正式已迁移 dataset 不走该分支。T08 将修复时间相关行情 fixture，并把估值确认绑定 security/publication/模型与假设指纹。

## T08 估值门禁和证券指纹

阶段与提交号：T08；提交在本阶段记录更新后创建。

实际改动：新增 valuation identity migration，将假设确认、估值运行、参考价计划和行情分别绑定 security/publication/model/assumptions 指纹；新增 valuation-profile API，草稿只校验，正式预览、反向 DCF 和保存运行均要求同一固定版本的已确认假设。后端阻断不适用模型、财务数据缺失、财报/报价币种不一致、未知 ADR 比例，以及未证明证券级股数口径的多股类估值。行情记录和读取按 security_id 隔离；新 publication 只把旧计划标为待复核，不改写历史运行，复制计划继承该状态。

测试命令及结果：

- RED：`uv run pytest tests/integration/test_onboarding_valuation.py -q`，`4 failed`，分别暴露未确认请求 500、valuation-profile 不存在和行情表缺 security_id。
- GREEN：同一命令，`6 passed in 1.05s`；覆盖未确认门禁、完整确认、publication 失效、反向 DCF、币种、ADR、多股类股数口径、证券行情隔离、计划待复核传播及历史运行字节级不变。
- T01—T08 专项回归：`66 passed in 4.35s`。
- 现有完整 API：通过可注入 UTC 时钟固定行情夹具语义后，`56 passed in 44.78s`；生产仍按真实观察时间判断过期。
- 静态核验：`uv run python -m compileall -q equitylens` 与 `git diff --check` 均通过。

证据文件/报告：`tests/integration/test_onboarding_valuation.py`、`spec/openapi_stub.yaml`。

遗留问题与下一步：legacy AAPL/MSFT 在完成 T10 新标准复核前保留原估值兼容入口；一旦质量状态升级，和新增证券一样要求显式确认。T09 将在页面展示这些门禁状态和确认入口。

## T09 页面申请与质量报告

阶段与提交号：T09；提交在本阶段记录更新后创建。

实际改动：移除前端硬编码公司目录和静默 fallback，页面只展示已发布公司并将 security/publication 固定绑定到所有正式读取；新增添加公司、建档中心、任务详情和质量报告四个组件，支持发现、幂等申请、两档可见性轮询、取消/重试、审查包、revision/fingerprint 复核及发布后刷新。请求使用 AbortController 和序列号隔离迟到响应；估值区显式展示待配置或数据阻断。补齐键盘焦点、Escape、重复提交保护、移动端操作区与现有浏览器 fixture。

测试命令及结果：

- RED：新增建档浏览器路径在页面仍使用硬编码目录且缺少“添加公司”入口时失败，符合未实现契约。
- 新增路径：`PLAYWRIGHT_CHROME_PATH='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' pnpm exec playwright test e2e/company-onboarding.spec.ts --project=chromium`，`6 passed`。
- 浏览器全量：同一 Chrome 配置执行 `pnpm exec playwright test --project=chromium`，`18 passed in 18.1s`；覆盖发布前后目录、重复提交、Escape/焦点恢复、质量阻断、迟到响应、移动端和估值配置门禁。
- 静态核验：`pnpm exec tsc --noEmit && pnpm lint` 通过。
- API 回归：`uv run pytest tests/integration/test_onboarding_api.py -q`，`7 passed`。
- 独立视觉巡检：Python Playwright 启动真实 Next.js 页面并等待 mock API 稳定后截取桌面/移动端；弹窗 `scrollWidth=clientWidth=372`，无横向溢出，移动端主要操作完整可见。

证据文件/报告：`apps/web/e2e/company-onboarding.spec.ts`、`/tmp/equitylens-onboarding-desktop.png`、`/tmp/equitylens-onboarding-mobile.png`。

遗留问题与下一步：浏览器路径使用确定性 API fixture，不能替代 T10 真实后端隔离库在线验收；T10 将固定官方来源快照、逐发行人 golden、迁移恢复演练并完成教程。

## T10 真实发行人接入、迁移验收与教程

阶段与提交号：T10；提交在本阶段记录更新后创建，目标提交信息 `test: verify issuer onboarding end to end`。

实际改动：固定 KO/COST 官方 submissions 与 Company Facts 快照及人工转录预期，新增 KO/COST profile v1、AAPL/MSFT profile v2、四发行人 golden 和真实 FETCH→BUILD→VALIDATE→PUBLISH 持久化流水线；profile concept 白名单、来源哈希绑定、同申报版本派生、同期间质量检查、适用性专属证据、证券双向一致性和分代重试预算均在生产路径强制执行。审查批准只原子转入 `PUBLISHING`，持久化执行器是唯一 publisher。新增用户/维护者教程和真实接入记录。

测试命令及结果：

- RED：KO/COST 初始 golden 暴露映射与派生 lineage 缺口；生产流水线、失败边界、版本化重试预算和额外活跃股类均先由失败测试复现。
- 聚焦回归：`uv run pytest tests/integration/test_onboarding_runner.py tests/integration/test_onboarding_pipeline.py tests/integration/test_issuer_review.py tests/integration/test_onboarding_api.py tests/unit/test_issuer_profile.py tests/unit/test_onboarding_quality.py tests/golden/test_onboarding_issuers.py -q`，`75 passed, 1 warning in 65.49s`。
- 冻结依赖与后端全量：`uv sync --frozen` 通过；`uv run pytest -q`，`348 passed, 1 warning in 121.75s`。唯一 warning 为 Starlette TestClient 对 httpx 的上游弃用提示。
- 前端：`pnpm --dir apps/web install --frozen-lockfile`、`pnpm --dir apps/web exec tsc --noEmit`、`pnpm --dir apps/web lint`、`pnpm --dir apps/web build` 均通过。
- 浏览器：`PLAYWRIGHT_CHROME_PATH='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' pnpm --dir apps/web e2e`，`18 passed in 18.1s`。
- 静态核验：`uv run python -m compileall -q equitylens` 与 `git diff --check` 通过。

证据文件/报告：`tests/fixtures/onboarding/`、`tests/golden/test_onboarding_issuers.py`、`docs/reviews/2026-09-12-company-onboarding-live-validation.md`；隔离在线验收截图 `/tmp/equitylens-onboarding-live.png`；迁移报告 `/Users/vincent/.local/share/equitylens-migration-rehearsal/20260912T090430Z/report.json` 与 `failure-recovery.json`。正式数据库和 raw 未写入。

复核：三轮代码审查逐项修复 profile/来源绑定、候选竞态、年度期间、派生 accession、durable publish、共享 SEC 限流、适用性证据、核心 filing context、版本化重试与多股类双向一致性；最终复核无 Critical/Important 遗留。

遗留问题与下一步：KO/COST 的 Company Facts 足以独立验证核心数值，但没有真实 filing/iXBRL 行级 context/locator 或分部维度；当前环境获取 SEC Archives 文档为 403。因此质量明确保留 `LINEAGE.filing_context` 和 `SEGMENTS.reconciliation` BLOCKER，两家公司未批准、未发布。AAPL/MSFT 保留 `LEGACY_UNREVIEWED`。取得并固定官方 iXBRL 后必须生成新候选、重跑质量并重新审查，不能沿用旧指纹或手工置为 PASS。
