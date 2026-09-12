# EquityLens 高质量公司建档：完整设计与开发计划

> **For agentic workers:** 使用 superpowers:executing-plans 按阶段顺序执行本计划。步骤用复选框跟踪。用户要求顺序执行，每完成一部分更新进度文档；不要默认派发子代理。

**Goal:** 用户从页面提交任意美股公司建档申请，经发行人专属适配、证据复核和质量校验后发布，支持可追溯分析。

**Architecture:** 本地单用户、单应用写入进程、持久化步骤任务；发行人和证券分离；候选数据隔离，按完整发布版本读取。系统采集和校验，维护者完成首次发行人适配复核；不承诺申请后无人参与即可完成。

**Tech Stack:** 现有 Python >=3.12、FastAPI、Pydantic、DuckDB、httpx、lxml、PyYAML；Next.js/React/TypeScript、pnpm；pytest、Playwright。沿用仓库锁文件，不在本功能中升级框架。

**Spec:** 本文第 1—12 节就是完整设计，第 13—16 节是执行计划与交接规则。单独拿到本文即可理解和开始开发，不依赖旧会话。背景审查见 `docs/reviews/2026-09-11-company-onboarding-design-review.md`，冲突时以本文为准。

**状态:** 用户已确认产品方向、维护者复核模式及审查修订，并要求编写完整开发文档。本文是开发输入；当前尚未实现新增公司功能。文档日期 2026-09-11，代码基线 `f00ae97`，项目 `/Users/vincent/workspace/equitylens`。

## 1. 已确定的目标、边界和执行约束

- 页面不再只列 AAPL/MSFT；动态列出已发布证券及原有公司。
- 用户接受等待，以分析数据质量为第一优先；不允许为即时加入而降低门槛。
- 申请范围为美股经营公司；ETF、基金、指数、空壳 SPAC 不支持。不能仅凭 ticker 注册表断言资格，需申报身份、类型和证据；不确定时停留待复核。
- 首期实现 US-GAAP 普通经营公司、10-K/10-Q 披露制度的完整模板。银行、保险、REIT、IFRS/20-F、ADR 允许识别并提交待适配请求，未有验证模板前不能发布。未来扩展模板无需改变申请接口。
- 同一 CIK 可以有多个证券；公司财务共享，各股类行情分离。多股类可以发布财报，无法证明每股换算时关闭每股估值。
- 本地单用户，无账号、云服务、邮件通知、定时唤起 Codex、自动代码生成执行。服务关闭期间任务不运行，重启可恢复。
- 必须有维护者适配入口和实际闭环；不能只做一个永远停留在等待的 UI。
- 已发布财务在行情临时不可用时仍可查看；当前价格相关估值需要有效行情。证券身份验证是首次发布前置条件，行情新鲜度不是财报持续可见的条件。
- 普通实现细节由开发者按本文确定，不再逐项请求产品确认。遇到需要改变上述边界时才说明取舍。
- 按阶段顺序开发，完成每一阶段更新 `docs/reviews/2026-09-11-company-onboarding-progress.md`，记录测试、实际完成内容和阻塞。
- 开发前读取适用 AGENTS.md，查询本地知识库；前端遵守 `apps/web/AGENTS.md`，阅读安装在 node_modules 中的 Next.js 对应指南。
- 创建 `codex/company-onboarding` 分支或隔离工作树；检查已有分支和用户修改，不能覆盖。本文编写不改变产品行为。

## 2. 当前代码与可复用能力

| 位置 | 当前情况 | 修改目标 |
|---|---|---|
| `equitylens/domain/companies.py` | SUPPORTED 硬编码两家公司；SEC ticker 本地查询 | 数据库注册表与证券解析，保留兼容解析入口 |
| `spec/schema.sql`、`storage/duckdb_store.py` | company 表已有；事实按 company_id，替换式写入 | 有版本迁移、候选与发布隔离、发布限定查询 |
| `ingestion/sec/sync.py` | Company Facts 和 submissions 快照、规范化 | 复用采集，接受解析后的公司身份和候选构建上下文 |
| `normalization/ixbrl.py`、`segments.py` | 现有 iXBRL 和专属分部解析 | 扩充报表事实证据和专属口径适配 |
| `config/mappings/*.yaml` | 通用财务与 AAPL/MSFT 分部规则 | 通用基础加 CIK 专属版本，不按 ticker 长期存配置 |
| `refresh/service.py` | 进程内公司锁和全局写锁、暂存文件发布 | 全局统一写入调度和 publication 发布，不新建旁路写锁 |
| `api/routes.py`、`api/main.py` | 公司路由调用硬编码解析器 | 新建独立建档路由，lifespan 托管任务执行器 |
| `market/sources.py`、`market/service.py` | 证券供应商配置和行情 | security_id 隔离、供应商身份映射 |
| `valuation/service.py`、`defaults.py` | 已有估值方案、假设和过期机制 | 新公司确认门禁、publication/security 指纹 |
| `apps/web/src/components/Shell.tsx`、`src/app/page.tsx` | 静态公司列表 | 动态列表、申请、任务详情和质量报告 |

API 前缀沿用 `/api/v1`。现有 CLI、分部、行情、管理层及刷新中所有 get_company 调用都必须盘点迁移，不能仅修改页面和 API 入口。

历史验证记录为后端 251 passed、TypeScript/ESLint 通过、浏览器 12 passed；这是旧基线记录，不是当前或新功能的验证结果。开始开发时重新获取基线。

## 3. 用户与维护者流程

### 3.1 用户

