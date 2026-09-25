# 高质量公司建档开发进度

主文档：`docs/superpowers/plans/2026-09-11-company-onboarding.md`

状态：T01—T10 已按顺序执行；当时 KO/COST 官方 iXBRL 证据不可取得，真实发布未冒进。扩展 C01—C10 已按顺序开发；C10 先在独立数据库完成真实 NVDA SEC iXBRL→审核→质量 PASS→原子发布，再备份、迁移正式库并对旧 NVDA 任务重新抓取、适配、审核和发布。用户接受系统采集校验 + 维护者专属适配复核，要求顺序执行并逐阶段更新本文。

扩展计划：`docs/superpowers/plans/2026-09-19-company-onboarding-closure.md`。C01—C10 用于补齐真实发行人固定证据、适配工作台、全局进度和 NVDA 发布闭环。

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
| C01 不可变 FETCH 持久化 | 已完成 | RED 2 failed；GREEN 2 passed；聚焦回归 13 passed；compileall/diff-check 通过 | 已自检 | migration v7、任务 bundle/candidate 指针、不可变 bundle/document、candidate/event/idempotency 表 |
| C02 固定 SEC 申报包 | 已完成 | RED 覆盖缺模块/未绑定 bundle/缺 history/SHA 错误；GREEN 聚焦 14 passed | 已自检 | 3 年 10-K、8 季 10-Q、适用修订及主文档均按 attempt as-of 固定 |
| C03 Profile v2 与申报证据 | 已完成 | RED 覆盖缺 v2、bundle 证据、locator 和 profile 分部配置；GREEN 聚焦 31 passed | 已自检 | v1 只读兼容；v2 BUILD 只用固定 iXBRL 生成正式事实 |
| C04 确定性候选制品 | 已完成 | RED 缺候选构建接口；GREEN 聚焦 25 passed，兼容回归 13 passed | 已自检 | 候选、暂停、revision 与事件原子提交；永不自动批准 |
| C05 严格 YAML 与原子恢复 | 已完成 | RED 覆盖严格解析/事务冲突；GREEN 44 passed，扩展流水线回归合计 55 passed | 已自检 | v2-only、证据绑定、版本单调、幂等重放与回滚均已验证 |
| C06 候选/导入/refetch API | 已完成 | RED 旧接口缺新端点/严格约束；GREEN 14 passed，OpenAPI 5 路径核验通过 | 已自检 | GET 无副作用；YAML/JSON 同一原子导入；refetch 指针规则已覆盖 |
| C07 统一进度与 attention | 已完成 | RED 缺 progress 模块；GREEN 41 passed | 已自检 | 五阶段、45 秒停滞、取消快照、数据库精确计数已覆盖 |
| C08 五阶段与适配工作台 | 已完成 | RED 无进度条；GREEN 17 浏览器测试，type/lint 通过 | 已自检 | 候选审查、证据、下载、上传边界和无刷新恢复已覆盖 |
| C09 全局任务入口 | 已完成 | 21 个全量浏览器路径、类型/lint/build 通过 | 已自检 | 精确计数、刷新恢复、终态消失与最近任务恢复均已覆盖 |
| C10 NVDA 真实闭环 | 已完成（独立验收库及正式库） | 412 个全量后端、37 个浏览器测试通过；正式库真实浏览器与 SEC 溯源检查 | 独立代码审查发现均已修复，v3 证据补入 golden | `docs/reviews/2026-09-19-company-onboarding-closure-validation.md`；正式任务 5/5 已发布 |

## C01 不可变 FETCH 持久化

阶段与提交号：C01；提交在本阶段记录更新后创建。

实际改动：新增 migration v7，为任务增加 `fetch_bundle_id`、`profile_candidate_id`；新增不可变 bundle/document、候选、追加事件及 Profile 导入幂等表。repository 新增严格类型化 bundle 写入/读取和事件读取；bundle、任务指针、revision 与激活事件在同一 writer 事务提交，相同输入重放不增 revision，旧 revision 不可覆盖。

