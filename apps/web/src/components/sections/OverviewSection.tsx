/* eslint-disable @typescript-eslint/no-explicit-any */
"use client";

import { useCallback, useMemo, useState } from "react";
import type { CompanyInfo, Fact, OverviewResponse } from "@/lib/types";
import { fmtMoney, fmtPct, signedPct } from "@/lib/format";
import { Card, Pill } from "@/components/ui";
import { EChart, seriesOption } from "@/components/charts";

type Props = {
  company: CompanyInfo | null;
  overview: OverviewResponse | null;
  error: string | null;
  onRetry: () => void;
  onGotoTab: (tab: import("@/components/Shell").TabKey) => void;
  onOpenMetric: (key: string, fact: Fact | null) => void;
};

type KpiItem = { label: string; value: string; note: string; tone?: string; metricKey?: string; fact?: Fact | null };
function KpiCard({ label, value, note, tone, metricKey, fact, onOpenMetric }: KpiItem & { onOpenMetric: (k: string, fact: Fact | null) => void }) {
  return (
    <button
      className="brief-card"
      onClick={() => metricKey && onOpenMetric(metricKey, fact ?? null)}
      disabled={!metricKey}
      style={{ textAlign: "left", border: "none", background: "inherit", cursor: metricKey ? "pointer" : "default" }}
    >
      <div className="brief-label">{label}</div>
      <div className="brief-value">{value}</div>
      <div className={`brief-note ${tone ?? ""}`}>{note}</div>
    </button>
  );
}

