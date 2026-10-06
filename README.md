# EquityLens — 本地优先的美股基本面研究系统

> 事实来自权威数据源（SEC EDGAR）；计算来自确定性代码；观点来自有证据支撑的研究层。
> 当前形态：桌面网页端的个人研究工具。公司目录由已发布数据决定，各公司的模块能力与估值审核状态分别显示；不能把“已添加公司”理解为所有功能均可用。
> 最新实现、验证环境与未完成事项见 [桌面产品状态与交接索引](docs/reviews/2026-10-06-desktop-status.md)。尚未完成正式数据环境验收，不宣称整个平台已完全可投入使用。

## 快速开始

```bash
# 1. 后端（Python 3.12 + uv）
uv sync                                   # 安装依赖（默认走清华 PyPI 镜像）
# 替换为自己的真实联系邮箱；示例/默认 contact@example.com 不能用于公司识别
export EQUITYLENS_USER_AGENT='EquityLens personal research your-real-email@your-domain.com'
# 默认使用仓库 data/。测试应先复制数据目录，再显式选择副本，避免改动正式数据
# export EQUITYLENS_DATA_DIR='/absolute/path/to/data-copy'
uv run uvicorn equitylens.api.main:app --host 127.0.0.1 --port 8000

# 2. 前端（Node 24 + pnpm）
cd apps/web
pnpm install
pnpm dev                                  # http://localhost:3000（/api/v1/* 自动代理到 :8000）
```

打开 http://localhost:3000 → 选择已发布公司 → 公司总览 / 财务分析 → 点击指标查看来源。生产方式为在 `apps/web` 执行 `pnpm build`，再 `pnpm start --port 3000`；修改代码后须重新构建并重启生产服务。

启动不会自动导入演示公司。空目录请使用“添加公司”→识别法律实体/证券→建档→质量检查/人工核验→发布。建档中心与任务提示用于查看阻塞原因；“等待适配”需要维护者补版本化公司资料，不会因为继续等待自动成功。审核通过的数据才进入研究目录。

估值使用选定 publication 的冻结事实；需确认估值基准后才展示模型。五项假设包括收入增长、营业利润率、WACC、永续增长和稳定期 ROIC；预览不保存，明确保存才生成个人方案。利率展示来自确认/运行快照，不冒充当前实时利率。

配置从进程环境读取，不自动加载 `.env`：修改后重启 API。`EQUITYLENS_DB_PATH` 可单独覆盖数据库路径，但原始快照仍在 `EQUITYLENS_DATA_DIR/raw`；迁移时必须一起保留，详见状态索引中的正式环境待办。

## 目录结构

```text
equitylens/
  equitylens/                  # Python 后端包
    ingestion/sec/             # SEC HTTP client（限速 2 req/s、UA、重试）+ sync 编排
    normalization/             # XBRL/分部(segments)/DEF14A(proxy)/Form4(insider) 解析 + fiscal resolver
    metrics/engine.py          # 确定性指标引擎（版本化公式 + 输入事实记录）
    market/                    # 行情 provider（nasdaq/tencent）+ sync/quote 服务（M8）
    valuation/                 # FCFF DCF 引擎 + 假设/敏感性/reverse + 利率适配器（M5）
    domain/                    # companies/filings/risks(M7)/moat(M8.5)/management_score(M6)
    research/engine.py         # 证据优先问答引擎（M7，LLM 可插拔解释层）
    storage/                   # raw store（SHA-256 快照）+ DuckDB 存储层
    api/                       # FastAPI：/api/v1/companies|facts|metrics|overview|segments|
                               #   management|valuation|risks|moat|research|promises|market|provenance|sources
  apps/web/                    # Next.js 16 前端（中文 UI，初学者/专业双模式）
  config/                      # mappings/（概念→指标）、market/（行情源）、management/、valuation/、sources.yaml
  data/raw/sec/{cik}/          # 不可变 SEC 原始快照（submissions/companyfacts JSON + SHA-256）
  data/raw/market/{ticker}/    # 不可变行情原始快照（provider 响应 + SHA-256，M8）
  tests/                       # pytest：golden（官方财报/分部/14A/Form4/DCF/风险/AI/行情/护城河）+ unit + integration；e2e/smoke.py
  spec/                        # 从 handoff 包保留的 schema.sql / openapi_stub.yaml
```