测试命令及结果：

- RED：两个新增用例 `2 failed`，分别确认迁移仅到 v6，以及 `create_fetch_bundle` 缺失。
- GREEN：两个新增用例 `2 passed in 0.27s`。
- 聚焦回归：`uv run pytest tests/integration/test_onboarding_migration.py tests/integration/test_onboarding_runner.py -q`，`13 passed in 1.05s`。
- 静态核验：`uv run python -m compileall -q equitylens` 与 `git diff --check` 通过。

证据文件/报告：`tests/integration/test_onboarding_migration.py`、`tests/integration/test_onboarding_runner.py`。

遗留问题与下一步：C01 仅建立持久化原语；C02 将实现确定性的 recent/history 合并、3 年/8 季/修订选择、主文档下载和完整 bundle 激活，流水线在 C02 前尚未调用新 bundle API。

## C02 固定 SEC 申报包

阶段与提交号：C02；提交在本阶段记录更新后创建。

实际改动：新增 `fetch_bundle` 选择/读取模块，确定性合并 submissions recent 与全部声明 history；按 FETCH attempt 开始时间过滤未来申报，选择最近 3 个不同 10-K 年度 report date、8 个不同 10-Q 季度 report date和相同口径修订。FETCH 同时固定 submissions、Company Facts、history 和每份 primary document 的来源、日期、SHA 与 raw-store 相对 locator，全部成功后才原子绑定 bundle。固定文档读取拒绝目录逃逸、缺文件及 SHA 不匹配。

测试命令及结果：

- RED：先后确认选择模块缺失、history 合并接口缺失、流水线未绑定 bundle，以及固定文档 SHA 校验缺失。
- GREEN：`uv run pytest tests/unit/test_onboarding_fetch_bundle.py tests/integration/test_onboarding_pipeline.py -q`，`14 passed in 1.38s`。
- 测试证明更新 raw-store 的 latest submissions 指针后，任务 bundle ID、内容哈希与已固定文档身份保持不变。
- 静态核验：`uv run python -m compileall -q equitylens` 与 `git diff --check` 通过。

证据文件/报告：`tests/unit/test_onboarding_fetch_bundle.py`、`tests/integration/test_onboarding_pipeline.py`。

遗留问题与下一步：C02 固定了 iXBRL 主文档但 BUILD 尚未将其解析为正式 lineage/segment 证据；C03 将增加 Profile v2 严格模型，并把 required metrics 从 bundle 主文档解析而不是由 Company Facts 冒充来源。

## C03 Profile v2 与申报证据

阶段与提交号：C03；提交在本阶段记录更新后创建。

实际改动：新增严格 Profile v2 模型及 JSON Schema，覆盖模板、财年、每个 metric、现金债务、EPS、证券、适用性和声明式分部 parser 的证据引用及条件约束；证据必须匹配当前 bundle 的 document ID 与 SHA。iXBRL 数值事实保留真实 context ID、XPath locator 和维度；分部配置从审核 Profile 构造。BUILD 对 v2 只按 bundle 相对 locator/SHA 读取申报主文档并生成 formal raw/canonical/segment facts；Company Facts 仅保留发现/交叉检查身份，不再冒充 filing lineage。v1 历史 Profile 保持原读取路径。

测试命令及结果：

- RED：分别确认 `IssuerProfileV2`、bundle evidence validator、iXBRL locator、profile segment config 与 profiled iXBRL normalization 缺失。
- GREEN：`uv run pytest tests/unit/test_issuer_profile.py tests/integration/test_onboarding_pipeline.py tests/golden/test_golden_segments.py -q`，`31 passed in 1.82s`。
- v2 集成反例把 Company Facts revenue 设为 999、申报 iXBRL revenue 设为 100；sealed dataset 只出现 100，且每条 raw fact 均带 `context_id=ctx`、真实 XPath 和 filing source document。
- 静态核验：`uv run python -m compileall -q equitylens` 与 `git diff --check` 通过。