1. 点“添加公司”，输入 ticker；去空格转大写，长度 1—20，字符限定字母、数字、点、短横线，拒绝 URL 和路径。
2. 只读识别，显示发行人、CIK、证券类别、交易所、身份来源、支持状态。歧义时明确选择证券；不猜测。
3. 确认身份创建任务。已有证券返回原证券；已有发行人任务复用任务，并关联新增证券请求。
4. 建档中心展示阶段、已完成步骤数/总步骤数、等待原因、覆盖期间、最近更新时间、质量检查及重试/取消。
5. 首次适配复核和强制规则全部通过后自动发布，侧边栏刷新。选中新增证券进入公司页。
6. 公司页常驻质量摘要入口：数据截止日、适配版本、来源、未披露/不适用项目、复核时间。估值单独显示等待假设或模型不适用。

不显示猜测百分比或预计完成日期；不提供“忽略错误并发布”。已取消任务可重新申请，历史记录保留。

### 3.2 维护者

1. 任务自动生成候选映射、来源清单与问题列表，停在 NEEDS_ADAPTATION 或 NEEDS_REVIEW。
2. 页面预览证据，导出 JSON 审查包：固定快照哈希、候选配置、检查结果、待解决项和原始文件定位；不打包任意文件路径。
3. 维护者在 `config/issuers/<CIK>/<version>.yaml` 修正映射、期间、股类、分部和勾稽规则；未知解析器需另行开发并测试。
4. CLI 校验 YAML 结构后通过本地 API 导入不可变配置，构建新候选并重跑质量检查。
5. 校验通过后，维护者对精确输入指纹提交复核记录及结论。确认按钮/命令不能覆盖失败规则；版本变化使旧复核失效。
6. 系统原子发布。普通后续刷新在已批准规则和稳定结构下自动验证发布；新 concept、分部结构、会计口径或重述变化重新进入复核。

复核是本地操作留痕，不声称具有密码学身份签名。首次空白配置不能自动获得批准。

## 4. 数据模型与不变量

新增表均有明确 schema migration；不要仅靠 CREATE TABLE IF NOT EXISTS 改旧表。时间统一 UTC，数值保留原始字符串和单位，哈希用规范 JSON/字节 SHA256。

| 表 | 主要字段与约束 |
|---|---|
| `schema_migration` | version PK、applied_at、checksum；已执行迁移校验和不可变 |
| `company` 扩展 | company_id = 零填充 CIK，cik UNIQUE、legal_name、reporting_template、active_publication_id nullable、quality_status、created_at/updated_at；旧 ticker 仅兼容字段 |
| `security` | security_id UUID PK、company_id FK、class_label、exchange、currency、instrument_type、status、identity_evidence_json |
| `security_ticker_alias` | alias_id PK、security_id、ticker、exchange、valid_from、valid_to nullable；同一交易所和 ticker 有效期间不能重叠，应用事务内验证 |
| `company_onboarding` | onboarding_id UUID、company_id、state、current_step、revision、cancel_requested、input_fingerprint、error_json、created_at/updated_at；同发行人最多一个活动建档任务 |
| `onboarding_security` | onboarding_id + security_id 联合唯一；多个证券复用财务工作 |
| `onboarding_step_attempt` | attempt_id、onboarding_id、step、attempt_no、input_hash、output_hash、state、started_at/finished_at、heartbeat_at、error_json；重试追加记录 |
| `issuer_profile_version` | profile_id、company_id、version、schema_version、content_json、content_sha256、created_at；company/version 唯一，不可变 |
| `dataset_version` | dataset_id、company_id、profile_id、source_manifest_json、parser_version、rule_version、state、created_at；候选构建后封存 |
| `dataset_row` | dataset_id + entity_type + row_id 联合主键、payload_json、payload_sha256；保存发布所需完整规范事实、指标、分部及证据引用 |
| `publication` | publication_id、company_id、dataset_id、profile_id、quality_report_id、review_id、published_at；发布后不可变 |
| `quality_report` | report_id、dataset_id、rule_version、result、fingerprint、created_at |
| `company_quality_check` | report_id + check_id + scope_key 唯一；status、severity、actual_json、expected_json、tolerance_json、evidence_json、reason |
| `adaptation_review` | review_id、company_id、fingerprint、reviewer、decision、note、created_at；批准只对固定指纹有效 |
| `company_capability` | publication_id + module 唯一；status、reason、coverage_json；行情实时状态另行计算，不能改写旧报告 |

实现决定：为控制旧库迁移风险，首期使用 `dataset_row` 保存封存的规范对象，通过类型化 repository 反序列化；现有表保留旧版和候选构建兼容用途。正式新版本查询不直接读那些替换式表。候选计算在临时 DuckDB 中复用现有管线，完成后抽取完整数据对象入 dataset_row。JSON 不是随意扩展接口：为 entity_type 建立 Pydantic 模型，单位、期间、来源引用必须校验；后续性能优化可转专用版本表，不改变 publication 契约。

源快照保持内容寻址和原始 fetched_at，新增快照不得重写旧引用。原始 raw_fact/source_document 可复用不可变对象，dataset_row 引用必须可解析且哈希匹配。任何现有替换逻辑不得删除被旧 publication 使用的证据。

估值复用 `valuation_assumption_set`、`valuation_run`、`valuation_plan`，增加 security_id、publication_id、确认状态/时间和输入指纹，不另建同义 valuation_profile 表。market_observation 增加 security_id；旧记录通过已核实种子证券回填。

## 5. 发布一致性、读取与迁移

发布指纹定义：SHA256(canonical JSON{dataset_hash, profile_hash, rule_version, parser_version, quality_report_hash, security_identity_hashes})。reviewer 批准此指纹，不能只批准 ticker。

发布顺序：

```text
采集不可变原始文件 → 临时库计算 → 封存 dataset → 校验引用/哈希
→ 保存质量报告 → 首次/变更复核 → 全局写事务重新验证输入未变
→ insert publication + capabilities → 更新 active_publication_id → COMMIT
```