export function OverviewSection({ company, overview, error, onRetry, onGotoTab, onOpenMetric }: Props) {
  const trend = useMemo(() => overview?.trend ?? {}, [overview]);
  const [activeChart, setActiveChart] = useState("revenue");

  const kpiFact = useCallback((key: string): Fact | null => {
    const item = overview?.kpis[key];
    if (!item || item.value === null || item.value === undefined) return null;
    return {
      metric: item.metric ?? key,
      period: item.period ?? "",
      period_type: item.frequency ?? "",
      fiscal_year: item.fiscal_year ?? null,
      fiscal_quarter: item.fiscal_quarter ?? null,
      period_start: null,
      period_end: item.period_end ?? null,
      instant_date: null,
      value: item.value,
      unit: item.unit ?? "",
      status: item.status ?? "UNKNOWN",
      canonical_fact_id: item.canonical_fact_id ?? null,
      result_id: item.result_id ?? null,
      provenance: {
        formula_id: item.formula_id ?? null,
        status: item.status ?? null,
      },
      input_fact_ids: item.input_fact_ids ?? [],
    };
  }, [overview]);

  const kpis = useMemo<{ items: KpiItem[] } | null>(() => {
    if (!overview) return null;
    const k = overview.kpis;
    const rev = trend.revenue?.values ?? [];
    const growth = trend.revenueGrowth?.values ?? [];
    const gross = trend.grossMargin?.values ?? [];
    const op = trend.opMargin?.values ?? [];
    const revTtm = k.TTM_REVENUE?.value ?? null;
    const priorRevenue = rev.slice(-8, -4);
    const revTtmPrev = priorRevenue.length === 4 && priorRevenue.every((value) => value != null)
      ? priorRevenue.reduce((sum: number, value) => sum + (value as number), 0)
      : null;
    const latestGrowth = growth.length ? growth[growth.length - 1] : null;
    const grossLast = gross.length ? gross[gross.length - 1] : null;
    const opLast = op.length ? op[op.length - 1] : null;
    const fcfTtm = k.TTM_FCF?.value ?? null;
    const fcfMargin = k.FCF_MARGIN?.value ?? null;
    const netDebt = k.NET_DEBT?.value ?? null;
    return {
      items: [
        {
          label: "TTM 营业收入",
          value: fmtMoney(revTtm),
          note: revTtm && revTtmPrev ? `${signedPct(revTtm / revTtmPrev - 1)} YoY` : "—",
          tone: revTtm && revTtmPrev && revTtm >= revTtmPrev ? "good" : "",
          metricKey: "revenue",
          fact: kpiFact("TTM_REVENUE"),
        },
        {
          label: "最近季度收入增速",
          value: latestGrowth !== null && latestGrowth !== undefined ? signedPct(latestGrowth) : "—",
          note: "同比（真实数据）",
          tone: latestGrowth !== null && latestGrowth !== undefined && latestGrowth > 0 ? "good" : "warn",
          metricKey: "revenue",
          fact: kpiFact("REVENUE_GROWTH_YOY"),
        },
        { label: "营业利润率", value: opLast != null ? fmtPct(opLast) : "—", note: "最近季度", tone: opLast != null && opLast > 0.2 ? "good" : "", metricKey: "opMargin", fact: kpiFact("OPERATING_MARGIN") },
        { label: "毛利率", value: grossLast != null ? fmtPct(grossLast) : "—", note: "最近季度", tone: grossLast != null && grossLast > 0.3 ? "good" : "", metricKey: "grossMargin", fact: kpiFact("GROSS_MARGIN") },
        { label: "TTM 自由现金流", value: fmtMoney(fcfTtm), note: "经营现金流 − 资本开支", tone: fcfTtm != null && fcfTtm > 0 ? "good" : "warn", metricKey: "fcf", fact: kpiFact("TTM_FCF") },
        { label: "FCF 率", value: fcfMargin != null ? fmtPct(fcfMargin) : "—", note: "最近季度", tone: fcfMargin != null && fcfMargin > 0.15 ? "good" : "", metricKey: "fcfMargin", fact: kpiFact("FCF_MARGIN") },
        { label: "净现金 / 净债务", value: netDebt != null ? fmtMoney(netDebt) : "—", note: netDebt != null && netDebt < 0 ? "净现金状态" : "净负债状态", tone: netDebt != null && netDebt > 0 ? "warn" : "good", metricKey: "netCash", fact: kpiFact("NET_DEBT") },
        {
          label: "最新财报期",
          value: overview.latest_period ? `FY${overview.latest_period.fiscal_year} Q${overview.latest_period.fiscal_quarter}` : "—",
          note: "SEC 10-Q / 10-K",
          tone: "",
        },
      ],
    };
  }, [overview, trend, kpiFact]);

  const signals = useMemo(() => {
    const growth = trend.revenueGrowth?.values ?? [];
    const gross = trend.grossMargin?.values ?? [];
    const fcf = trend.fcf?.values ?? [];
    const out: { tone: "good" | "warn"; cat: string; title: string; desc: string }[] = [];
    if (growth.length >= 2) {
      const last = growth[growth.length - 1];
      const prev = growth[growth.length - 2];
      out.push({
        tone: last != null && prev != null && last >= prev ? "good" : "warn",
        cat: "增长",
        title: last != null ? `收入同比 ${signedPct(last)}` : "增长数据缺失",
        desc:
          last != null && prev != null
            ? `较上季度${last >= prev ? "加速" : "放缓"}（${signedPct(prev)} → ${signedPct(last)}）`
            : "无法计算",
      });
    }
    if (gross.length >= 2) {
      const last = gross[gross.length - 1];
      const prev = gross[gross.length - 2];
      out.push({
        tone: last != null && prev != null && last >= prev ? "good" : "warn",
        cat: "盈利",
        title: `毛利率 ${last != null ? fmtPct(last) : "—"}`,
        desc: last != null && prev != null ? `环比 ${prev >= last ? "下降" : "提升"} ${fmtPct(Math.abs(last - prev))}` : "无法计算",
      });
    }
    if (fcf.length >= 2) {
      const last = fcf[fcf.length - 1];
      const prev = fcf[fcf.length - 2];
      out.push({
        tone: last != null && prev != null && last >= prev ? "good" : "warn",
        cat: "现金流",
        title: `季度 FCF ${fmtMoney(last)}`,
        desc: "季节性波动明显，建议看 TTM 而非单季（真实数据）",
      });
    }
    return out;
  }, [trend]);

  if (error) {
    return (
      <Card>
        <div style={{ color: "var(--bad)" }}>总览数据加载失败：{error}</div>
        <button className="tab-btn" onClick={onRetry}>重试</button>
      </Card>
    );
  }
  if (!overview) {
    return (
      <Card style={{ textAlign: "center", color: "var(--muted)" }}>
        <div className="spinner" /> 正在加载 SEC 真实财务数据…
      </Card>
    );
  }

  const chartKeys: { key: string; label: string; fallbackUnit: "currency" | "ratio" }[] = [
    { key: "revenue", label: "营业收入", fallbackUnit: "currency" },
    { key: "revenueGrowth", label: "收入同比", fallbackUnit: "ratio" },
    { key: "grossMargin", label: "毛利率", fallbackUnit: "ratio" },
    { key: "opMargin", label: "营业利润率", fallbackUnit: "ratio" },
    { key: "fcf", label: "自由现金流", fallbackUnit: "currency" },
  ];
  const active = trend[activeChart];
  const activeDefinition = chartKeys.find(({ key }) => key === activeChart) ?? chartKeys[0];
  const activeUnit = active?.unit === "ratio" ? "ratio" : activeDefinition.fallbackUnit;

  return (
    <>
      <div className="grid grid-2">
        <Card className="thesis-card">
          <h2>公司概况</h2>
          <div className="big">{company?.name ?? "—"}</div>
          <div className="thesis-meta">
            {[company?.ticker, company?.exchange, company?.fiscal_year_end ? `财年 ${company.fiscal_year_end}` : null]
              .filter(Boolean)
              .map((t) => <span key={t as string}>{t}</span>)}
          </div>
        </Card>
        <Card className="score-wrap">
          <div className="card-sub">综合质量评分 · 待核实</div>
          <div className="summary-score">
            <strong>—</strong>
            <span>暂不评分</span>
          </div>
          <p className="card-sub" style={{ marginTop: 10 }}>
            不编造综合分数：各维度的真实证据请分别查看业务构成、财务、风险、护城河、管理层页面。
          </p>
          <div style={{ marginTop: 8 }}>
            <button className="text-link" onClick={() => onGotoTab("risks")}>查看风险证据 →</button>
          </div>
        </Card>
      </div>

      <div className="section-head" style={{ marginTop: 20 }}>
        <div>
          <h2>关键简报</h2>
          <div className="card-sub">全部来自 SEC 真实数据；点击指标可查看解释与来源。</div>
        </div>
        <Pill tone="good">真实数据</Pill>
      </div>
      <div className="briefing-grid">
        {kpis?.items.map((k: KpiItem) => (
          <KpiCard key={k.label} label={k.label} value={k.value} note={k.note} tone={k.tone}
            metricKey={k.metricKey} fact={k.fact} onOpenMetric={onOpenMetric} />
        ))}
      </div>

      <div className="cockpit-grid" style={{ marginTop: 16 }}>
        <Card className="donut-card">
          <div className="section-head">
            <div>
              <h2>业务构成</h2>
              <div className="card-sub">来自 SEC 分部披露（真实）；概览只做入口，完整数据在业务构成页。</div>
            </div>
            <button className="text-link" onClick={() => onGotoTab("business")}>完整下钻 →</button>
          </div>
          <div className="card-sub" style={{ padding: 16 }}>
            分部收入与营业利润按 10-K/10-Q 披露口径解析，每项可溯源到原始文件；未单独披露的维度会显式标注。
          </div>
        </Card>
        <Card className="quarter-chart-wrap">
          <div className="chart-top">
            <div>
              <div className="card-title" data-testid="overview-chart-title">{activeDefinition.label} · 最近 8 季（真实）</div>
              <div className="card-sub">连续季度比单点数字更容易看出经营方向</div>
              <div className="card-sub" data-testid="overview-chart-unit">图表单位：{activeUnit === "currency" ? "$" : "%"}</div>
            </div>
            <div className="seg">
              {chartKeys.map(({ key, label }) => (
                <button key={key} className={activeChart === key ? "active" : ""} onClick={() => setActiveChart(key)}>{label}</button>
              ))}
            </div>
          </div>
          <div className="chart-area">
            {active && active.values.length ? (
              <EChart option={seriesOption(active.periods.slice(-8), active.values.slice(-8), { unit: activeUnit, name: activeDefinition.label })} height={230} />
            ) : null}
          </div>
        </Card>
      </div>

      <div className="section-head" style={{ marginTop: 20 }}>
        <div>
          <h2>经营趋势信号（真实）</h2>
          <div className="card-sub">系统把真实图表变化翻译成下一步该关注的问题。</div>
        </div>
      </div>
      <div className="signal-grid">
        {signals.map((s: any, i: number) => (
          <div className="signal-card" key={i}>
            <span className={`signal-badge ${s.tone}`}>{s.cat}</span>
            <h4>{s.title}</h4>
            <p>{s.desc}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-2" style={{ marginTop: 16 }}>
        <Card className="card-pad">
          <div className="card-title">现金流转化快照（真实）</div>
          <div className="card-sub">利润好不好，最终还要看能不能变成现金。</div>
          <div className="cash-waterfall">
            <div className="cash-step">
              <label>TTM 经营现金流</label>
              <div className="cash-bar"><div className="cash-fill" style={{ width: "100%" }} /></div>
              <strong>{fmtMoney(overview.kpis.TTM_OPERATING_CASH_FLOW?.value)}</strong>
            </div>
            <div className="cash-step">
              <label>TTM 资本开支</label>
              <div className="cash-bar"><div className="cash-fill" style={{ width: "100%" }} /></div>
              <strong>-{fmtMoney(overview.kpis.TTM_CAPITAL_EXPENDITURES?.value)}</strong>
            </div>
            <div className="cash-step">
              <label>TTM 自由现金流</label>
              <div className="cash-bar"><div className="cash-fill" style={{ width: "100%" }} /></div>
              <strong>{fmtMoney(overview.kpis.TTM_FCF?.value)}</strong>
            </div>
          </div>
          <div className="beginner-note beginner-only">
            <div>💡</div>
            <div>
              <strong>这里重点看什么？</strong>
              <p>经营现金流减去 CapEx 后才是更接近股东可支配的自由现金流。资本开支突然上升时，要追问它是在“投资未来”还是“维持现状”。</p>
            </div>
          </div>
        </Card>
        <Card className="card-pad">
          <div className="card-title">下一步重点跟踪</div>
          <div className="card-sub">基于真实信号与承诺追踪，而不是模拟清单。</div>
          <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 8 }}>
            <button className="text-link" onClick={() => onGotoTab("risks")}>查看确定性风险信号 →</button>
            <button className="text-link" onClick={() => onGotoTab("management")}>查看管理层承诺追踪 →</button>
          </div>
        </Card>
      </div>
    </>
  );
}