## 数据管线（反幻觉红线）

```text
SEC data.sec.gov → 原始快照（落盘 + SHA-256）→ XBRL 解析 → 规范化事实（canonical_fact）
  → fiscal resolver（财年/季度/独立季度推导）→ 确定性指标（metric_value 公式+输入）
  → 候选版本与质量门禁 → 人工核验/发布 → publication 冻结事实与能力状态
  → FastAPI → 前端（证据可用的指标通过来源抽屉溯源；缺失/未披露不补猜测数字）
```

- **LLM 永不参与数字**：`LLM → 数字 → 持久化` 被禁止（CODEX_START_HERE.md）。
- **重述语义**：API 默认 `latest_restated`（按 filing 日期选最新）；`point_in_time` 留待后续。
- **季度现金流**：10-Q 只报 YTD，Q2/Q3/Q4 独立季度由 YTD 链差分推导（公式
  `standalone_quarter.ytd_diff.v1`），缺失桶返回缺失而不是猜测。
- **状态可见**：`NORMALIZED`（官方披露）/ `CALCULATED`（系统计算，含公式与输入 ID）。

## 测试

```bash
uv run pytest -q                       # 后端全量：golden（官方财报/分部/14A/Form4/DCF/风险/研究/行情/护城河/承诺）+ 单元 + 集成
uv run python tests/e2e/smoke.py --base-url http://localhost:3000 # 需两个服务已在跑；动态读取已发布目录
# 可用 --api-url http://127.0.0.1:8000/api/v1 或 --ticker NVDA；--help 查看选项
# 未安装 Playwright Chromium 时可用 --chrome-path '/absolute/path/to/Chrome'
cd apps/web && pnpm exec playwright test # 前端端到端回归（Playwright）
# 前端可设置 PLAYWRIGHT_PORT=3012、PLAYWRIGHT_CHROME_PATH='/absolute/path/to/Chrome'
# pnpm lint && pnpm exec vitest run && pnpm build
```

冒烟脚本检查已发布公司的八个模块导航、指标来源抽屉、研究问答、运行时错误和估值门禁；估值 READY 时另验滑杆预览重算与 Reverse DCF（不持久化）。`LIMITED` 是真实能力限制，不代表估值通过；仅已核实的缺发行人 defaults 草案错误可作为限制，未知错误仍失败。空目录/未发布 ticker 返回失败；不会导入、确认基准、保存方案或刷新数据。保存与并发等边界仍依靠完整回归及专项验证，冒烟通过不等于财务正确性或建档全链路验收。

Golden 数据与官方财报核对。测试库/拦截接口回归与真实数据副本验证分别记录，均不能代替正式库迁移与备份恢复验收。

## 模块能力与边界

以下为已实现的模块，不承诺每家已发布公司均有完整覆盖；应以公司能力面板、缺口提示和所选 publication 为准。

- ✅ 总览页 + 财务分析页：真实 SEC 数据（KPI、季度/年度趋势、指标卡、三年财务表、来源抽屉）
- ✅ 业务构成页（M4）：AAPL 地理分部/产品类别 + MSFT 三大分部，来自 10-K/10-Q iXBRL 维度解析；
  环形图、点击下钻、8 期趋势、Q4 由「年度−9 个月累计」推导、利润率 NOT_DISCLOSED 明确标注、来源可溯源
- ✅ 管理层页（M6）：DEF 14A 代理解析（核心高管/薪酬表/董事会）、Form 4 内部人交易、
  资本配置（回购/SBC/分红/CapEx/FCF/股本变化）、确定性 rubric 评分卡（证据覆盖率 <70% 时总分不可用）、观察项
- ✅ 估值页（M5）：确定性 FCFF DCF 引擎（新估值使用版本化 `fcff_dcf.v2`，兼容历史 v1；WACC>g 护栏；运行可持久化复现）、
  基准事实取自 SEC，预测项使用有版本和理由的公司配置；5 个参数可调整并全量重算，Bear/Base/Bull 使用公司情景故事与明确输入路径，
  高级敏感性矩阵、Reverse DCF 二分求根、假设来源、个人方案及刷新后复核状态均可追溯；
  行情已同步时显示"市场价(快照)"与较公允价偏离（price_vs_fair.v1，确定性计算），未同步则显式标注