事务中再次检查取消状态、期望任务 revision、活动发布指针和复核指纹；冲突返回 409。文件先持久化，事务失败允许残留未引用文件；不能先推进 manifest 再让旧查询读到新数据。无引用文件清理只做显式维护命令，不在首期自动删除。

每个 API 请求起始解析 publication_id；页面首个公司响应返回 publication_id，后续财务/分部/来源/分析请求携带它，避免多个请求跨发布混读。后台发布新版本时 UI 提示有更新，用户刷新后整体切换。候选仅在维护者任务接口可见。来源抽屉必须使用该版本证据，不按最新文件定位。

迁移：停止应用写入，备份 DB + raw manifest 及摘要；在副本执行迁移并重放。AAPL/MSFT 的 company_id 已按 CIK 写入主要链路，先核查异常值而非盲目替换。创建证券和 legacy dataset/publication，标记 LEGACY_UNREVIEWED，保持旧页可读；不能把旧质量认证写成通过。新门禁对新增证券立即生效，旧估值历史保留并显示旧版身份。完成新标准复核后再切新 publication。

迁移验收比较表行数、主键集合、来源路径/SHA/fetched_at、估值输出摘要；迁移二次执行无变化。回滚使用停止服务后恢复备份，不对真实库运行未验证降级 SQL。

## 6. 任务执行与错误契约

状态：QUEUED → FETCHING → BUILDING → NEEDS_ADAPTATION / VALIDATING → NEEDS_REVIEW → PUBLISHING → PUBLISHED；运行阶段可进入 FAILED 或 CANCELLED。NEEDS_ADAPTATION 重新导入配置后 BUILDING；NEEDS_REVIEW 批准后 PUBLISHING；FAILED 重试创建新的 attempt。发现不支持模板进入 NEEDS_ADAPTATION，清楚标记 TEMPLATE_UNSUPPORTED。

只用一个应用进程写正式 DuckDB；lifespan 启停执行器，进程级文件锁阻止第二写进程。单写入调度涵盖旧 refresh、估值保存、任务变更与 CLI；网络 I/O 不持有数据库事务。内部队列仅用于唤醒，数据库任务记录才是真相来源。CLI 对正在运行服务通过 API 写入；离线迁移必须先取得同一进程锁。

启动恢复：未完成 attempt 标为 INTERRUPTED，验证已持久化输出哈希；可复用则进入下一步，否则新建 attempt 重跑。无法恢复的口径问题停留人工处理，不无限循环。取消使用 cancel_requested 和安全边界，在发布事务内最后检查。

网络错误最多三次总尝试，默认等待 2/4 秒并尊重服务端 Retry-After；大于当前执行窗口的等待记为 next_attempt_at。保留现有 SEC 2 RPS 共享限速；429/5xx 可重试，身份冲突、解析失败和证据缺失不可当网络错误重试。User-Agent 使用实际配置，缺失有效联系方式时给出配置提示；不能自动编造联系方式。

结构化错误沿用 `error.code/field/message`，扩展 retryable、details；常用代码 IDENTITY_CHANGED、AMBIGUOUS_SECURITY、TEMPLATE_UNSUPPORTED、SOURCE_UNAVAILABLE、EVIDENCE_MISSING、QUALITY_BLOCKED、REVIEW_STALE、TASK_CONFLICT、WRITER_BUSY。详情不包含凭证和任意本地文件内容。

## 7. 适配配置与质量规则

配置 schema v1 必须有 company_id、template、version、evidence、fiscal_calendar、metrics、segments、cash_debt、securities、applicability。内容仅声明数据和已安装解析器名称，禁止 eval、任意导入和执行脚本。通用规则继承结果必须展开进版本快照，不能以后随公共 YAML 变化。

示意字段结构（不是可直接批准的发行人配置）：

```yaml
schema_version: 1
company_id: '0000000001'
version: 1
template: us_gaap_operating_v1
fiscal_calendar: {year_end: '12-31', week_based: false}
metrics:
  REVENUE:
    concepts: ['us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax']
    unit: USD
    context: consolidated
    period: duration
    selection: latest_filed_same_basis
segments: {axes: [], reconciliation: explicit_eliminations}
cash_debt: {cash_components: [], debt_components: [], restricted_cash_policy: separate}
securities: []
applicability: {}
evidence: []
```

空的必需证据、现金债务定义和证券列表导致批准校验失败；示例 CIK 仅演示结构。候选自动生成只推荐在原始文件实际出现的 concept/context，不以标签名称相似直接判定正确。

### 7.1 强制检查

| 规则族 | 判定及反例 |
|---|---|
| IDENTITY | SEC 身份、申报发行人和证券来源一致；歧义阻塞；无证据不推断经营公司资格 |
| COVERAGE | 普通模板最近 3 完整财年、8 单季度，及最新已披露年度/季度；历史不足需核对 submissions 全部可用期间，无故缺一季度阻塞 |
| PERIOD | 按真实起止日与财年定义；累计差分只用同口径同财年兼容版本，Q4 = FY − 9M；不能跨重述版本相减 |
| CORE | 收入、营业利润、归属及合并净利润口径、基本/稀释 EPS 和加权股份、资产/负债/权益、经营/投资/融资现金流及期初末现金具备完整来源；缺失需模板规则明确允许 |
| BALANCE | 资产与负债、权益和适用中间权益项目勾稽；不能误将可赎回权益当缺口 |
| CASH | 期初现金 + 三类现金流 + 汇率/其他明确调整 = 同口径期末现金，处理受限现金 |
| EPS | 首先核对披露值和适配分子/分母；两类法/优先股/反稀释用显式规则，无法证明则阻塞该能力，不能无条件使用净利润/股数 |
| SEGMENTS | 报告分部与产品/地域拆分分开；合并收入 = 分部 + 抵销/未分配，禁止把产品/地域重复相加 |
| CASH_DEBT | 现金、短期投资、受限现金和短长期借款分别定义；租赁是否计入需明确，避免重复加总总项和子项 |
| LINEAGE | 所有正式数值有原始快照、申报 accession、期间、单位、concept/context 或表格定位及转换链；衍生值保留全部输入 ID |
| SECURITY | 行情交易所/股类/币种经核实；行情数据供应商不支持不能猜代码；每股价值另验换算 |

