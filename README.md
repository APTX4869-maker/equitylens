# EquityLens — 本地优先的美股基本面研究系统

> 事实来自权威数据源（SEC EDGAR）；计算来自确定性代码；观点来自有证据支撑的研究层。
> 当前交付：**M1–M4** — AAPL/MSFT 真实 SEC 财务数据全链路 + 总览/财务分析/业务构成页 + 溯源抽屉。

## 快速开始

```bash
# 1. 后端（Python 3.12 + uv）
uv sync                                   # 安装依赖（默认走清华 PyPI 镜像）
uv run equitylens sync AAPL MSFT          # 拉取并规范化 SEC 数据（首次联网，之后 --no-fetch 可离线重跑）
uv run equitylens sync-segments AAPL MSFT # 拉取 10-K/10-Q filing 并提取分部数据（M4）
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
  equitylens/            # Python 后端包
    ingestion/sec/       # SEC HTTP client（限速 2 req/s、UA、重试）+ sync 编排
    normalization/       # XBRL 解析、版本化概念映射、fiscal-period resolver（YTD→单季）
    metrics/engine.py    # 确定性指标引擎（版本化公式 + 输入事实记录）
    storage/             # raw store（SHA-256 快照）+ DuckDB 存储层
    api/                 # FastAPI：/api/v1/companies|facts|metrics|overview|provenance
  apps/web/              # Next.js 16 前端（中文 UI，初学者/专业双模式）
  config/mappings/       # canonical_mappings.yaml（版本化概念→指标映射）
  data/raw/sec/{cik}/    # 不可变原始快照（submissions/companyfacts JSON + SHA-256）
  tests/                 # pytest：golden（官方财报核对）+ unit；e2e/smoke.py（Playwright）
  spec/                  # 从 handoff 包保留的 schema.sql / openapi_stub.yaml
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
uv run pytest -q                       # 62 个测试：golden（对照官方 10-K/10-Q/分部）+ 单元 + 集成
uv run python tests/e2e/smoke.py       # 浏览器冒烟（需两个服务已在跑）
```

Golden 数据（AAPL FY2024 收入 391,035M、净利 93,736M；MSFT FY2024 收入 245,122M 等）
与官方财报核对，任一不符即阻塞该指标发布。

## 当前范围与边界（M1–M3）

- ✅ 总览页 + 财务分析页：真实 SEC 数据（KPI、季度/年度趋势、指标卡、三年财务表、来源抽屉）
- ✅ 业务构成页（M4）：AAPL 地理分部/产品类别 + MSFT 三大分部，来自 10-K/10-Q iXBRL 维度解析；
  环形图、点击下钻、8 期趋势、Q4 由「年度−9 个月累计」推导、利润率 NOT_DISCLOSED 明确标注、来源可溯源
- ⚠️ 护城河/管理层/估值/风险/AI 助手：V3 原型**模拟数据**（页面显著标注），M5–M7 接入
- ⚠️ 行情价格：未配置（按约定先做 provider 抽象），估值页显示"行情未配置"
- ⚠️ 支持的 ticker：AAPL、MSFT（V0.1 正确性优先于覆盖面）

## 常见问题

- **uv 安装慢**：pyproject.toml 已配置清华镜像 `[tool.uv] index-url`，可自行改回官方源。
- **同步失败/想离线重跑**：`uv run equitylens sync AAPL MSFT --no-fetch` 只从本地快照重算。
- **SEC 拒绝请求**：请设置 `EQUITYLENS_USER_AGENT`（SEC fair-access 要求标识应用）。
