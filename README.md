# EquityLens — 本地优先的美股基本面研究系统

> 事实来自权威数据源（SEC EDGAR）；计算来自确定性代码；观点来自有证据支撑的研究层。
> 当前交付：**M1–M8.6** — AAPL/MSFT 的 SEC 财务事实与公开行情链路，以及总览、财务分析、业务构成、管理层、估值、风险、规则研究助手、护城河、承诺追踪和数据新鲜度页面。事实、计算、配置假设与证据缺口在界面中分别标注。

## 快速开始

```bash
# 1. 后端（Python 3.12 + uv）
uv sync                                   # 安装依赖（默认走清华 PyPI 镜像）
uv run equitylens sync AAPL MSFT          # 拉取并规范化 SEC 数据（首次联网，之后 --no-fetch 可离线重跑）
uv run equitylens sync-segments AAPL MSFT # 拉取 10-K/10-Q filing 并提取分部数据（M4）
uv run equitylens sync-management AAPL MSFT # 拉取 DEF 14A + Form 4 并提取管理层数据（M6）
uv run equitylens sync-quotes AAPL MSFT     # 同步真实行情：原始快照 + market_quote 行（M8，Nasdaq 主源/腾讯备源）
# 估值：无同步命令；DCF 直接基于已同步的 canonical facts，每次 POST /valuation/run 持久化
uv run uvicorn equitylens.api.main:app --port 8000

# 2. 前端（Node 24 + pnpm）
cd apps/web
pnpm install
pnpm dev                                  # http://localhost:3000（/api/v1/* 自动代理到 :8000）
```

打开 http://localhost:3000 → 搜索 AAPL → **公司总览**（真实 KPI）→ **财务分析** → 点击指标 → **查看来源**。

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
  → FastAPI → 前端（每个数字可点开 Source drawer 溯源到 accession/concept/期间）
```

- **LLM 永不参与数字**：`LLM → 数字 → 持久化` 被禁止（CODEX_START_HERE.md）。
- **重述语义**：API 默认 `latest_restated`（按 filing 日期选最新）；`point_in_time` 留待后续。
- **季度现金流**：10-Q 只报 YTD，Q2/Q3/Q4 独立季度由 YTD 链差分推导（公式
  `standalone_quarter.ytd_diff.v1`），缺失桶返回缺失而不是猜测。
- **状态可见**：`NORMALIZED`（官方披露）/ `CALCULATED`（系统计算，含公式与输入 ID）。

## 测试

```bash
uv run pytest -q                       # 后端全量：golden（官方财报/分部/14A/Form4/DCF/风险/研究/行情/护城河/承诺）+ 单元 + 集成
uv run python tests/e2e/smoke.py       # 浏览器冒烟（需两个服务已在跑）
cd apps/web && pnpm exec playwright test # 前端端到端回归（Playwright）
```

Golden 数据（AAPL FY2024 收入 391,035M、净利 93,736M；MSFT FY2024 收入 245,122M 等）
与官方财报核对，任一不符即阻塞该指标发布。

## 当前范围与边界（M1–M8.6）

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
- ⚠️ 支持的 ticker：AAPL、MSFT（V0.1 正确性优先于覆盖面）
- ⚠️ LLM 解释层：暂未接入（按用户决定）——确定性引擎已可用，插槽保留，永不生成财务数字

## Docker Compose（可选打包）

```bash
docker compose up -d --build                  # api(:8000) + web(:3000)
docker compose exec api uv run --no-sync equitylens sync AAPL MSFT
docker compose exec api uv run --no-sync equitylens sync-segments AAPL MSFT
docker compose exec api uv run --no-sync equitylens sync-management AAPL MSFT
docker compose exec api uv run --no-sync equitylens sync-quotes AAPL MSFT
# 打开 http://localhost:3000（web 通过 EQUITYLENS_API_URL 代理到 compose 内网 api:8000）
```

- `./data`（快照 + DuckDB）与 `./config`（只读）挂载进 api 容器；CLI 在容器内执行。
- web 为**开发模式容器**（热更新）；生产 standalone 构建留待硬化。
- 需 Docker Desktop/daemon；基础镜像 ghcr.io/astral-sh/uv、依赖走清华 PyPI 镜像。

## 常见问题
- **同步失败/想离线重跑**：`uv run equitylens sync AAPL MSFT --no-fetch` 只从本地快照重算。
- **SEC 拒绝请求**：请设置 `EQUITYLENS_USER_AGENT`（SEC fair-access 要求标识应用）。