检查状态 PASS、FAIL、NOT_DISCLOSED、NOT_APPLICABLE、UNSUPPORTED；严重度 BLOCKER、WARNING。报告通过要求无 BLOCKER 失败、无未解决必需检查。NOT_DISCLOSED/NOT_APPLICABLE 必须有原始证据且规则允许；不能由用户自行选择绕过。

精度容差：从 XBRL decimals 或原文报表单位建立舍入区间；等式两侧区间相交视为通过，不使用无依据的全局百分比。衍生加减传播输入区间。缺精度时复核原表单位；仍未知则阻塞必需勾稽。合理诊断提示可 WARNING，但规则严重度属于审核配置，不能运行时降级。

Company Facts 无原始 context 的事实不能伪造 context_id；对核心数值回到申报 iXBRL/表格建立证据关联。表格证据允许通过，但需固定文件哈希、表格/单元格定位、单位和抽取方法，并人工核对。

## 8. 估值和可选模块

新证券估值状态 NEEDS_CONFIGURATION、UNSUPPORTED_MODEL、DATA_BLOCKED、READY、NEEDS_REVIEW。首次必须确认实际模型使用的增长路径、资本成本、再投资、终值及情景。历史 CAGR 仅参考，系统建议有来源标签，不复制 AAPL/MSFT 发行人假设给新公司。

有效确认绑定 security_id、publication_id、模型版本、假设哈希及行情身份；新财务发布后旧运行不改写，标为待复核。普通价格更新沿用现有过期规则，不把旧价格结果冒充最新结果。复制旧计划继承待复核状态。

财报币种/报价币种不一致、ADR 比例或多股类市值换算未验证，阻塞每股估值。确认假设不能解除这些数据门禁。银行等无适用模型时即使将来财报可发布，也明确 UNSUPPORTED_MODEL。

管理层、风险、护城河和问答只读取 publication 可用证据。未就绪时给原因，不用 demo 或虚构结论补齐。可选模块变更不悄悄改变核心财务版本；需要正式关联时创建新的 publication，复用未变 dataset 内容和适配批准。

## 9. API 契约

以下均位于 `/api/v1`，分页列表 limit 默认 50 最大 200，返回 next_cursor；时间 ISO 8601 UTC。

| 方法/路径 | 输入 | 输出/行为 |
|---|---|---|
| GET /companies | cursor、limit | items[{company_id,security_id,ticker,name,exchange,publication_id,quality_status,capabilities}] |
| POST /companies/discover | {ticker} | discovery_id、identity_hash、expires_at、candidates[]、eligibility、evidence；只读不创建公司 |
| POST /company-onboardings | {discovery_id,identity_hash,candidate_id} + Idempotency-Key | 202 {onboarding_id,state,revision,existing:false}；重复相同请求返回原结果 |
| GET /company-onboardings | cursor、limit | 任务摘要 |
| GET /company-onboardings/{id} | — | state、revision、steps、coverage、checks、blocking_reasons、actions |
| POST /company-onboardings/{id}/retry | {expected_revision} | 新 attempt 或 409 |
| POST /company-onboardings/{id}/cancel | {expected_revision} | 接受取消请求，若已发布 409 |
| GET /company-onboardings/{id}/review-package | — | 固定哈希 JSON 审查包 |
| POST /company-onboardings/{id}/profile | {expected_revision,profile} | 校验导入并重新构建；错误 422 |
| POST /company-onboardings/{id}/review | {expected_revision,fingerprint,decision,reviewer,note} | approve/reject；未过门禁 409，批准触发发布 |
| GET /companies/{ticker}/quality-report | security_id、publication_id 可选 | 固定发布报告；不返回候选作为正式报告 |
| PUT /companies/{ticker}/valuation-profile | security_id、publication_id、model_version、assumptions、confirmed | 复用假设表，返回 confirmation_id/status |

discovery 缓存有效期 15 分钟，注册表缓存 24 小时；过期可重新识别，离线缓存明确 fetched_at。创建任务仍核对身份哈希；缓存不足以判定身份则阻塞。Idempotency-Key 记录请求哈希，相同键不同输入返回 409；此记录持久化到 `api_idempotency(key, request_hash, response_json, created_at)`，不因重启失效。

现有 ticker 路由兼容单一无歧义证券；歧义返回 409 候选，前端传 security_id。请求的 publication 必须属于相同发行人，否则 404。不向客户端开放任意 SQL/路径读取。

## 10. 前端与交互实现

新增 AddCompanyDialog、OnboardingCenter、OnboardingDetail、QualityReportPanel；沿用现有 UI 组件与风格。Shell 读取动态列表；不得前端补回硬编码默认公司掩盖 API 失败。加载失败显示重试，空列表显示添加入口。

使用 api.ts 类型化封装；任务详情可见时 2 秒轮询，隐藏页面 10 秒，终态停止；卸载 AbortController 取消。请求序号绑定 onboarding_id/security_id/publication_id，迟到响应不覆盖新选择。不能因为局部刷新成功而清除旧估值待复核状态。

