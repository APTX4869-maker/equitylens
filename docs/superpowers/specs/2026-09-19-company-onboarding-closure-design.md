# EquityLens 新公司建档闭环与任务可见性设计

日期：2026-09-19

状态：产品设计已确认，等待实施计划

## 1. 目的

补齐当前新公司建档流程的最后一个真实阻塞点：没有预置发行人配置的公司会停在 `NEEDS_ADAPTATION`，但网页既不能查看候选适配内容，也不能下载、修订和导入审核版配置。用户刷新或关闭建档中心后，也缺少持续可见的任务状态，因此无法判断任务正在运行、等待人工还是已经失败。

本设计在既有高质量门禁、人工复核和不可变发布模型之上，完成以下闭环：

1. 后端基于任务已固化的 SEC 快照生成可审查的完整候选 YAML。
2. 维护者在网页查看候选映射、证据和阻塞项，下载 YAML 后在仓库中修订版本化配置。
3. 网页上传审核版 YAML，后端安全解析并严格校验；成功后自动恢复构建流水线。
4. 用户在任意研究页面都能看到未完成任务入口、数量、真实阶段和下一步。
5. 任务通过构建、质量校验和人工审核后发布，新公司自动进入研究列表。

设计来源：

- `docs/superpowers/plans/2026-09-11-company-onboarding.md`
- `docs/reviews/2026-09-18-user-journey-audit.md` 中 O05、O06、O08—O10 的发现
- 已确认的高保真页面方案：在现有“公司建档中心”内加入适配工作台和五段式进度条

## 2. 已确认的产品原则

- 数据质量优先，首次发行人适配必须经过维护者审核。
- 不绕过质量门禁，不允许候选配置自动获得“已审核”身份。
- 不把后台已暂停的任务描述为仍在加工，也不要求用户无限等待。
- 采用“网页审查 + YAML 导入”方案：网页负责展示候选内容、证据、阻塞项、下载和上传；维护者在仓库中维护版本化 YAML。
- 适配工作台整合在现有公司建档中心内，不再创建另一套独立任务页面。
- 所有状态来自持久化后台任务。刷新页面、切换公司或重新打开浏览器后必须恢复。
- 同一公司已有未完成任务时，重新添加应打开既有任务，不能创建第二个并发任务。
- 右下角提供全局、最上层的红色叹号任务入口；点击后打开公司建档中心并定位相关任务。

## 3. 范围

### 3.1 本次包含

- 完整候选发行人 Profile 的生成、持久化、查看和 YAML 下载。
- 将任务所需的 10-K、10-Q 及适用修订申报主文档纳入 FETCH 固定输入，并从 iXBRL 保留 context、locator 和分部证据。
- 审核版 YAML 的浏览器上传、安全解析、严格校验和不可变导入。
- 导入成功后从 `NEEDS_ADAPTATION` 自动恢复构建、校验、审核和发布。
- 建档中心五阶段进度、责任方、更新时间、阻塞原因和恢复动作。
- 所有页面可见的任务提醒入口、任务数量和刷新后恢复。
- 重复操作、并发修改、失败、取消、停滞和服务重启的恢复语义。
- 对上述流程的后端、前端和真实浏览器回归测试。

### 3.2 本次不包含

- 自动生成代码或自动提交发行人配置。
- 跳过维护者审核的全自动发布。
- 云账号、多人权限、邮件通知或外部任务调度。
- 任意服务器文件路径导入。
- 扩大现有支持模板；银行、保险、REIT、IFRS/20-F 等仍受既有模板与质量门禁约束。
- 行情刷新过程及普通公司页面的数据刷新体验改造；该项已登记为后续待办，见第 14 节。

## 4. 系统闭环

### 4.1 候选适配包

候选生成器只读取当前任务 FETCH 阶段已经固化的 `submissions`、`companyfacts`、申报主文档和来源清单，不重新请求网络数据，也不读取另一个任务的“最新文件”。候选输入身份同时包含 FETCH bundle 哈希、候选生成器版本、通用映射版本与内容哈希、Profile schema 版本。输出包括：

- 完整 `IssuerProfile` 字段骨架；可确定字段填入候选值，未确定的标量使用 `null`，集合使用空集合，并由 YAML 注释和 `unresolved_fields` 标出。候选 DTO 不是已通过验证的 `IssuerProfile`，不得送入构建。
- 每个指标的候选 XBRL concept、单位、期间类型和选择策略。
- 证券身份、财年、分部、现金债务、EPS 方法和适用性候选。
- 每项候选使用的证据 ID、来源文档、内容哈希和定位信息。
- `unresolved_fields`：所有必须由维护者处理的字段路径、原因和建议操作。
- 候选内容哈希、生成时间、任务 ID、任务修订号和所绑定的原始快照哈希。

候选包永远标记为未审核；即使没有未解决字段，也只能供维护者检查和导入，不能直接发布。

### 4.1.1 任务级固定 FETCH 输入

FETCH 不再只把输出哈希写进 attempt。它必须在完成前原子写入任务级不可变 fetch bundle，固定以下输入：

- submissions 和 companyfacts 快照。
- 满足当前质量窗口所需的最近 3 个年度和 8 个季度申报主文档，包括适用的 10-K/A、10-Q/A；选择规则遵循最新申报同口径并保留被修订版本。
- 每份文档的 accession、form、filed/report date、SEC URL、抓取时间、完整 SHA-256 和 raw-store 相对 locator。
- bundle 内容哈希和 fetcher/parser 版本。

后续候选、构建和质量检查只按 bundle 中的 SHA 读取；禁止重新解析可变的 `submissions.json`、`companyfacts.json` 或 raw-store latest 指针。若输入不完整，FETCH 失败或候选生成进入明确阻塞态，不能用未固定数据继续。

