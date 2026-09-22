# C10：NVDA 真实建档与发布验收

执行日期：2026-09-19—2026-09-22。按照 `docs/superpowers/plans/2026-09-19-company-onboarding-closure.md` 的 C10 执行。先在独立数据目录 `/tmp/equitylens-nvda-c10.XfGQKC` 验收，随后对正式 `data/` 单独备份、迁移和按门禁导入；没有用独立数据库覆盖正式库，也未改写原有 AAPL/MSFT 发布版本或用户行情快照。SEC 请求使用已配置的有效身份 User-Agent；此记录不保存联系邮箱。

## 真实任务与证据

| 项目 | 固定结果 |
|---|---|
| 公司 | NVDA / CIK `0001045810`，SEC 身份识别为 NVIDIA CORP |
| 建档任务 | `85171c6c-42e9-4abf-8b85-a405ec315969`，最终 `PUBLISHED`，revision 21，五阶段 5/5 |
| 固定抓取包 | `3e97afba-2f19-48db-ab5c-3d67faa67185` |
| Profile | `config/issuers/0001045810/1.yaml` 保留初次审查版本；`2.yaml` 为修正后批准版本 |
| 已封存数据集 | `9058a7fd-c7c7-44c4-b747-ffbd01ce4181`，968 条规范化事实、70 条分部事实 |
| 质量报告 | `f52e22dd-1de8-446b-903f-27f6e0d5e2f7`，`PASS`、零 BLOCKER；旧报告规则版本 `us_gaap_operating_v1.1`。之后现金桥语义修正，未来校验版本提升至 `v1.2`，不改写旧报告。 |
| 人工复核 | `625475fa-8357-4fbe-9995-187dce45f146`，批准 |
| 原子发布 | `95c57f23-84fc-49f7-9f94-99d6d85eb241`，2026-09-19 23:17:56，发布后目录显示 `VERIFIED` |

## 正式数据目录接入（2026-09-22）

在确认正式库无其他 writer 后，先将 `/Users/vincent/workspace/equitylens/data/equitylens.duckdb` 备份至 `/Users/vincent/.local/share/equitylens-migration-rehearsal/c10-main-NiDS7q/equitylens.duckdb`，原始文件和备份 SHA-256 均为 `9a32edde11ccd977d55e017a276ba031f6807f2459adee4078ab26163f881870`。先在 `/tmp/equitylens-c10-migration-B5CHHL/equitylens.duckdb` 复制品上连续执行两次 `DuckDBStore.init_schema()`，确认迁移幂等且 3 家原有公司与旧任务保留，再由正式 API 对原库执行迁移。

旧 NVDA 任务 `2dfbca4b-f4ea-423c-aaa9-06362cbce376` 原停在 `NEEDS_ADAPTATION` revision 3，但旧版没有固定抓取包。此时只提供“导入配置”会让维护者永远无法前进；新增回归后改为显示/允许“重新抓取”。正式任务重新抓取后生成 bundle `017379de-057f-4dc8-a622-b7654a056935`。仓库中的 Profile v2 绑定独立验收库的原始字节；正式目录同 accession 的 2024 10-K 和 2026 10-K 文件仅在末尾动态生成标识处不同，SHA 因此不同。系统原先会把 v2 自动套用并在 BUILD 抛出大段证据错误；新增回归后，固定抓取包与已安装配置不一致时改为安全暂停、生成候选，不越过证据门禁。

维护者核对两份文件正文和本次固定包后，把 37 条原有证据的文档 ID/SHA 精确重绑到正式包，保留指标、分部策略和 locator，形成 `config/issuers/0001045810/3.yaml`。正式任务上传 v3 后完成 BUILD/VALIDATE：质量报告 `3d67974e-e5be-4092-b3a4-cdcf9470caea`，规则 `us_gaap_operating_v1.2`，`PASS`，1005 项检查全部 PASS、零非 PASS。审核包 fingerprint `bdb2c74e234025e2fa4c301aca7582cb9083329958b1c4f7b664e56ff101da0f`；辅助维护审核记录 `defcf28f-cd8f-43cd-95d0-b3d7c97e3472` 批准后，原子发布 `87ba7dd8-dce9-4767-9643-21b4001a8eee`。正式任务最终 `PUBLISHED`、revision 17、五阶段 5/5。正式 API 公司目录为 NVDA/AAPL/MSFT；NVDA 概览指向该 publication、最新 FY2027 Q2，财务/分部披露日 2026-08-26。管理层/治理、行情、估值仍标记缺失。

独立审查指出最新版 v3 不能只依赖旧版 v2 golden。已将正式包 2024/2026 10-K 原始字节另存为两个压缩 fixture，在 `manifest.json` 固定原文与压缩文件 SHA；新增 golden 逐条确认 v3 的 37 项证据对应这两份文件的当前文档 ID、SHA 和 iXBRL locator。保留 v2 golden 作为独立验收历史，不篡改旧 Profile 或旧 fixture。