错误提示描述下一步：重试网络、配置来源联系信息、等待维护者适配、查看冲突证据。复核按钮只在强制检查通过且指纹当前时可用，后端仍重验。来源预览由已有来源机制提供固定版本文件，不从浏览器任意文件路径加载。

键盘可打开关闭对话框，焦点返回触发按钮，提交中禁重复提交。新增成功后刷新列表并定位证券，刷新浏览器后维持任务可查。

## 11. 测试数据与真实验收

首个端到端发行人选择 KO，第二个选择 COST，用于验证普通经营公司与不同财年/分部结构。这些是测试接入目标，不是在本文中声明其当前申报内容。开发阶段从 SEC 实时核实身份、资格、最新披露和 CIK，将访问 URL、采集时间、SHA 和 accession 固定在 fixture manifest；不要凭记忆填写。

fixture 存 `tests/fixtures/onboarding/<CIK>/`；golden 预期从原始报表人工核对，写明定位，不用待测解析器生成。网络测试与离线 golden 分离。负面测试可用清晰标记的合成 fixture：多股类同 CIK、重用 ticker、53 周财年、缺季度、重述、分部抵销、受限现金、反稀释、不同币种、ETF/未知资格、模板不支持。

在线来源不可用时记录具体阻塞，不替换成假在线数据，也不能声称全功能验收。可继续其他离线开发；最终在线验收仍保持未完成。

## 12. 完成标准

- 用户从页面提交 KO 和 COST，经历真实采集、专属配置、人工证据核对、门禁和发布；重启后可查任务与公司。
- 两家新增公司的规定期间、核心事实、分部和桥接均有独立核对证据；不能只测试“返回 200”。
- 重复添加不重复发行人/证券；多股类不共享行情；历史 ticker 不造成身份覆盖。
- 候选无法从正式接口泄漏；发布异常不改变旧 publication；并发请求不能混用版本。
- 取消、网络失败、服务中断、过期复核和数据冲突均有反例测试。
- AAPL/MSFT 旧数据和估值历史迁移保真，并完成新标准复核；如果真实数据不足，明确阻塞，不将旧版认证为通过。
- 新证券估值只有模型、数据和用户确认均通过时可运行；历史结果始终可追溯。
- 后端测试、TS、ESLint、浏览器、生产构建及迁移演练通过，质量审查没有未处理的重要问题。
- 完整用户教程和维护者适配教程可从仓库直接使用；进度表全部有证据，真实阻塞不打勾。

## 13. 开发文件与公共接口

以下是计划新增文件，不代表已存在。旧文件修改遵循第 2 节，不做无关拆分。

```text
equitylens/companies/models.py        # CompanyIdentity、SecurityIdentity、DiscoveryResult
equitylens/companies/registry.py      # 身份解析与注册事务
equitylens/companies/discovery.py     # 来源发现与资格证据
equitylens/onboarding/models.py      # TaskState、StepAttempt、TaskView
equitylens/onboarding/repository.py  # 持久化任务和幂等键
equitylens/onboarding/runner.py      # 步骤执行和中断恢复
equitylens/onboarding/service.py     # 申请、重试、取消、复核协调
equitylens/storage/writer.py         # 进程锁与统一串行写入
equitylens/storage/migrations.py     # 有序迁移与校验和
equitylens/publication/models.py     # Dataset、Publication、PublicationContext
equitylens/publication/repository.py # 固定版本读取与发布事务
equitylens/publication/builder.py    # 暂存计算与封存
equitylens/issuers/profile.py        # 配置 schema、哈希、加载校验
equitylens/issuers/candidate.py      # 证据驱动候选规则
equitylens/issuers/review.py         # 审查包与批准指纹
equitylens/quality/models.py         # CheckResult、QualityReport
equitylens/quality/engine.py         # 规则调度和报告
equitylens/quality/rules.py          # 确定性勾稽与区间计算
equitylens/api/company_routes.py     # 注册表与任务 API
equitylens/api/company_schemas.py    # 请求响应校验
config/issuers/schema-v1.json        # 与 Pydantic 导出 schema 一致
config/quality/us_gaap_operating_v1.yaml # 覆盖、必需项、规则严重度
apps/web/src/components/companies/AddCompanyDialog.tsx
apps/web/src/components/companies/OnboardingCenter.tsx
apps/web/src/components/companies/OnboardingDetail.tsx
apps/web/src/components/companies/QualityReportPanel.tsx
```

公共服务契约（在相应 models.py 用 Pydantic 定义返回模型；服务构造函数注入 repository/client/clock，不依赖测试全局真实库）：

```python
# CompanyRegistry
resolve(ticker: str, security_id: str | None = None) -> SecurityIdentity
# CompanyDiscovery
discover(ticker: str) -> DiscoveryResult
# OnboardingService
create(discovery_id: str, identity_hash: str, candidate_id: str,
       idempotency_key: str) -> TaskView
retry(task_id: str, expected_revision: int) -> TaskView
cancel(task_id: str, expected_revision: int) -> TaskView
# IssuerProfileService
import_profile(task_id: str, expected_revision: int, profile: dict) -> TaskView
# DatasetBuilder
build(task_id: str, profile_id: str) -> str  # dataset_id
# QualityEngine
validate(dataset_id: str) -> QualityReport
# ReviewService
review(task_id: str, expected_revision: int, fingerprint: str,
       decision: str, reviewer: str, note: str) -> TaskView
# PublicationRepository
publish(task_id: str, expected_revision: int, fingerprint: str) -> Publication
context(company_id: str, publication_id: str | None = None) -> PublicationContext
facts(context: PublicationContext) -> list[dict]
# OnboardingRunner
run_once() -> bool  # 是否处理一个可执行步骤
recover_interrupted() -> int
```