申报选择算法必须确定：

1. `as_of` 固定为 FETCH attempt 开始的 UTC 时间，只接受 SEC `filingDate <= as_of` 的记录。
2. 合并 submissions recent 与其声明的 history 文件，固定所有输入文件及 SHA 后再选择申报。
3. 基础表单只取 `10-K`、`10-Q`；按 `(base_form, reportDate)` 分组，以 `filingDate, accessionNumber` 确定顺序，选择最近 3 个不同年度 report date 和最近 8 个不同季度 report date。10-K 作为年度申报，Q4 由年度与前三季度累计数据按既有财务规则推导，不把 10-K 同时当作 10-Q。
4. 对每个已选基础申报，同时固定截至 `as_of`、相同 base form 与 report date 的全部 `10-K/A` 或 `10-Q/A`；修订文档不替换或删除原文档，由规范化阶段按 filed-at/restatement 规则决定事实优先级。
5. primary document 使用该 SEC submission row 的 `primaryDocument`，URL 由 CIK、无连字符 accession 和文件名确定；结果按 report date、filed date、accession 排序后计算 bundle 哈希。
6. 任一所需 history 或 primary document 缺失、哈希不匹配时，bundle 不得激活并返回明确 FETCH 错误。

### 4.1.2 iXBRL 与发行人适配配置

Company Facts 继续用于概念发现和交叉检查，但新公司正式数据集中的质量门禁指标必须能回到申报主文档的 iXBRL context 和 locator。BUILD 从固定申报文档提取 numeric facts，按审核版 Profile 映射、去重并处理重述，再生成满足 3 年/8 季窗口的规范事实。所需 filing context 不得通过伪造 locator 或仅引用 Company Facts 快照来满足。

新公司候选使用 `IssuerProfile` schema v2；已有 v1 Profile 继续只读兼容。v2 把此前分散在 `config/mappings/segment_axes.yaml` 的发行人分部配置纳入单一审核 YAML：

- `metrics.<metric>.evidence`：该映射所引用的证据 ID。
- `segments.parser`：首期只允许声明式 `ixbrl_segments_v1` 或 `not_applicable`。
- `segments.axes[]`：axis 名称、类型、标签、成员映射和证据 ID。
- `segments.revenue_concept`、可选 `profit_concept` 和 reconciliation 规则。
- `cash_debt.evidence` 以及原有证券、适用性证据。

所有 evidence ID 必须解析到本任务 fetch bundle 内的文档哈希。若申报结构无法由受支持的声明式解析器表示，任务保持 `NEEDS_ADAPTATION` 并说明需要先扩展受测试的解析器；系统不自动生成或执行代码。

#### Profile v2 规范

所有模型继续使用 `extra=forbid`。除标注可选外，字段均必填：

| 结构 | 字段与约束 |
|---|---|
| `IssuerProfileV2` | `schema_version: Literal[2]`；十位 `company_id`；正整数 `version`；`template: us_gaap_operating_v1`；`template_evidence: list[str]` 最少 1 项；以及下列 fiscal calendar、metrics、segments、cash debt、EPS、securities、applicability 和 evidence |
| `fiscal_calendar` | `year_end` 为 `MM-DD`；`week_based: bool`；`evidence: list[str]` 最少 1 项 |
| `metrics.<name>` | `concepts: list[str]` 最少 1 项；`unit: str`；`context: consolidated`；`period: duration/instant`；`selection: latest_filed_same_basis`；`evidence: list[str]` 最少 1 项 |
| `segments` | `parser: ixbrl_segments_v1/not_applicable`；`axes: list[SegmentAxisV2]`；`reconciliation: explicit_eliminations/not_applicable`；`revenue_concept: str/null`；`profit_concept: str/null`；`evidence: list[str]` 最少 1 项 |
| `SegmentAxisV2` | `name: str`；`kind: segment/product/geo`；`label: str`；`members: dict[str, SegmentMemberV2]` 最少 1 项；`evidence: list[str]` 最少 1 项 |
| `SegmentMemberV2` | `label: str`；`aggregate: bool = false` |
| `cash_debt` | 原有 `cash_components`、`debt_components` 最少各 1 项；`restricted_cash_policy: include/exclude/separate`；`evidence: list[str]` 最少 1 项 |
| EPS | `eps_method: reported_diluted/two_class/preferred_adjusted/null`；`eps_method_evidence: list[str]`；当 EPS 为 required 或方法非 null 时最少 1 项 |
| `securities[]` | 沿用 ticker、exchange、currency、instrument_type、可选 class_label；`evidence` 最少 1 项 |
| applicability | 每个受支持模块必须声明 `required/not_disclosed/not_applicable`；每个 `not_disclosed/not_applicable` 声明必须在 `applicability_evidence` 中有至少 1 个证据 ID |
| `evidence[]` | 沿用 `evidence_id`、`source_document_id`、完整 `content_sha256`、非空 `locator`；`evidence_id` 在 Profile 内唯一 |

条件约束：

- `segments.parser=ixbrl_segments_v1` 时，`axes` 至少 1 项、`revenue_concept` 非空、`reconciliation=explicit_eliminations`，且 applicability 的 SEGMENTS 不能是 `not_applicable`。
- `segments.parser=not_applicable` 时，`axes=[]`、两个 concept 都为 null、`reconciliation=not_applicable`，且 applicability 的 SEGMENTS 必须为 `not_applicable` 并提供证据。
- 所有 metrics、segment、cash/debt、EPS、security、template、calendar 和 applicability evidence 引用都必须存在，并且文档 SHA 属于当前 fetch bundle。
- 新建档任务和所有新导入一律要求 schema v2。schema v1 仅用于读取既有配置、历史 Profile 和历史 publication，不允许通过 JSON 或 YAML 接口新导入。
- 旧暂停任务若已有 v1 Profile，系统生成一个 v2 升级候选；新增证据字段进入 `unresolved_fields`，经维护者补齐并以新版本导入后才能恢复。