任务记录中的 FETCH 于 17:55:04—17:55:11 完成；初次 BUILD/VALIDATE 结果因 Profile 修正而标记 `STALE`，并非被静默覆盖。最终 BUILD 于 23:17:10—23:17:12、VALIDATE 于 23:17:12—23:17:13、PUBLISH 于 23:17:56 完成。第一版现金流映射/符号解释未通过质量门禁，维护者查看官方申报后导入第二版，再产生新的质量指纹和批准。系统没有绕过门禁或把候选标为发布。

官方 2026 10-K 原始字节固定为 `tests/fixtures/onboarding/0001045810/filing-2026-10k.html.gz`，索引和独立期望数值在相邻 `manifest.json`。来源为 accession `0001045810-26-000021`、截至 2026-01-25 的 10-K；解压原文 SHA-256 `467f9ed57e599a1ef9d3bc5aecc5693fb8592457e30c92c9c85f09148cb49b38`。Golden 测试验证收入 215.938B、经营现金流 102.718B、投资现金流 -52.228B、融资现金流 -48.474B、期末现金及受限现金 10.605B；Compute & Networking 193.479B + Graphics 22.459B = 合并收入 215.938B。断言的是官方文件中带 context/locator 的 iXBRL 行与 Profile 证据绑定，而非 Company Facts 替代物。

## 页面与读取验收

在独立数据目录启动 API（127.0.0.1:8000）和无扩展浏览器中的前端（127.0.0.1:3000），强制重载后核查：NVDA 自动出现在已发布目录，侧栏 `VERIFIED`；总览最近财报 FY2027 Q2，财务/分部披露日期均为 2026-08-26，不把 2026-09-19 的抓取时间当作披露时间；公司报告分部显示 Compute & Networking 193.5B、Graphics 22.5B。点击 TTM 营业收入 →“查看来源”，可见四期规范化事实、原始 `us-gaap:Revenues`、10-K/10-Q accession 和提交日。浏览器控制台未见应用错误。界面视觉、可访问树和来源抽屉截图在本次 Codex in-app browser 验收中检查；截图保留于本任务工具记录，未复制到仓库，验收标签页保留为用户可打开的本地页面。

正式库切回 127.0.0.1:8000 后重启前端，重新加载同一浏览器页：侧栏同时显示 NVDA `VERIFIED` 与 AAPL/MSFT `LEGACY_UNREVIEWED`；NVDA 总览 FY2027 Q2、财务/分部 2026-08-26、TTM 收入 303.0B。来源抽屉可见 `canonical-mappings.v4+profile.v3`、10-K accession `0001045810-26-000021` 及最新 10-Q `0001045810-26-000075`，控制台 error 列表为空。页面保留在 `http://127.0.0.1:3000/` 供用户复核。

读取边界修复：新发布数据的 facts、metrics、overview、segments、freshness 和来源树统一读取已发布数据集；旧 legacy 发布保持明确兼容路径。旧封存数据集缺 `filed_at` 时，按同一 source-document 的规范化事实 `as_known_at` 恢复披露日期，分部重述选最新披露而非任意行；新 BUILD 此后直接封存 `filed_at`/`report_date`。溯源只允许解析已发布行并校验 payload SHA，候选数据不因 GET 泄露；指定历史 publication 时来源抽屉会固定同一版本，异步切换公司/版本不会沿用旧响应。现金净变动含汇兑影响而单独 FX 未披露时，展示隐含 FX/其他差额，核对期初 + 已披露净变动 = 期末，不再错误要求三类活动现金流之和等于含 FX 净变动；此类推导另记部分覆盖告警，不能与完整披露等同。

## 自动验证与边界

- 聚焦后端：`uv run pytest tests/golden/test_onboarding_issuers.py tests/integration/test_onboarding_pipeline.py tests/integration/test_onboarding_api.py -q`：51 passed（初次 C10 闭环）；后续来源/重述/现金桥回归另行执行。
- 全量后端：正式库遗留路径与 v3 golden 补齐后最终 `uv run pytest -q`：412 passed、1 条 Starlette/httpx 弃用警告，132.16 秒。
- 浏览器：默认 3000 端口、真实隔离 API 可用时 `PLAYWRIGHT_PORT=3000 PLAYWRIGHT_CHROME_PATH=... pnpm --dir apps/web e2e`：最终 37 passed（29.5 秒）。旧来源抽屉用例的 API mock 未容纳新加的 `publication_id` 查询参数，已修正并重跑全量。
- `uv sync --frozen`、`pnpm --dir apps/web install --frozen-lockfile`、`uv run python -m compileall -q equitylens`、TypeScript、ESLint、Next build 和 `git diff --check` 均以退出码 0 完成。

此验收证明 NVDA 的财报和分部已在独立库及正式库分别按门禁发布，不表示行情、治理、估值均已同步。页面明确标注管理层/治理、行情快照、估值运行缺失；估值能力为 `NEEDS_CONFIGURATION`，不会把缺失模块伪装成已完成。行情刷新及公司页面数据刷新体验优化仍是后续单独待办，不在 C10 内宣称完成。