这些是接口声明，不是可直接执行的 Python 源码。每个任务实现接口时必须提供具体类型、错误及事务边界；不得用恒定返回值代替真实逻辑。TaskView 至少包含 id/state/revision/current_step/actions；PublicationContext 必含 company_id/publication_id/dataset_id/profile_id。

## 14. 按顺序执行的开发任务

每个任务结束时先验证，再提交该任务涉及的文件及进度表；`git add` 指定路径，不使用全库盲目暂存。以下测试代码是要求实现的行为反例；fixture 在对应测试文件或 tests/conftest.py 中实现，均使用 tmp_path、固定时钟和隔离库。

每个新增 Python 包同时创建 `__init__.py`。执行时优先复用现有测试 fixture，文中 `*_case` fixture 是该任务需要新增的隔离测试工厂，并非仓库已有 API；工厂必须调用真实实现，只有外部 HTTP、时钟和故障点可替身。

### T01：身份注册和可回滚迁移

文件：新增 companies/models.py、registry.py、storage/migrations.py；修改 domain/companies.py、spec/schema.sql、storage/duckdb_store.py；新增 tests/integration/test_company_registry.py、test_onboarding_migration.py。

接口：产生 CompanyRegistry.resolve 和 SecurityIdentity；证券不是 company 的别名。

- [x] 从真实库只读盘点 CIK、ticker、行情、来源与估值关联，保存迁移前报告。
- [x] 写身份隔离和迁移幂等反例：

```python
def test_share_classes_keep_separate_identity(registry_with_two_classes):
    a = registry_with_two_classes.resolve('EXAMPLE.A')
    b = registry_with_two_classes.resolve('EXAMPLE.B')
    assert a.company_id == b.company_id
    assert a.security_id != b.security_id
```

- [x] 运行 `uv run pytest tests/integration/test_company_registry.py tests/integration/test_onboarding_migration.py -q`，确认失败来自尚未实现的契约。
- [x] 实现第 4 节身份表、migration checksum、有效期重叠校验和 AAPL/MSFT 种子；对重名 ticker 必须抛 AMBIGUOUS_SECURITY，不取第一行。
- [x] 在备份副本执行两次迁移，验证旧记录摘要完全一致及二次无变化；同一测试命令通过。
- [x] 更新进度、提交 `feat: add issuer and security registry`。真实库此时不切换新行为。

### T02：固定数据版本和发布隔离

文件：新增 publication/models.py、repository.py、builder.py；修改 storage/duckdb_store.py、spec/schema.sql；新增 tests/integration/test_publication.py。

接口：实现 PublicationRepository.context/facts/publish 与 DatasetBuilder.build；后续请求只使用 PublicationContext。

- [x] 写候选隔离反例：

```python
def test_candidate_does_not_change_visible_facts(publication_case):
    before = publication_case.visible_facts()
    publication_case.build_candidate(revenue=999)
    assert publication_case.visible_facts() == before
```

- [x] 运行 `uv run pytest tests/integration/test_publication.py -q` 确认反例先失败。
- [x] 实现 dataset_row 类型校验、临时库封存、来源引用保护、发布指纹和原子指针切换；补充旧 legacy 快照。
- [x] 注入文件写后/事务提交前失败，验证旧事实与来源仍可读；对不同发行人 publication 请求拒绝。
- [x] 同一测试命令通过，更新进度并提交 `feat: publish immutable company datasets`。

### T03：统一写入与持久化任务

文件：新增 storage/writer.py、onboarding/models.py、repository.py、runner.py；修改 refresh/service.py、api/main.py、旧写入调用路径；新增 tests/integration/test_onboarding_runner.py。

接口：OnboardingRunner.run_once/recover_interrupted；所有正式库写入调用统一 writer，不允许 CLI 旁路。

- [x] 写中断恢复反例：

```python
def test_restart_does_not_duplicate_completed_step(runner_case):
    runner_case.persist_completed_fetch()
    runner_case.restart()
    runner_case.runner.recover_interrupted()
    runner_case.runner.run_once()
    assert runner_case.fetch_call_count == 1
```

- [x] 运行 `uv run pytest tests/integration/test_onboarding_runner.py -q` 确认失败。
- [x] 实现持久化状态转换、expected_revision、attempt 哈希、进程锁、串行 writer、取消检查和有上限重试；lifespan 启停和测试隔离。
- [x] 测第二进程写锁拒绝、发布时取消、同发行人重复任务、旧 refresh 与估值保存串行互斥；不要只测试线程锁本身。
- [x] 同一测试命令通过，更新进度并提交 `feat: persist and recover onboarding jobs`。

### T04：真实发现、采集和专属候选

文件：新增 companies/discovery.py、issuers/profile.py、candidate.py；修改 ingestion/sec/sync.py、filing_docs.py、normalization/ixbrl.py；新增 tests/unit/test_issuer_profile.py、tests/integration/test_company_discovery.py。

接口：CompanyDiscovery.discover、IssuerProfileService.import_profile（先提供验证部分）；采集输出固定 source manifest。

- [x] 写身份改变反例：

```python
def test_changed_identity_cannot_create_task(discovery_case):
    found = discovery_case.discover()
    discovery_case.change_registry_identity()
    response = discovery_case.create_from(found)
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'IDENTITY_CHANGED'
```

- [x] 运行 `uv run pytest tests/unit/test_issuer_profile.py tests/integration/test_company_discovery.py -q` 确认失败。
- [x] 实现身份缓存/过期核对、资格证据、SEC 历史申报分页采集；下载范围覆盖所需财年和季度，不只依赖最近 submissions 列表。
- [x] 实现严格配置 schema、展开通用映射、原始报表定位、候选未知字段待适配；不把自动候选标为复核通过。
- [x] 补充 ETF 拒绝、未知资格停留、多股类不重复抓财务、坏 YAML/可执行字段拒绝测试；同一测试命令通过。
- [x] 更新进度并提交 `feat: discover issuers and build evidence-backed profiles`。

