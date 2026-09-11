# 高质量公司建档开发进度

主文档：`docs/superpowers/plans/2026-09-11-company-onboarding.md`

状态：T01 已实现并验证；正在按顺序执行后续阶段。用户接受系统采集校验 + 维护者专属适配复核，要求顺序执行并逐阶段更新本文。

| 阶段 | 实现 | 验证 | 复核 | 证据/阻塞 |
|---|---|---|---|---|
| T01 身份注册与迁移 | 已完成 | 5 passed；真实库副本双次迁移通过 | 已自检 | `docs/reviews/2026-09-11-company-onboarding-pre-migration-inventory.md` |
| T02 发布版本隔离 | 未开始 | 未运行 | 未开始 | — |
| T03 持久化任务与写入 | 未开始 | 未运行 | 未开始 | — |
| T04 发现采集与候选 | 未开始 | 未运行 | 未开始 | — |
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
