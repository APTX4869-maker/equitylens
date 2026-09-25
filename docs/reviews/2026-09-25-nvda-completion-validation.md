# NVDA 研究补全验证记录

对应计划：`docs/superpowers/plans/2026-09-25-nvda-completion.md`

验证日期：2026-09-25（Asia/Shanghai）

## 结论

NVDA 的行情、管理层/Form 4、估值假设审核、确认后自动解锁和发布版本失效保护，均已在正式数据库的临时副本上通过。正式数据库与正式 raw 目录没有被本次演练写入。

桌面端完整用户路径通过；390×844 下的估值配置卡本身无横向溢出、五个控件标签齐全、确认顺序清晰、错误态可读。验收同时发现现有移动端把整个侧边栏隐藏，却没有公司和研究模块的替代导航，因此普通移动端用户无法自行进入 NVDA 估值页。该项属于计划外界面方案，保留为待用户确认的设计阻塞，不把它伪装为已完成。

## 自动化质量门

| 范围 | 命令 | 结果 |
|---|---|---|
| 后端全量 | `/Users/vincent/workspace/equitylens/.venv/bin/python -m pytest tests/unit tests/integration tests/golden -q` | `423 passed, 1 warning in 129.04s` |
| 前端 lint | `pnpm lint` | 通过 |
| TypeScript | `pnpm exec tsc --noEmit` | 通过 |
| Next.js 生产构建 | `pnpm build` | 通过 |
| 浏览器全量 | `PLAYWRIGHT_CHROME_PATH=... pnpm e2e` | `38 passed in 27.7s` |
| Task 5 聚焦回归 | setup/state/beginner/onboarding | `24 passed in 21.4s` |
| Task 6 聚焦回归 | setup/refresh/state | `12 passed in 16.6s` |

唯一 warning 是既有的 Starlette `TestClient`/`httpx` 上游弃用提示，不是 NVDA 行为跳过或失败。

## 副本与隔离

- 正式数据库：`/Users/vincent/workspace/equitylens/data/equitylens.duckdb`
- 演练目录：`/tmp/equitylens-nvda-rehearsal.d8UU3D`
- 演练数据库：`/tmp/equitylens-nvda-rehearsal.d8UU3D/equitylens.duckdb`
- 演练 raw：`/tmp/equitylens-nvda-rehearsal.d8UU3D/raw`
- 正式数据库 SHA-256：`5eaa4a8626ef4a0da29d875bef4831d1d3637d88f884540f09a76dacb433cc1c`
- 正式数据库记录的修改时间保持为 `2026-09-25 17:23:53 +0800`。

所有写入服务均显式接收演练数据库和 raw 路径。SEC 身份只通过演练进程环境传入，未写入源码、文档或 Git diff。

## 真实行情与管理层证据

行情同步结果：

- ticker：`NVDA`
- provider：`nasdaq`
- price：`223.705`
- observed_at：`Sep 25, 2026 10:49 AM ET`
- fetched_at：`2026-09-25 14:49:45`
- source：`https://api.nasdaq.com/api/quote/NVDA/info?assetclass=stocks`

管理层同步结果：

- 高管：10
- 薪酬行：15
- 董事：10
- 成功读取 Form 4 主文档：12
- 跳过文档：0
- 当前内部人交易：30

本轮 Form 4 accession：

- `0002152188-26-000005`
- `0001696841-26-000012`
- `0001696841-26-000010`
- `0001588670-26-000014`
- `0001347842-26-000015`
- `0001310264-26-000008`
- `0001283854-26-000010`
- `0001243821-26-000007`
- `0001199039-26-000014`
- `0001199039-26-000012`
- `0001197649-26-000012`
- `0001197647-26-000009`

`0001347842-26-000015` 成功下载和解析，但没有非衍生交易，作为 warning 保留；它不等同于下载或解析失败。

## 估值审核与版本失效

初始身份：

- security：`59b11c79-a02a-5248-abbb-b0678b2610e5`
- publication：`87ba7dd8-dce9-4767-9643-21b4001a8eee`
- model：`fcff_dcf.v2`
- draft：`NEEDS_CONFIGURATION`

提交草稿返回 200；随后 `/valuation/default` 返回 200，公司目录估值能力为 `READY`。

演练再发布同一固定数据集，生成 publication `085380d9-ee8b-428c-b1f6-9350c7c4fb69`。新发布的估值能力恢复为 `NEEDS_CONFIGURATION`，未确认的 default 返回 `VALUATION_NEEDS_CONFIGURATION`，再次提交旧 publication 的确认返回 `VALUATION_DRAFT_STALE`。这证明确认只绑定指定证券、发布版本、模型和完整假设，不会跨发布静默沿用。

## 浏览器验收

桌面 1440×900：

- 页面宽度与内容宽度均为 1440，无横向溢出。
- 显示证券、publication、`fcff_dcf.v2` 三项身份。
- 显示首年收入增速、第五年营业利润率、WACC、永续增长率、稳定期增量资本回报率五个有标签控件。
- Bear/Base/Bull 分别显示 `$44/$82/$112`。
- 勾选审核确认后，配置卡自动消失并直接出现 `$82` 估值工作区；没有浏览器 reload。

移动 390×844：

- viewport 与内容宽度均为 390，无横向溢出。
- 五个滑杆均有对应 label。
- 审核复选框位于确认按钮之前。
- 模拟 `VALUATION_DEFAULT_UNAVAILABLE` 时，错误卡左右边界为 14/376，错误说明和重新加载按钮可读。

截图保存在演练目录：`nvda-setup-desktop.png`、`nvda-setup-mobile.png`、`nvda-setup-error-mobile.png`、`nvda-ready-desktop.png`。这些是临时验证制品，不纳入 Git。

## 演练发现并修复的缺陷

1. `sync_management(store=...)` 内部 filing 查询曾重新打开默认数据库。现已把显式 store 贯穿到 DEF 14A/Form 4 列表，并增加回归测试。
2. TTM 当前值计算曾把 `fiscal_year=NULL` 的季度键与整数年份排序，导致真实 NVDA 行情派生触发 `TypeError`。现已统一过滤无有效财年的季度键，并保留完整期/单位门禁。
3. 发布事实单位 `usd` 与证券币种 `USD` 曾被误判不一致。现仅规范化大小写和空白，真正的 EUR/USD 不匹配仍由原测试阻断。

## 外部来源边界与待定项

- Nasdaq 行情是公开非授权研究源，不是交易报价；价格会随时间变化。
- SEC 和 Nasdaq 都是外部网络依赖；本记录只证明上述观察时间的真实请求成功。
- 移动端缺少公司/模块替代导航，用户无法从移动首页自行到达该估值卡。需要先确认移动导航方案，再单独实施和验收。