Profile 版本规则：首次 v2 导入必须大于该公司历史最高 Profile 版本；之后每次内容修订也必须严格递增。只有同一个 `Idempotency-Key` 的成功重放可以返回已经写入的相同版本；普通请求不能回退或重新绑定较旧版本。若在 `NEEDS_ADAPTATION` 上传与当前 Profile 完全相同的内容，界面提示没有实质修订并保持暂停；必须提交严格递增的新版本。只有处于 `FAILED` 且 remediation 为 `RETRY` 的非配置错误才使用 retry 动作。

### 4.2 维护者审核与导入

维护者在网页中完成以下动作：

1. 查看候选摘要、证据、未解决字段和当前阻塞原因。
2. 下载候选 YAML。
3. 将文件放入仓库的版本化发行人配置目录并修正内容。
4. 在网页选择修正后的 YAML 文件；浏览器读取文本并提交，不上传本地路径。
5. 后端安全解析、严格验证并返回字段级结果。

导入成功后：

- 使用现有不可变 `issuer_profile_version` 保存审核版配置。
- 将 Profile 绑定到当前任务，任务从 `NEEDS_ADAPTATION` 进入 `BUILDING`。
- 常驻 `OnboardingExecutor` 自动发现可运行任务并继续，不需要用户再次点击“启动”。
- 原候选数据保持可追溯，但不再被当作当前审核版配置。
- 网页上传只能证明导入的内容、版本与哈希；“文件已写入 Git 仓库并提交”仍是维护者流程约定，不由浏览器伪造保证。

### 4.3 构建、质量审核和发布

后续继续使用既有流水线：构建候选数据集、运行质量检查、生成复核包、人工批准、不可变发布。任何质量阻断项都不能被 Profile 导入动作绕过。发布成功后，公司进入研究列表，页面更新公司目录，任务成为终态 `PUBLISHED`。

质量失败或审核驳回后，维护者以当前已导入 Profile 而不是最初候选为修订基线。工作台提供当前 Profile YAML 下载；审核驳回转回 `NEEDS_ADAPTATION`，Profile 可修正型 BUILD/VALIDATE 失败也显式开放 `PROFILE_IMPORT`。重新导入产生新不可变版本并使旧 dataset、质量报告和审核失效。

## 5. 数据与持久化设计

新增不可变 `onboarding_fetch_bundle` 与 `onboarding_fetch_document`：bundle 记录任务、fetcher/parser 版本、内容哈希和创建时间，并以 `(onboarding_id, content_sha256)` 唯一；document 记录第 4.1.1 节的公开文档身份，并以 `(bundle_id, document_id)` 为主键。`company_onboarding.fetch_bundle_id` 固定当前任务使用的 bundle。相同任务可在显式重新抓取后产生新 bundle，但旧 bundle 和候选不得删除或改写。

新增不可变候选制品 `issuer_profile_candidate`，至少包含：

| 字段 | 含义 |
|---|---|
| `profile_candidate_id` | 候选制品唯一标识 |
| `onboarding_id` | 所属任务 |
| `task_revision` | 生成时任务修订号 |
| `company_id` | 固定十位 CIK |
| `fetch_bundle_id` | 固定输入 bundle |
| `input_sha256` | bundle、生成器、映射和 schema 身份的哈希 |
| `generator_version` | 候选生成器版本 |
| `mapping_version` / `mapping_sha256` | 通用映射身份 |
| `snapshot_manifest_json` | 公开快照身份；不接受可变 latest 指针 |
| `profile_json` | 完整候选字段骨架 |
| `unresolved_json` | 未解决字段、原因和建议操作 |
| `yaml_text` | 可下载的确定性 YAML 文本 |
| `content_sha256` | canonical JSON `{profile, unresolved_fields, snapshot_manifest}` 的 SHA-256 |
| `yaml_sha256` | 下载 YAML UTF-8 字节的 SHA-256 |
| `created_at` | 生成时间 |

约束：

- 制品写入后不可修改；数据库对 `(onboarding_id, input_sha256)` 建唯一约束，相同输入重复生成时返回同一制品。
- 候选生成失败不能覆盖上一份成功制品。
- Profile 导入继续写入现有不可变 `issuer_profile_version`。
- 每次候选生成、导入尝试、导入成功、恢复、审核和发布都写入任务事件或现有步骤记录，能够回答“系统或维护者角色在什么时候做了什么”。本地单用户阶段只记录角色，不声称识别具体自然人。
- 数据库迁移是新增式的，保留现有任务、Profile 和发布数据。

`company_onboarding` 新增 `fetch_bundle_id` 和 `profile_candidate_id` 指针。新任务首次进入人工暂停时，候选插入、候选指针绑定、暂停状态、revision 增长和事件写入必须在同一事务完成。兼容旧任务的候选生成不改变 `NEEDS_ADAPTATION` 阶段，但会绑定指针并递增 revision；客户端使用响应中的新 revision。失败只允许留下未被任务引用的 raw-store 文件，不得留下半写入 bundle、候选或任务指针。

新增追加式事件表 `onboarding_event`，用于记录不适合仅靠步骤 attempt 表达的用户或系统动作：