证据文件/报告：`config/issuers/schema-v2.json`、`tests/unit/test_issuer_profile.py`、`tests/integration/test_onboarding_pipeline.py`、`tests/golden/test_golden_segments.py`。

遗留问题与下一步：Profile v2 当前只能由已有文件或低层 repository 绑定；C04 将生成完整、可审查但不可直接构建的候选制品，并在无审核 Profile 时原子绑定候选后暂停。

## C04 确定性候选制品

阶段与提交号：C04；提交在本阶段记录更新后创建。

实际改动：候选生成器仅使用当前任务固定 bundle、版本化通用映射、任务证券身份与固定申报 iXBRL catalog，输出完整 Profile v2 字段骨架。无法确定的标量保留 `null`、集合保留空集合，并以 `unresolved_fields` 的字段路径、原因、建议操作和 YAML 注释同时呈现。候选输入哈希覆盖 bundle、生成器、映射版本/内容和 schema 版本；内容/YAML 哈希均确定。BUILD 缺审核 Profile 时，repository 在同一事务中插入或复用不可变候选、绑定指针、暂停 attempt、进入 `NEEDS_ADAPTATION`、递增 revision 并写入 `PROFILE_CANDIDATE_CREATED` 事件。候选始终标为待适配，不能自动进入构建或批准。

测试命令及结果：

- RED：候选构建接口不存在，目标测试在收集阶段失败。
- GREEN：`uv run pytest tests/unit/test_issuer_profile.py tests/integration/test_onboarding_pipeline.py -q`，`25 passed in 1.72s`。
- 兼容回归：`uv run pytest tests/integration/test_onboarding_runner.py tests/integration/test_onboarding_migration.py -q`，`13 passed in 1.09s`。
- 静态核验：`uv run python -m compileall -q equitylens` 与 `git diff --check` 通过。

证据文件/报告：`equitylens/issuers/candidate.py`、`equitylens/onboarding/repository.py`、`equitylens/onboarding/runner.py`、`equitylens/onboarding/pipeline.py`、`tests/unit/test_issuer_profile.py`、`tests/integration/test_onboarding_pipeline.py`。

遗留问题与下一步：候选目前已经可追踪但尚无严格的网页 YAML 导入恢复事务；C05 将实现受限 YAML loader、幂等导入和单事务恢复 BUILD。

## C05 严格 YAML 与原子恢复

阶段与提交号：C05；提交在本阶段记录更新后创建。

实际改动：新增 512 KiB/深度 20/节点 20,000/scalar 64 KiB 上限的严格 SafeLoader，拒绝多文档、重复键、非字符串键、merge、anchor、alias、显式 tag、候选占位和 v1 新导入。Profile YAML 导入在单写者事务内先处理幂等重放，再校验 revision/state/CIK/当前 bundle 证据/版本单调性，随后一次性创建不可变 Profile、清空候选和下游指针、将旧 BUILD/VALIDATE/PUBLISH attempt 标为 STALE、恢复 `BUILDING/BUILD`、清除错误与定时器、写入 `PROFILE_IMPORTED`/`TASK_RESUMED` 事件并保存完整成功响应。失败不占用幂等键，事件写入异常会回滚全部变更。

测试命令及结果：

- RED：严格 YAML 限制与旧 v1 导入兼容用例暴露缺少新 loader/原子服务。
- GREEN：`uv run pytest tests/unit/test_issuer_profile.py tests/integration/test_issuer_review.py tests/integration/test_onboarding_runner.py -q`，`44 passed in 2.73s`；导入提交后 wake 回调已验证。
- 扩展流水线回归：加入 `tests/integration/test_onboarding_pipeline.py` 后，`55 passed in 3.88s`。
- 静态核验：`uv run python -m compileall -q equitylens` 与 `git diff --check` 通过。

证据文件/报告：`equitylens/issuers/yaml_loader.py`、`equitylens/issuers/profile.py`、`equitylens/onboarding/repository.py`、`tests/unit/test_issuer_profile.py`、`tests/integration/test_issuer_review.py`、`tests/integration/test_onboarding_runner.py`、`tests/integration/test_onboarding_pipeline.py`。