- ✅ 风险页（M7）：确定性风险信号（增长/利润率/FCF 转化/资本开支强度/净债务/集中度/估值敏感性/管理层证据），
  每条带严重度、类别、证据与可回访的监控信号
- ✅ AI 研究助手（M7）：证据优先确定性规则检索引擎（意图路由→真实事实检索→结构化 claims + 证据 ID），
  离线可用；仅回答规则能覆盖的指标问题（收入增长/利润率/现金流/风险/估值/业务构成），未覆盖问题会说明能力范围；
  LLM 解释层可后续插拔，永不生成财务数字（确定性保证规则固定，不保证结论正确）
- ✅ 行情（M8）：`sync-quotes` 抓取 Nasdaq（主）/腾讯（备）→ SHA-256 原始快照 → market_quote 行（追加、可溯源）；
  估值页现价 vs 公允价偏离（确定性 price_vs_fair.v1）、财务页 P/E(TTM)=市值/净利TTM（pe_ttm.v1，证据 ID 可查）；
  未同步时显式"行情未同步"（不伪造价格）；两源均为非授权公开接口，仅研究用途
- ✅ 护城河（M8.5）：确定性护城河证据引擎——毛利率水平/趋势、营业利润率、FCF 自筹、资本强度、
  规模、分部/产品集中度、董事会独立性（14A 标注时），每条信号带证据 ID 与方法版本；
  无 SEC 数字证据的定性维度（品牌/网络效应/转换成本/专利/客户集中）显式列为"证据缺口"不评分——
  页面无模拟数据、无整体打分，结论只覆盖证据能支撑的部分
- ✅ 承诺追踪（M8.6）：Promise Tracker——证据卡（原话/发言人/日期/来源 URL + 可核对口径）由
  `ingest-promises` 导入（data/evidence/promises/{TICKER}/*.json）；读取时确定性 promise_verify.v1
  对照 SEC 事实自动判定 VERIFIED/BROKEN/OPEN/UNVERIFIED（含披露值 vs 承诺值对比与证据 ID），状态永不手填；
  兑现率在样本有意义前不计算
- ✅ 数据新鲜度（M8.6）：GET /companies/{t}/freshness 按模块报告 as-of（SEC 财务/分部/管理层/行情/估值运行），
  过期/缺失标色并在页面顶部"数据新鲜度"条展示，绝不静默使用旧数据
- ⚠️ 支持公司不写死为 AAPL/MSFT：目录仅列出已发布版本；新 ticker 需要公司资料/映射/质量门禁适配，不能保证任意公司一键导入或直接估值。
- ⚠️ LLM 解释层：暂未接入（按用户决定）——确定性引擎已可用，插槽保留，永不生成财务数字

## Docker Compose（可选打包）

```bash
docker compose up -d --build                  # api(:8000) + web(:3000)
# 打开 http://localhost:3000（web 通过 EQUITYLENS_API_URL 代理到 compose 内网 api:8000）
```

- `./data`（快照 + DuckDB）与 `./config`（只读）挂载进 api 容器；CLI 在容器内执行。
- web 为**开发模式容器**（热更新）；生产 standalone 构建留待硬化。
- 当前 Compose 的 API User-Agent 是固定旧值；公司识别前须将 `api.environment.EQUITYLENS_USER_AGENT` 改成含真实联系邮箱的标识。此路径尚未完成本轮 Docker 实测，不作为已验收部署方式。
- 需 Docker Desktop/daemon；基础镜像 ghcr.io/astral-sh/uv、依赖走清华 PyPI 镜像。

## 常见问题

- **同步与发布的区别**：`sync` / `sync-segments` / `sync-management` 是维护命令，不等价于新增公司审核发布；不能用它们绕过 publication 门禁。不要照旧版四条同步命令期待自动得到可估值公司。
- **行情维护**：`uv run equitylens sync-quotes NVDA` 同步指定公司的公开行情快照；成功拉取不保证已是最新交易时点。过期行情不参与现价比较，页面会明确标注。刷新后台持久化和跨页面恢复仍有待办。
- **同步失败/想离线重跑**：`uv run equitylens sync AAPL MSFT --no-fetch` 只从本地快照重算。
- **SEC 拒绝请求**：先确认 API 进程的 `EQUITYLENS_USER_AGENT` 含真实联系方式，再检查网络/限流；只在另一个终端设置变量不会更新正在运行的 API。