### T05：质量规则和可解释报告

文件：新增 quality/models.py、engine.py、rules.py、config/quality/us_gaap_operating_v1.yaml；修改 normalization/fiscal_periods.py、normalize.py、segments.py；新增 tests/unit/test_onboarding_quality.py。

接口：QualityEngine.validate 返回报告及固定指纹；规则必须有 check_id 和 scope_key。

- [x] 写受限现金及累计季度反例：

```python
def test_cash_bridge_uses_same_cash_definition(quality_case):
    report = quality_case.cash_bridge(opening=100, operating=20,
        investing=-5, financing=-10, fx=2, closing=107)
    assert report.result == 'PASS'
    assert quality_case.cash_bridge(opening=100, operating=20,
        investing=-5, financing=-10, fx=2, closing=117).result == 'FAIL'
```

- [x] 运行 `uv run pytest tests/unit/test_onboarding_quality.py -q` 确认失败。
- [x] 实现第 7 节规则族、舍入区间和来源校验；复用现有期间解析但增加重述兼容条件。
- [x] 加入 EPS 非恒等式、分部抵销、无季度披露、来源损坏、NOT_APPLICABLE 无证据的失败样例；未支持行业明确阻塞。
- [x] 同一测试命令通过，更新进度并提交 `feat: enforce issuer quality gates`。

### T06：复核、维护者命令和发布闭环

文件：新增 issuers/review.py、onboarding/service.py；修改 cli.py、publication/repository.py；新增 tests/integration/test_issuer_review.py。

接口：ReviewService.review 和完整 IssuerProfileService.import_profile；绑定 profile/dataset/report/security 指纹。

- [x] 写复核失效反例：

```python
def test_old_approval_cannot_publish_new_candidate(review_case):
    approval = review_case.approve_current()
    review_case.change_profile_and_rebuild()
    result = review_case.publish_with(approval)
    assert result.error.code == 'REVIEW_STALE'
```

- [x] 运行 `uv run pytest tests/integration/test_issuer_review.py -q` 确认失败。
- [x] 实现审查包与证据定位、批准/拒绝记录、输入改变失效、规则失败拒绝批准和发布。
- [x] 增加 CLI：`equitylens onboarding show ID`、`export ID --output FILE`、`profile-import ID --file FILE --revision N`、`review ID --fingerprint HASH --revision N --reviewer NAME --note TEXT`。CLI 默认调用本地 API；连接失败不擅自直接写库。实际命令解析加入 `onboarding` 子命令组。
- [x] 同一测试命令通过，维护者通过命令完成一次合成申请闭环，更新进度并提交 `feat: add auditable issuer review workflow`。

### T07：API 与所有正式读取链路

文件：新增 api/company_routes.py、company_schemas.py；修改 api/main.py、routes.py、segments_service.py、domain/companies.py、market/service.py、research/engine.py 和公司相关读取；新增 tests/integration/test_onboarding_api.py。

接口：第 9 节所有路径；api_idempotency 持久化；正式响应携带 publication_id/security_id。

- [x] 写幂等和版本一致性反例：

```python
def test_repeated_request_returns_same_task(api_case):
    a = api_case.create(idempotency_key='request-1')
    b = api_case.create(idempotency_key='request-1')
    assert a.json()['onboarding_id'] == b.json()['onboarding_id']
```

- [x] 运行 `uv run pytest tests/integration/test_onboarding_api.py -q` 确认失败。
- [x] 实现接口与错误契约；正式读取通过 PublicationContext，旧 ticker 无歧义兼容；行情按 security_id，禁用不适用分析能力。
- [x] 测同幂等键不同输入、分页、超期发现、跨公司 publication、候选隔离、读取期间后台发布、取消终态。
- [x] 同一测试命令通过，更新进度并提交 `feat: expose company onboarding and versioned reads`。

### T08：估值门禁和证券指纹

文件：修改 valuation/service.py、defaults.py、market.py、api/routes.py、spec/schema.sql；新增 tests/integration/test_onboarding_valuation.py。

接口：PUT valuation-profile 复用既有表；确认指纹包括 publication/security/model/assumptions。

- [x] 写未确认估值反例：

```python
def test_new_security_requires_confirmed_assumptions(valuation_case):
    response = valuation_case.preview_without_confirmation()
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'VALUATION_NEEDS_CONFIGURATION'
```

- [x] 运行 `uv run pytest tests/integration/test_onboarding_valuation.py -q` 确认失败；将该错误码加入 API schema。
- [x] 实现确认表字段、模型/币种/股类能力校验、旧计划保真和新版本失效；草稿参数可验证，但正式计算/保存必须通过确认门禁。
- [x] 测复制待复核计划、异币种、未知 ADR 比例、发行人总股数不能配单一股类价格、旧运行不被更新覆盖。
- [x] 同一测试命令通过，更新进度并提交 `feat: gate valuations on verified issuer data`。

### T09：页面申请与质量报告

文件：新增第 13 节四个组件；修改 Shell.tsx、app/page.tsx、lib/api.ts、lib/types.ts、sections/ValuationSection.tsx；新增 apps/web/e2e/company-onboarding.spec.ts。

接口：前端仅消费第 9 节 API；固定 publication 贯穿页面，任务 revision 控制操作。

- [x] 阅读本地 Next.js 指南，沿用现有样式与请求模式。
- [x] 写浏览器用户路径：