遗留问题与下一步：底层事务已完成，网页尚无候选读取/下载、YAML 上传和显式 refetch 接口；C06 将统一接入 API、稳定错误体和提交后 executor wake。

## C06 候选、导入与 refetch API

阶段与提交号：C06；提交在本阶段记录更新后创建。

实际改动：新增候选生成/读取/YAML 下载、当前审核 Profile YAML 下载、严格 YAML 导入和受控 refetch 端点；现有 JSON Profile 接口也要求 v2、幂等键并复用同一原子事务。候选 GET/下载不修改 revision，快照只返回相对 locator；重复生成相同输入复用候选且不递增 revision。错误体统一包含 `code/message/remediation/field_errors`，不回显 YAML、绝对路径或环境信息。refetch 仅在后端 `actions` 明确包含 `REFETCH` 时允许，提交后 wake executor；新 bundle 激活前保留历史诊断指针，成功激活后原子清空旧候选、Profile 和下游制品。步骤输入哈希加入 bundle/candidate 身份，防止 refetch 被旧完成 attempt 跳过。

测试命令及结果：

- RED：旧 API 缺少候选/YAML/refetch 路径，旧 JSON 导入也不满足 v2/幂等/固定证据要求。
- GREEN：`uv run pytest tests/integration/test_onboarding_api.py -q`，`14 passed, 1 warning in 2.10s`。
- 扩展回归：API、pipeline、runner 合计 `35 passed, 1 warning in 4.50s`。
- OpenAPI 运行时检查：5 个新增路径均存在；`spec/openapi_stub.yaml` 同步。
- 静态核验：`uv run python -m compileall -q equitylens` 与 `git diff --check` 通过。

证据文件/报告：`equitylens/api/company_routes.py`、`equitylens/api/company_schemas.py`、`equitylens/onboarding/service.py`、`equitylens/onboarding/repository.py`、`equitylens/onboarding/pipeline.py`、`spec/openapi_stub.yaml`、`tests/integration/test_onboarding_api.py`。

遗留问题与下一步：接口已具备工作台所需数据，但任务详情仍缺统一五阶段进度、心跳停滞判断和不受分页限制的待关注总数；C07 将补齐这些派生字段。

## C07 统一进度、心跳与待关注计数

阶段与提交号：C07；提交在本阶段记录更新后创建。

实际改动：新增后端唯一五阶段进度模型 `IDENTITY/FETCH/ADAPTATION/BUILD_VALIDATE/REVIEW_PUBLISH`，统一派生 completed、percent、当前阶段、activity、actor、阶段时间戳、停滞和 fingerprint。`NEEDS_ADAPTATION` 固定为完成 2/5（40%）并显示等待维护者；FAILED 根据 current step 与是否已有 Profile 精确落段。runner 在 handler 执行期间按 10 秒更新 attempt heartbeat，连续 45 秒无心跳才标记 stalled。取消事务把取消前完整 progress 存入 `TASK_CANCELLED` 事件，终态从该快照恢复。列表/详情复用同一派生器；`attention_only` 返回分页 items，同时用独立 `COUNT(*)` 返回不受 limit 影响的 `attention_count`。

测试命令及结果：

- RED：`tests/unit/test_onboarding_progress.py` 因 progress 模块不存在而在收集阶段失败。
- GREEN：`uv run pytest tests/unit/test_onboarding_progress.py tests/integration/test_onboarding_runner.py tests/integration/test_onboarding_api.py -q`，`41 passed, 1 warning in 3.39s`。
- 表驱动覆盖正常态、全部 FAILED 映射、角色/activity、心跳 fingerprint、45 秒边界、取消快照和分页外精确计数。
- 静态核验：`uv run python -m compileall -q equitylens` 与 `git diff --check` 通过。