| 字段 | 含义 |
|---|---|
| `event_id` | 事件唯一标识 |
| `onboarding_id` | 所属任务 |
| `event_type` | 如 `PROFILE_CANDIDATE_CREATED`、`PROFILE_IMPORT_REJECTED`、`PROFILE_IMPORTED`、`TASK_RESUMED` |
| `actor_type` | `SYSTEM` 或 `MAINTAINER` |
| `task_revision` | 动作发生时的任务修订号 |
| `payload_json` | 内容哈希、错误码等最小审计信息；不保存重复的大段 YAML |
| `created_at` | 事件时间 |

事件只追加、不更新。纯读取或下载不改变任务状态，也不以 GET 请求制造审计写入。

Profile 导入使用一个新的 repository 原子操作完成：在同一写事务中重新校验 task revision/state、创建不可变 Profile、绑定 `profile_id`、清空旧 `dataset_id`/`quality_report_id`/`review_id`/`publication_id`、将旧 BUILD/VALIDATE/PUBLISH attempts 标记为 `STALE`、清除旧错误和 retry timer、更新到 `BUILDING/BUILD`、递增 revision、追加事件，并把 `Idempotency-Key`、请求哈希和完整成功响应写入 idempotency 表。任一步失败都整体回滚，不能留下未绑定 Profile，也不能出现任务已前进但幂等记录缺失。当前分离的 `create_profile()` 与 `set_candidate()` 调用不能直接作为最终导入实现。

## 6. API 契约

### 6.1 生成与获取候选适配包

新任务在 BUILD 步骤发现缺少审核版 Profile 时，必须先生成并持久化候选制品，再进入 `NEEDS_ADAPTATION`。因此正常流程打开页面时只执行读取。

兼容旧暂停任务时使用：

`POST /api/v1/company-onboardings/{task_id}/profile-candidate`

请求携带 `expected_revision`。“候选缺失”定义为当前 fetch bundle、生成器版本、映射哈希和 schema 版本计算出的 `input_sha256` 没有被当前 `profile_candidate_id` 指向；任务历史上存在旧候选不算当前候选。相同 input SHA 返回同一候选，缺少固定输入时返回明确阻塞错误。该接口不改变任务阶段，但首次绑定或升级候选指针会递增 task revision，响应必须返回更新后的任务和候选摘要。

`GET /api/v1/company-onboardings/{task_id}/profile-candidate`

返回：

- `profile_candidate_id`
- `onboarding_id`
- `task_revision`
- `content_sha256`
- `snapshot_manifest`
- `profile`
- `unresolved_fields`
- `created_at`

读取接口无副作用。候选基于固定输入确定，不因页面刷新产生不同结果。

`snapshot_manifest` 对每份文档只公开：`document_id`、`document_type`、`accession_number`、`form_type`、`filed_at`、`report_date`、`fetched_at`、`source_url`、`content_sha256` 和 raw-store 相对 `raw_locator`；不得返回绝对路径。

### 6.2 下载候选 YAML

`GET /api/v1/company-onboardings/{task_id}/profile-candidate.yaml`

以附件形式返回候选 YAML。文件包含帮助维护者理解未解决字段的注释，但解析后的顶层结构只能是 `IssuerProfile` 字段；不得把审查元数据混入最终 Profile schema。

`GET /api/v1/company-onboardings/{task_id}/profile-current.yaml`

任务已有 `profile_id` 时，以附件形式导出当前不可变 Profile，供质量失败或审核驳回后的二次修订。响应包含 Profile 版本和内容哈希 header；没有当前 Profile 时返回 `404 PROFILE_NOT_IMPORTED`。

### 6.3 导入审核版 YAML

`POST /api/v1/company-onboardings/{task_id}/profile-yaml`

请求必须带 `Idempotency-Key` header；浏览器对一次文件选择生成一个 key，网络重试复用同一个 key。

请求体：

```json
{
  "expected_revision": 3,
  "yaml_text": "<完整 YAML 文本>"
}
```

行为：

- UTF-8 请求上限为 512 KiB；解析后最大深度 20、最大节点数 20,000、单个 scalar 最长 64 KiB。
- 使用自定义严格 SafeLoader：只允许一个 mapping 文档，拒绝对象构造、自定义 tag、重复键、非字符串 mapping key、merge key、anchor 和 alias。
- 通过 `IssuerProfile` 的 `extra=forbid` schema 完整校验。
- 拒绝候选占位：任何未解决的 `null`、必填空集合或 `__REVIEW_REQUIRED__` 标记都返回字段错误。
- 校验 `company_id`、任务状态、取消标志、任务修订号和证据引用。
- 成功时复用 `IssuerProfileService.import_profile` 的不可变写入与候选失效语义。
- 请求哈希覆盖 task ID、expected revision 和 YAML 字节 SHA。服务先检查已提交 idempotency 记录：相同 key 和请求哈希返回第一次成功响应，即使任务 revision 已前进；相同 key 不同请求哈希返回 `409 IDEMPOTENCY_CONFLICT`。不存在匹配记录时再检查当前 revision，因此使用新 key 提交旧 revision 必须返回 `409 TASK_CONFLICT`。
- 除同 key 成功重放外，已存在的 Profile 版本无论内容是否相同都不能通过普通请求重新绑定；相同版本不同内容返回不可变版本冲突，相同内容则提示必须使用当前状态允许的动作或提交严格递增的新版本。
- 任务已经变化时返回 `409 TASK_CONFLICT`，不覆盖新状态。

允许导入的状态只有：

- `NEEDS_ADAPTATION`，包括首次适配、分部证据暂停和审核驳回。
- `FAILED` 且 `current_step` 为 BUILD 或 VALIDATE，并且后端动作列表明确包含 `PROFILE_IMPORT` 的 Profile 可修正错误。