```typescript
test('company appears only after publication', async ({ page }) => {
  await installOnboardingApiFixture(page); // 本文件定义：状态从 NEEDS_REVIEW 到 PUBLISHED
  await page.goto('/');
  await page.getByRole('button', { name: '添加公司', exact: true }).click();
  await page.getByLabel('股票代码').fill('KO');
  await page.getByRole('button', { name: '识别公司' }).click();
  await page.getByRole('button', { name: '确认并建档' }).click();
  await expect(page.getByText('等待维护者复核', { exact: true })).toBeVisible();
  await expect(page.getByTestId('company-list').getByText('KO', { exact: true })).toHaveCount(0);
});
```

- [x] 运行 `pnpm --dir apps/web exec playwright test e2e/company-onboarding.spec.ts` 确认行为失败。
- [x] 实现对话框、列表、详情、轮询、取消重试、审查包下载和质量报告；为上述测试定义 API fixture，另补发布后列表出现、重载、迟到响应和键盘焦点测试。
- [x] 运行 TypeScript、ESLint 和上述浏览器测试通过，更新进度并提交 `feat: add company onboarding pages`。

### T10：真实发行人接入、迁移验收与使用文档

文件：新增 config/issuers/<核实CIK>/<version>.yaml、tests/fixtures/onboarding/、tests/golden/test_onboarding_issuers.py；修改用户教程（若不存在则创建 docs/company-onboarding-user-guide.md）、新增 docs/company-onboarding-maintainer-guide.md。

接口：使用已完成的页面/CLI/API，不为 KO/COST 增加主业务硬编码特例。确有新解析行为时放入命名解析器并复核所有发行人。

- [x] 核实 KO/COST 当前身份和来源，固定官方快照、覆盖期间及独立手工预期值。
- [x] 建立 golden 测试，逐个核心指标比较值、期间、单位和原始证据引用；先让未适配案例失败。
- [ ] 顺序完成 KO、COST 配置、复核与页面发布，再完成 AAPL/MSFT 新标准复核；任一证据不足保留阻塞。
- [x] 执行 `uv run pytest tests/golden/test_onboarding_issuers.py -q`，新旧公司关键数值独立核对通过。
- [x] 在副本完整迁移、故障回滚与恢复演练；真实迁移仅使用已验证流程，保留备份地址和摘要；先确认服务已停止写入，不能覆盖用户新增数据。
- [x] 完成第 15 节全量验证、审查和两份教程；记录截图/报告位置及提交号，提交 `test: verify issuer onboarding end to end`。

T10 阻塞记录（2026-09-12）：KO/COST 配置、候选、golden 与复核路径已完成，但当前环境访问官方 SEC Archives iXBRL 返回 403。Company Facts 不包含真实报表行级 context/locator 或分部维度，质量正确保留 `LINEAGE.filing_context` 与 `SEGMENTS.reconciliation` BLOCKER；两家公司未批准、未发布。AAPL/MSFT 完成 profile v2 与新标准 golden，但正式库仍保持 `LEGACY_UNREVIEWED`。因此第三项按“任一证据不足保留阻塞”保持未勾选。

## 15. 验证命令、审查和交付

从仓库根目录执行（首先检查本机工具及锁文件；不自动更新依赖）：

```bash
uv sync --frozen
uv run pytest -q
pnpm --dir apps/web install --frozen-lockfile
pnpm --dir apps/web exec tsc --noEmit
pnpm --dir apps/web lint
pnpm --dir apps/web build
```

浏览器单独串行运行，避免生成 test-results 与 ESLint 扫描冲突。先检查浏览器是否安装，macOS 可复用：

```bash
PLAYWRIGHT_CHROME_PATH='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' pnpm --dir apps/web e2e
```

无此浏览器时使用项目对应 Playwright 浏览器，记录实际版本和命令，不能因为缺浏览器跳过验收。现有浏览器测试多为 API mock，需要另有真实后端/隔离库在线验收记录，不能互相替代。

审查聚焦：所有正式读取是否限定 publication，旧来源是否被删除，write lock 是否覆盖所有写入口，复核是否能被竞态绕过，股类/币种是否混用，NOT_APPLICABLE 是否有证据，测试预期是否独立于解析器。使用 requesting-code-review 技能时遵守用户顺序执行约束；无必要不派发子代理。

本功能阶段完成不是自动合并/远程发布授权。交付记录包括 commit、测试结果、迁移报告、实际在线接入记录、限制和待办。仓库当前未配置远端的历史情况需执行时核实，不自动创建远端仓库。

## 16. 新会话执行入口与完成追踪

把以下内容作为新会话首条任务即可：

> 请在 EquityLens 项目执行 docs/superpowers/plans/2026-09-11-company-onboarding.md。这是已经确认的高质量公司建档设计，采用系统采集校验和维护者专属适配复核。先读 AGENTS.md、知识库、主文档及 docs/reviews/2026-09-11-company-onboarding-progress.md，核查 Git 状态，按 T01—T10 顺序开发。每完成一部分先验证，再更新进度文档并提交。不要重新讨论已确定的产品方案，不要把候选数据或尚未验证的公司标为完成；遇到实际阻塞保留证据并继续可独立完成的步骤。

进度表是恢复执行入口，本文是需求和接口权威。变更接口时同步修改本文和所有调用任务。没有完成的步骤保留未勾选；用户手工完成的内容先审查实际代码和质量，不能只凭文档勾选跳过。

### 设计自审覆盖

身份/股类 → T01/T07；发布一致性/回滚 → T02/T10；中断恢复/写锁 → T03；真实发现/专属映射 → T04；规则/证据 → T05；复核闭环 → T06；API → T07；估值 → T08；页面 → T09；真实接入/迁移/教程 → T10。首期不支持的行业有申请状态和模型门禁，不冒充覆盖所有美股。没有依赖用户再次选择的产品未决项。