证据文件/报告：`equitylens/onboarding/progress.py`、`equitylens/onboarding/models.py`、`equitylens/onboarding/repository.py`、`equitylens/onboarding/runner.py`、`equitylens/api/company_routes.py`、`tests/unit/test_onboarding_progress.py`、`tests/integration/test_onboarding_runner.py`、`tests/integration/test_onboarding_api.py`。

遗留问题与下一步：后端现已提供工作台所需的权威状态和制品接口；C08 将把它们接入五阶段进度条、候选审查、下载、上传错误与 refetch 操作。

## C08 五阶段与适配工作台

阶段与提交号：C08；提交在本阶段记录更新后创建。

实际改动：新增可访问的五阶段进度组件，严格按后端 progress 渲染：完成段绿色、当前/未完成段红色、未来段灰色，并同时提供图标、文字和 aria 状态。新增发行人适配工作台，可查看候选覆盖摘要、未解决字段、固定快照和逐项证据，下载候选/当前 Profile YAML，选择文件后显示名称与字节数，并在浏览器端阻止空文件和超过 512 KiB 的文件。一次文件选择只生成一个幂等键，服务端字段错误按路径展示；成功导入立即用响应替换任务并只在真实 RUNNING/QUEUED activity 下恢复轮询，无需手动刷新。`REFETCH` 仅按后端 actions 显示。

测试命令及结果：

- RED：新增浏览器用例找不到“建档总进度” progressbar。
- GREEN：隔离端口运行 `company-onboarding.spec.ts`，`17 passed in 18.2s`；核心适配用例覆盖 40% 暂停、证据展开、空/超限文件、字段错误、幂等重试和成功后立即切换 60%。
- `pnpm --dir apps/web exec tsc --noEmit` 与 `pnpm --dir apps/web lint` 通过。
- 为避免复用主工作区旧的 3000 端口服务，Playwright 配置新增 `PLAYWRIGHT_PORT`，本阶段在 3011 隔离端口验证。

证据文件/报告：`apps/web/src/components/companies/OnboardingProgress.tsx`、`apps/web/src/components/companies/ProfileWorkbench.tsx`、`apps/web/src/components/companies/OnboardingDetail.tsx`、`apps/web/src/lib/types.ts`、`apps/web/src/lib/api.ts`、`apps/web/e2e/company-onboarding.spec.ts`。

遗留问题与下一步：建档中心内部已完整可用，但关闭弹窗后仍缺持续可见的全局待关注入口；C09 将在页面右下角增加最上层感叹号入口，并验证刷新恢复与精确计数。

## C09 全局任务入口与刷新恢复

阶段与提交号：C09；提交在本阶段记录更新后创建。

实际改动：页面右下角新增固定于最上层的红色感叹号入口，数字严格使用后端不受分页限制的 `attention_count`。入口在首次加载、窗口重新获得焦点及建档任务发生变更时刷新；仅当任务 activity 为 `QUEUED` 或 `RUNNING` 时快速轮询，等待维护者、失败、取消和完成状态不伪装为后台仍在工作。最近打开的任务 ID 写入 localStorage，刷新页面或重新打开建档中心时直接恢复该任务；任务全部进入终态后入口自动消失。全局入口加载失败保持静默，建档中心仍保留详细错误与重试能力。

测试命令及结果：

- RED：新增全局入口用例在组件不存在时失败。
- GREEN：隔离端口 3011、单 worker 运行 `company-onboarding.spec.ts` 与 `research-boundaries.spec.ts`，`21 passed in 22.8s`。
- 浏览器用例明确验证后端仅返回 2 个 item、但 `attention_count=7` 时仍显示精确数字；验证 localStorage 恢复指定任务、整页刷新后保持选择、focus 刷新及终态计数归零后入口消失。
- `pnpm --dir apps/web exec tsc --noEmit`、`pnpm --dir apps/web lint` 与 `pnpm --dir apps/web build` 全部通过。