`QUEUED`、`FETCHING`、运行中的 `BUILDING`/`VALIDATING`、`PUBLISHING`、`PUBLISHED` 和 `CANCELLED` 一律拒绝导入。导入事务提交后显式调用 executor `wake()` 以降低等待；即使 wake 丢失，常驻轮询和服务重启恢复仍能继续任务。

语法/schema 验证失败、业务冲突和回滚后的 5xx 不占用 idempotency key；只有业务事务成功时才保存 key。若提交成功但响应传输失败，重试同一个 key 必须从同一事务已保存的响应恢复。事务外的首次查询只用于快速返回；取得单写者事务后必须再次读取并比较 idempotency key，匹配则返回已存响应，不匹配则返回冲突，不能把唯一键插入错误暴露成 5xx。

现有 JSON 接口 `POST /profile` 保留兼容，CLI 继续可用；网页默认走 YAML 接口。兼容接口必须复用相同的状态授权、revision 检查和原子导入服务，不能成为绕过路径。

### 6.4 重新抓取固定输入

`POST /api/v1/company-onboardings/{task_id}/refetch`

请求携带 `expected_revision`。只有 `NEEDS_ADAPTATION` 或 `FAILED` 且当前阻塞码为 `FETCH_BUNDLE_INCOMPLETE`、`FETCH_BUNDLE_CORRUPTED` 时允许。不得把普通 Profile 校验错误伪装成重新抓取。UI 仅在后端 actions 包含 `REFETCH` 时显示此动作。

refetch 身份规则：

1. 接受 refetch 时保留旧 bundle、候选、Profile 和下游制品记录本身，但把其 ID 写入 `REFETCH_REQUESTED` 事件作为历史基线；任务转到 `FETCHING/FETCH` 后这些指针不再允许构建、审核或发布。
2. FETCH 进行中及失败时，旧 `fetch_bundle_id` 仍可用于诊断展示，但 API 标记 `current=false`；candidate/current-profile 下载也标记为历史制品，不提供导入动作。任务只能重试或取消。
3. 新 bundle 全部下载、校验并持久化成功后，在同一事务把 `fetch_bundle_id` 原子切换到新 bundle，同时清空 `profile_candidate_id`、`profile_id`、`dataset_id`、`quality_report_id`、`review_id`、`publication_id`，并将旧 BUILD/VALIDATE/PUBLISH attempts 标记 `STALE`。
4. 旧 Profile 的 evidence 绑定旧 bundle，不能自动复用。BUILD 基于新 bundle 生成新的 v2 候选，维护者必须重新审核并以严格递增版本导入。
5. GET/下载始终按任务当前 `profile_candidate_id` 选择候选；历史候选只能通过审计详情查看，不能被误当作当前候选。
6. 新 FETCH 失败时不替换当前 bundle 指针；修复后重试继续生成新 bundle。失败状态绝不能回到旧 bundle 自动构建。

### 6.5 完整任务状态转换

| 起始状态 | 动作/结果 | 目标状态 | 原子副作用 |
|---|---|---|---|
| `QUEUED` | executor 开始 FETCH attempt | `FETCHING` | 创建 RUNNING attempt、开始心跳 |
| `FETCHING` | bundle 成功固定 | `BUILDING` | 绑定新 bundle，完成 FETCH attempt，进入 BUILD |
| 任一运行态 | retryable 失败且未满 3 次 | 保持 current step 对应运行态 | attempt 失败，按 2/4 秒退避设置 `next_attempt_at` |
| 任一运行态 | 非重试错误或同输入第 3 次失败 | `FAILED` | 保留 current step 和错误 remediation |
| `BUILDING`、无 Profile | 候选保存成功并暂停 | `NEEDS_ADAPTATION` | 绑定候选，记录暂停原因 |
| `BUILDING`、有 Profile | dataset 构建成功 | `VALIDATING` | 绑定 dataset，完成 BUILD attempt |
| `NEEDS_ADAPTATION` | 审核版 YAML 导入成功 | `BUILDING` | 绑定 Profile，失效下游制品，恢复 BUILD |
| Profile 可修正 `FAILED` | 审核版 YAML 导入成功 | `BUILDING` | 同上 |
| `VALIDATING` | 质量检查完成且无需适配 | `NEEDS_REVIEW` | 绑定 report；PASS/FAIL 都进入可见审核，FAIL 禁止批准 |
| `VALIDATING` | 发现必须补充的 Profile/分部证据 | `NEEDS_ADAPTATION` | 绑定 report，current step 回到 BUILD，开放 Profile 修订 |
| `NEEDS_REVIEW` | 审核拒绝 | `NEEDS_ADAPTATION` | 保留当前 Profile 作为修订基线，失效审核 |
| `NEEDS_REVIEW` | 审核批准且质量 PASS | `PUBLISHING` | 绑定精确 candidate fingerprint |
| `PUBLISHING` | 发布成功 | `PUBLISHED` | 激活不可变 publication |
| 可重新抓取暂停/失败态 | `refetch` | `FETCHING` | 保留旧制品、记录事件并 `wake()`；由 executor 唯一创建 FETCH attempt |
| `FAILED` | `RETRY` | 与 current step 对应的运行态 | 清错误和 timer，使用同一不可变输入重新执行 |
| 服务启动发现 RUNNING attempt | 恢复 | 保持 step 对应运行态 | attempt 标记 INTERRUPTED，创建新 attempt；已完成相同输入不重复执行 |
| 非运行非终态 | 取消 | `CANCELLED` | 事件保存取消前 progress snapshot |
| 运行态 | 取消请求 | 保持当前运行态直至安全点，再 `CANCELLED` | 设置 cancel flag；事件保存取消前 progress snapshot |

