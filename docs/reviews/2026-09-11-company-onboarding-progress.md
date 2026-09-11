# 高质量公司建档开发进度

主文档：`docs/superpowers/plans/2026-09-11-company-onboarding.md`

状态：T01—T04 已实现并验证；正在按顺序执行后续阶段。用户接受系统采集校验 + 维护者专属适配复核，要求顺序执行并逐阶段更新本文。

| 阶段 | 实现 | 验证 | 复核 | 证据/阻塞 |
|---|---|---|---|---|
| T01 身份注册与迁移 | 已完成 | 5 passed；真实库副本双次迁移通过 | 已自检 | `docs/reviews/2026-09-11-company-onboarding-pre-migration-inventory.md` |
| T02 发布版本隔离 | 已完成 | 5 passed；真实库副本双次迁移通过 | 已自检 | `docs/reviews/2026-09-11-company-onboarding-publication-rehearsal.md` |
| T03 持久化任务与写入 | 已完成 | 7 passed；T01—T03 回归 20 passed | 已自检 | writer 跨进程、恢复、取消、重试和真实刷新/估值互斥测试 |
| T04 发现采集与候选 | 已完成 | 12 passed；T01—T04 回归 29 passed | 已自检 | SEC 身份快照、历史分页、严格 profile 与候选反例 |
| T05 质量门槛 | 未开始 | 未运行 | 未开始 | — |
| T06 维护者复核闭环 | 未开始 | 未运行 | 未开始 | — |
| T07 API 与版本读取 | 未开始 | 未运行 | 未开始 | — |
| T08 估值门禁 | 未开始 | 未运行 | 未开始 | — |
| T09 页面流程 | 未开始 | 未运行 | 未开始 | — |
| T10 真实接入及完整验收 | 未开始 | 未运行 | 未开始 | — |

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