证据文件/报告：`apps/web/src/components/companies/OnboardingAttentionButton.tsx`、`apps/web/src/components/companies/OnboardingCenter.tsx`、`apps/web/src/app/page.tsx`、`apps/web/src/lib/api.ts`、`apps/web/e2e/company-onboarding.spec.ts`。

遗留问题与下一步：C01—C09 的产品闭环与恢复入口均已完成；C10 将使用真实 NVDA SEC 字节执行候选、审核 Profile、构建、验证、批准、发布和强制刷新验收，并把固定字节纳入 golden 回归。

## C10 NVDA 真实闭环

阶段与提交号：C10；验证与实现提交 `5721f42`（已快进合并到 main）。

实际改动：有效 SEC 身份请求取得 NVDA 固定 10-K/10-Q 证据；候选 Profile 经版本审查，保留被质量门禁拒绝的旧版本，修正现金流符号和分部证据后封存数据、通过质量检查、批准并发布。官方 2026 10-K 原始字节、SHA、独立抄录数值、iXBRL context/locator 和分部对账进入 golden；正式库版本 v3 的两份 10-K 原始字节及 37 项证据另行固定并验证。补齐已发布财务、分部、公司来源新鲜度与溯源读取；旧不可变数据集缺 `filed_at` 时，从同一 filing 的规范化事实恢复披露时间，不把重抓日期冒充数据日期。已通过质量审核的公司目录显示 `VERIFIED`，旧发布记录也能正确读取。独立审查发现并修复新数据来源链接、旧封存分部重述选择、含 FX 净变动误判、历史 publication 溯源、旧任务缺抓取包恢复和旧配置证据不匹配安全暂停；现金规则后续版本升至 `v1.2`。

测试命令及结果：

- RED→GREEN：来源树曾 404、旧封存分部取旧值、现金桥误拒非零汇兑影响、已发布目录仍为 PENDING，均由新回归先复现后修复。
- `uv run pytest tests/golden/test_onboarding_issuers.py tests/integration/test_onboarding_pipeline.py tests/integration/test_onboarding_api.py -q`：`51 passed, 1 warning in 70.66s`。
- `uv run pytest -q`：最终 `412 passed, 1 warning in 132.16s`；唯一 warning 为 Starlette TestClient 上游弃用提示。
- `PLAYWRIGHT_PORT=3000 PLAYWRIGHT_CHROME_PATH=... pnpm --dir apps/web e2e`：最终 `37 passed in 29.5s`。旧 mock 路径断言已适配带 publication 的溯源 API。
- 冻结依赖、`compileall`、TypeScript、ESLint、Next build、`git diff --check` 通过；独立真实浏览器强制重载后 NVDA `VERIFIED`、FY2027 Q2、2026-08-26 财务/分部披露日期、两项报告分部与来源树均可见。

证据文件/报告：`docs/reviews/2026-09-19-company-onboarding-closure-validation.md`、`tests/fixtures/onboarding/0001045810/`、`config/issuers/0001045810/`。独立发布任务 `85171c6c-42e9-4abf-8b85-a405ec315969`，publication `95c57f23-84fc-49f7-9f94-99d6d85eb241`；正式任务 `2dfbca4b-f4ea-423c-aaa9-06362cbce376`，publication `87ba7dd8-dce9-4767-9643-21b4001a8eee`。

边界与下一步：独立验收库 `/tmp/equitylens-nvda-c10.XfGQKC` 和正式 `data/` 是分别审核发布的版本。管理层、行情、估值仍明确显示未同步/需配置，不能宣称整个研究面板全部完成。行情刷新与公司页面数据刷新体验优化保留为后续单独待办。

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

阶段与提交号：T10；`e6fc9af test: verify issuer onboarding end to end`。

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

## 上线后回归：未发布公司目录隔离（2026-09-16）

实际问题：创建 NVDA 建档任务后，身份注册已写入 `company/security`，但尚无 publication。公司目录查询遗漏发布门槛，返回 `publication_id=null` 的 NVDA；页面默认选中首项后，其总览、行情和新鲜度请求均返回 404。真实发现接口同时返回 `SUPPORTED/REJECTED`，页面仍使用旧的 `ELIGIBLE/INELIGIBLE` 枚举。