表中“任一运行态失败/重试”和“取消”覆盖 FETCH/BUILD/VALIDATE/PUBLISH；除此之外未列出的写状态转换均返回冲突，不采用“尽量继续”的隐式行为。

### 6.6 任务进度字段

任务列表和详情都由后端返回同一份派生进度，前端不各自维护状态映射：

```json
{
  "progress": {
    "completed": 2,
    "total": 5,
    "percent": 40,
    "current_stage": "ADAPTATION",
    "activity": "WAITING_FOR_MAINTAINER",
    "actor": "MAINTAINER",
    "updated_at": "2026-09-19T10:00:00Z",
    "stalled": false,
    "stages": [
      {
        "id": "IDENTITY",
        "label": "识别公司",
        "status": "COMPLETED",
        "activity": "COMPLETED",
        "started_at": null,
        "completed_at": "2026-09-19T09:58:00Z"
      }
    ],
    "fingerprint": "<任务、attempt、event 水位的哈希>"
  }
}
```

五个 stage ID 固定为 `IDENTITY`、`FETCH`、`ADAPTATION`、`BUILD_VALIDATE`、`REVIEW_PUBLISH`。`stages[].status` 只能是 `COMPLETED`、`CURRENT`、`UPCOMING`；顶层和当前段 `activity` 只能是 `QUEUED`、`RUNNING`、`WAITING_FOR_MAINTAINER`、`FAILED`、`CANCELLED` 或 `COMPLETED`，UPCOMING 段的 activity 必须为 null。`actor` 只能是 `SYSTEM`、`MAINTAINER` 或 `NONE`。运行 handler 至少每 10 秒更新 attempt heartbeat；连续 45 秒没有 heartbeat 才标记 `stalled=true`，阈值可配置但测试固定使用默认值。

FAILED 精确映射：current step 为 FETCH 时完成 1 段、当前 `FETCH`；BUILD 且无 Profile 时完成 2 段、当前 `ADAPTATION`；BUILD 且有 Profile 或 VALIDATE 时完成 3 段、当前 `BUILD_VALIDATE`；PUBLISH 时完成 4 段、当前 `REVIEW_PUBLISH`。失败段 activity 为 `FAILED`，后续为 UPCOMING/null。

取消请求创建 `TASK_CANCELLED` 事件时直接保存取消前的完整 `progress_snapshot_json`，包含 stage ID、completed、percent、actor 和 fingerprint；最终 CANCELLED 展示以该快照为基线，只把当时当前段 activity 改成 `CANCELLED`。排队期取消、BUILDING 有无 Profile 等情况不再二次猜测。

`progress.fingerprint` 覆盖 task revision、最新 attempt heartbeat 和事件水位；list/detail 在相同 fingerprint 下必须返回相同进度，heartbeat 改变时允许 fingerprint 随之改变。

`GET /api/v1/company-onboardings?attention_only=true` 返回全部待关注任务的分页 items，同时返回数据库 `COUNT(*)` 计算的 `attention_count`，数量不受当前页 `limit` 影响。前端不能用最多 200 条结果自行猜总数。

### 6.7 错误格式

预期错误返回稳定 `code`、用户可理解的 `message`，以及适用时的字段错误列表：

```json
{
  "detail": {
    "code": "INVALID_PROFILE_YAML",
    "message": "审核版配置有 2 个字段需要修正",
    "remediation": "PROFILE_IMPORT",
    "field_errors": [
      {"path": "metrics.REVENUE.unit", "message": "Field required"}
    ]
  }
}
```

YAML 语法错误尽量提供安全的行列位置。响应不得回显超大文件、服务器路径或敏感环境变量。

任务错误额外返回稳定的 `remediation`：`PROFILE_IMPORT`、`REFETCH`、`RETRY` 或 `NONE`；后端据此生成 actions，前端不得从中文错误消息猜操作权限。

## 7. 用户界面设计

### 7.1 全局任务入口

- 在应用右下角使用固定定位、最高业务层级的红色叹号按钮。
- 显示需要关注的任务数量；范围包括运行中、等待人工和失败任务，不包括 `PUBLISHED`、`CANCELLED`。
- 没有需要关注的任务时隐藏入口，避免永久噪声。
- 点击打开现有公司建档中心；只有一个任务时直接选中，多任务时用 `localStorage` 保存最近选择的 task ID，找不到时选择 `updated_at` 最新任务。
- 首次加载、窗口重新获得焦点、建档动作完成和任务变更后刷新任务摘要。
- 真正运行态才高频轮询；等待适配、等待审核、失败和终态不制造后台仍在运行的假象。

### 7.2 五阶段进度条

所有后台状态映射为用户可理解的五个阶段：

1. 识别公司
2. 获取 SEC 数据
3. 适配公司规则
4. 构建并校验数据
5. 人工审核与发布

视觉语义：

- 绿色：已经完成。
- 红色：当前尚未完成的阶段。
- 灰色：尚未开始。
- 每段同时显示文字、状态图标和可访问文本，不能只依赖颜色。
- 百分比只计算完整完成的阶段。例如 `NEEDS_ADAPTATION` 完成前两段，显示 `2/5 · 40%`，第三段为红色。
- 红色当前段必须配合文本区分“正在执行”“等待维护者”和“执行失败”；颜色本身不能暗示后台一定在计算。

后台状态映射：

| 后台状态 | 当前阶段 | 展示语义 |
|---|---:|---|
| `QUEUED`、`FETCHING` | 2 | 等待/正在获取 SEC 数据 |
| `BUILDING` 且无 `profile_id` | 3 | 正在准备或检查适配规则 |
| `NEEDS_ADAPTATION` | 3 | 已暂停，等待维护者导入审核版配置 |
| `BUILDING` 且有 `profile_id`、`VALIDATING` | 4 | 正在构建或校验数据 |
| `NEEDS_REVIEW`、`PUBLISHING` | 5 | 等待维护者审核或正在发布 |
| `PUBLISHED` | 无 | 五段全部完成，100% |
| `FAILED` | 按 `current_step` 和已有制品推导 | 保留已完成绿色段，在失败段显示错误 |
| `CANCELLED` | 按取消前记录推导 | 保留历史进度并标记已取消 |

进度由任务状态、步骤尝试和已绑定制品实时推导，不另外保存一个容易失真的百分比。

完整阶段数规则固定为：`QUEUED/FETCHING=1`、适配阶段=2、构建/校验阶段=3、审核/发布阶段=4、`PUBLISHED=5`。`FAILED`/`CANCELLED` 使用第 6.6 节规定的失败或取消前阶段，不能凭当前是否存在错误字符串猜测。

### 7.3 任务详情与适配工作台

任务详情在进度条下展示：

- 当前状态、完成阶段、最近更新时间和当前责任方。
- 上次步骤开始/结束/心跳时间。
- 当前阻塞原因和唯一明确的下一步。
- 候选字段覆盖率、未解决字段数量、证据数量和快照哈希摘要。
- 候选映射与证据的可展开列表。
- 首次适配显示“下载候选 YAML”；已有 Profile 的返工显示“下载当前审核版 YAML”，并始终提供“选择审核版 YAML”。
- 上传前文件名和大小；校验中、成功、字段错误及版本冲突状态。
- 成功导入后立即刷新为 `BUILDING`，进度条移动到构建阶段并恢复轮询。
- 固定输入缺失时仅显示后端授权的“重新抓取 SEC 资料”，普通适配错误不显示该操作。

`NEEDS_ADAPTATION` 的固定主提示为“任务已暂停，等待维护者操作”，不得显示“请继续等待”或无意义的“重试当前步骤”。

## 8. 运行、暂停、失败和停滞语义

- **正在执行**：后台存在可运行步骤或 RUNNING attempt；显示当前步骤和最近心跳。
- **等待人工**：`NEEDS_ADAPTATION` 或 `NEEDS_REVIEW`；停止运行态轮询，明确责任方和操作入口。
- **执行失败**：`FAILED`；展示失败阶段、稳定错误码、说明、技术详情折叠区和可执行恢复动作。
- **可能停滞**：运行态 attempt 的心跳超过阈值；界面显示“可能停滞”，建议检查后台服务或重试，不自行判定成功或创建重复任务。

错误与恢复要求：

- SEC 限流、超时或不可用：显示 HTTP/领域错误、已重试次数和建议；保留已成功下载的不可变快照。
- 缺少 `EQUITYLENS_USER_AGENT`：在发现或创建任务前置检查，阻止启动并显示配置说明。
- 候选配置不完整：允许查看和下载，列出全部未解决字段，但禁止导入后进入构建。
- YAML 语法或 schema 错误：保留任务和原候选不变，精确提示修改位置。
- 版本或修订冲突：拒绝覆盖，提示重新加载任务并下载最新候选。
- 构建或质量门禁失败：保留构建产物和报告；允许修正配置后按受控动作重新导入或重试。
- 页面刷新或关闭：后台任务继续；重新进入后恢复真实状态。
- 重复添加同一公司：打开既有未完成任务；已发布证券提示无需重复建档。
- 取消任务：停止后续步骤，保留历史记录；以后可以按现有产品规则重新创建。

## 9. 安全与完整性边界

- 网页上传 YAML 文本，不接受服务器路径、URL 或文件系统 glob。
- 使用安全 YAML 解析器并限制文件大小、文档数量和解析后的结构深度/规模。
- 严格校验类型、未知字段、CIK、任务归属、修订号、Profile 版本和证据引用。
- 候选证据只能引用当前任务固定快照中的文档和哈希。
- 候选 Profile 无论覆盖率多高都不能直接发布。
- 未通过质量检查的候选数据集不能进入人工批准成功路径。
- 导入失败不得部分写入 Profile、改变任务状态或唤醒错误任务。
- 所有状态写入继续通过单应用写入进程和事务执行。

## 10. 兼容与迁移

- 现有任务表、JSON Profile 导入接口、CLI 和已发布公司保持可用。
- fetch bundle、候选制品和事件表采用新增迁移；不重写旧发布版本。
- 旧任务只有在 submissions、companyfacts 和质量窗口所需申报主文档都可按 SHA 固定时，才允许补建 legacy fetch bundle 并生成候选。
- 当前 NVDA 原始目录只有 submissions/companyfacts，没有申报 iXBRL 主文档，不能直接满足 `LINEAGE.filing_context` 和分部证据门禁；本次实现必须通过受控 `refetch` 抓取并固定所需 10-K/10-Q 文档，而不是降低门禁或伪造证据。
- 若旧任务缺少生成候选所需的固定快照，界面显示 `FETCH_BUNDLE_INCOMPLETE` 并提供受控的 FETCH 重试，而不是生成无证据配置。
- 前端类型变更采用新增字段，旧任务在字段缺失时由 API 推导兼容值。

## 11. 测试策略

实现遵循测试驱动：先增加能复现缺口或错误的失败测试，再实现最小行为，最后运行相关回归。

### 11.1 后端测试