修复：后端公司目录只返回 `active_publication_id` 非空的证券；前端再次过滤无 publication 的异常响应，避免错误项成为当前公司；添加公司弹窗按真实 `SUPPORTED/REJECTED` 枚举展示和门禁。目录刷新增加请求代次并稳定发布回调，旧响应不会覆盖新发布公司；分页游标改为完整 `(security_id, ticker, alias_id)` 排序键并兼容旧游标。NVDA 建档任务继续保留为 `NEEDS_ADAPTATION`，未删除、未冒充正式发布。

验证：

- TDD 后端回归先失败、修复后通过；`uv run pytest -q`：`350 passed, 1 warning in 129.80s`。
- `pnpm --dir apps/web lint` 与 `pnpm --dir apps/web build` 通过。
- 新增未发布目录防御、目录迟到响应、SUPPORTED 展示和 REJECTED 门禁浏览器反例；全量 Playwright：`28 passed in 17.9s`。
- 真实数据库 API：公司目录仅返回 AAPL、MSFT；建档任务仍返回 NVDA `NEEDS_ADAPTATION`、`publication_id=null`。
- 真实浏览器：默认进入 Apple，侧栏无 NVDA，无“公司或财务总览加载失败”，控制台错误与失败请求均为 0。

## 后续优先级 P1：行情刷新与公司页面原地更新（2026-09-25）

实际改动：公司页刷新新增财务、分部、治理、行情四模块可视进度。等待和进行中保留红色未完成区，成功模块即时转绿并在返回后原地重载页面数据；成功但没有新披露或新行情时明确显示“检查成功，暂无更新”。进度卡分别显示数据日期和本次检查时间，本次检查时间按浏览器本地时区呈现，顶部来源信息继续显示 SEC 抓取时间。模块错误不会抹掉此前成功结果或旧完整快照，结构化错误与网络级错误均显示失败原因并可只重试该模块；单模块网络失败不会阻断后续模块，重试也不会重置其他模块状态。财务或行情变化一经返回即使后续模块失败也会立即触发估值复核。页面重新读取行情或新鲜度偶发失败时保留上次完整快照并明确提示，而不是清空成未同步。公司切换会清空旧进度，既有请求代次继续阻止迟到响应污染新公司。

测试过程：先以浏览器反例确认页面没有进度组件、重试会重置已有成功状态、中文摘要缺失、网络失败停留在进行中以及 UTC 时间被直接显示；再逐项实现并复跑。专项 Playwright 覆盖顺序请求、实时进度、无更新、即时重载、部分失败、单模块重试、估值自动重算、旧估值响应隔离和公司切换隔离。Python Playwright 独立启动真实 Next.js 页面并使用确定性 API 响应完成桌面/移动视觉验收，移动端 `scrollWidth - clientWidth = 0`；截图为 `/tmp/equitylens-refresh-desktop.png`、`/tmp/equitylens-refresh-mobile.png`。

最终验证：`pnpm --dir apps/web exec tsc --noEmit`、`pnpm --dir apps/web lint`、`pnpm --dir apps/web build` 均通过；系统 Chrome 全量 `pnpm --dir apps/web e2e` 为 `41 passed in 36.3s`；相关后端回归 `uv run pytest tests/unit/test_freshness.py tests/unit/test_replay_paths.py tests/integration/test_api.py -q` 为 `68 passed, 1 warning in 52.19s`，唯一 warning 仍为 Starlette TestClient/httpx 上游弃用提示；`git diff --check` 通过。

边界与下一步：本阶段改造的是刷新过程和页面更新体验，不把“检查成功但无新数据”伪装成数据日期变化，也不改变财务/行情来源本身的可用性。下一优先级为补齐 NVDA 的行情、治理与估值数据能力；AAPL/MSFT 旧版本复核和 KO/COST 官方 iXBRL 证据仍按既定顺序随后处理。