- 候选生成只使用固定快照，输出确定且证据哈希匹配。
- FETCH 原子保存任务级 bundle；后续即使 raw-store latest 改变仍读取原 SHA。
- iXBRL required metrics 保留真实 context/locator；Company Facts 不能冒充 filing lineage。
- schema v2 中指标、分部、现金债务、证券和适用性证据均可解析到 bundle 文档。
- 完整字段骨架和未解决字段路径正确。
- 候选不可自动批准或发布。
- YAML 安全解析拒绝对象 tag、多文档、非对象和超限内容。
- schema、公司归属、证据、版本和任务 revision 校验。
- 相同内容幂等、同版本异内容冲突、旧 revision 冲突。
- idempotency key 重放先于 revision 检查；新 key 加旧 revision 仍冲突。
- 导入事务任一点失败都无未绑定 Profile 或部分任务更新；成功后状态进入 `BUILDING`。
- 执行器从导入后的任务自动继续，经过验证、审核和发布。
- 心跳按 10 秒更新、45 秒停滞判定；FAILED/CANCELLED 进度使用保留的步骤或取消事件。
- list/detail 对相同进度 fingerprint 返回同一五阶段结果，attention count 不受分页限制。
- 服务重启、步骤重放和重复请求不产生重复制品或发布。

### 11.2 前端与浏览器测试

- 全局任务入口在创建后出现，显示正确数量，终态后消失。
- 强制刷新页面后入口、任务选择和真实进度恢复。
- 五阶段颜色、文字、图标、百分比和可访问名称正确。
- `NEEDS_ADAPTATION` 明确显示暂停和维护者操作，不显示后台运行假象。
- 候选详情、未解决字段、证据展开和 YAML 下载可用。
- 上传空文件、非 YAML、超大文件、恶意 YAML、字段缺失和旧 revision 均有可执行提示。
- 导入成功后页面无需手动刷新即进入构建阶段并恢复轮询。
- 双击、重复上传和两个标签页并发操作不会创建重复任务或覆盖新状态。
- 失败、停滞、取消、审核拒绝、重新导入和最终发布路径可恢复。
- 多个公司任务并存时入口数量和任务切换正确。
- 待关注任务超过单页上限时 badge 仍显示数据库准确总数；最近任务选择刷新后恢复。

### 11.3 真实端到端验收

以 NVDA 作为真实未发布公司样例：

1. 打开现有 NVDA 任务，确认处于 `NEEDS_ADAPTATION`。
2. 确认系统识别旧任务缺少 iXBRL 固定输入，执行受控 `refetch`，抓取并固定质量窗口所需的 10-K/10-Q 主文档。
3. 生成并检查候选包、真实 filing context/locator、分部证据和未解决字段。
4. 下载 YAML，在仓库中完成审核修改，再从网页上传。
5. 验证无需额外启动动作即可继续构建和质量检查。
6. 查看复核包，确认 `LINEAGE.filing_context`、分部和其他阻断项不可绕过；满足条件后批准。
7. 验证任务发布、NVDA 进入公司列表并可打开真实研究数据。
8. 强制刷新浏览器，确认发布状态和公司仍然存在。

最终验证必须包括：全部后端测试、前端测试、Playwright、lint、生产构建和真实无扩展浏览器检查。不得以模拟 API 的浏览器测试代替 NVDA 实际闭环。

NVDA 在线验收以 SEC 可访问且 `EQUITYLENS_USER_AGENT` 合法为外部前置条件。若 SEC 返回 403、429 或持续不可用，验收记录为外部阻塞并保留已下载制品；不得改用缺少 filing context 的 Company Facts 冒充通过，也不得降低质量门禁。待 SEC 恢复后从持久任务继续同一验收。

## 12. 验收标准

- 用户始终能知道任务是否运行、等待人工、失败、取消或完成。
- 任意页面刷新后都能重新发现未完成任务，不会误导用户重复添加。
- `NEEDS_ADAPTATION` 页面提供真实可用的候选查看、下载和审核版导入入口。
- 导入错误精确、可恢复且不改变正确状态；导入成功自动继续。
- 新公司必须经过不可变 Profile、候选数据集、质量报告和人工审核后才能发布。
- NVDA 的质量窗口指标必须追溯到固定 iXBRL 申报文档，不能仅引用 Company Facts 或降低门禁。
- NVDA 完成一次真实端到端发布并进入研究列表。
- 每个实施阶段都更新 `docs/reviews/2026-09-11-company-onboarding-progress.md`，记录改动、验证命令、结果、残余风险和下一步。

## 13. 实施边界与建议顺序

建议实施顺序为：

1. 任务级 fetch bundle、申报文档抓取和按 SHA 重放。
2. iXBRL 事实/分部证据接入与 `IssuerProfile` schema v2。
3. 候选制品数据模型和确定性完整候选生成。
4. 候选/当前 Profile 下载、严格 YAML 导入、原子恢复与重新抓取 API。
5. 后端统一进度、心跳、状态转换和全局 attention count。
6. 前端五阶段进度、适配工作台、上传与返工流程。
7. 全局任务入口、刷新恢复和多任务行为。
8. NVDA 真实闭环、全量回归和文档更新。

具体文件和逐步测试命令由后续实施计划给出。本设计不授权跳过既有 T01—T10 的完成记录或质量门禁。

## 14. 已登记的后续待办：数据刷新体验优化

状态：**待本次新公司建档闭环完成后再评审和实施，本次不开发。**

待办范围：

- 行情刷新过程提供模块级实时进度，而不是长时间只显示“刷新中”。
- 普通公司页面在刷新完成后自动重新加载受影响内容，不要求用户手动刷新浏览器。
- 明确区分数据披露/观察日期、最近成功检查时间、抓取时间和页面更新时间。
- 无新财报或无新行情时明确显示“检查成功但没有更新”，避免用户把日期未变化理解为刷新失败。
- 继续保留部分模块成功、失败模块单独重试和旧完整快照不被破坏的语义。

该待办在本需求完成后的下一轮设计中重新检查现状、边界和验收用例，不在当前实施计划中顺带修改。
