"use client";

import { useMemo } from "react";
import type { CompanyInfo, OverviewResponse } from "@/lib/types";
import { demoData, demoV2 } from "@/lib/demo";
import { fmtMoney, fmtPct, signedPct, fmtNumber } from "@/lib/format";
import { Card, Pill, SignalDot, SectionHead } from "@/components/ui";
import { EChart, seriesOption } from "@/components/charts";

type Props = {
  company: CompanyInfo | null;
  overview: OverviewResponse | null;
  error: string | null;
  onRetry: () => void;
  onOpenMetric: (key: string, fact: import("@/lib/types").Fact | null) => void;
  onGotoTab: (tab: import("@/components/Shell").TabKey) => void;
};

type KpiItem = { label: string; value: string; note: string; tone?: string };
function KpiCard({ label, value, note, tone }: KpiItem) {
  return (
    <div className="brief-card">
      <div className="brief-label">{label}</div>
      <div className="brief-value">{value}</div>
      <div className={`brief-note ${tone ?? ""}`}>{note}</div>
    </div>
  );
}

export function OverviewSection({ company, overview, error, onRetry, onOpenMetric, onGotoTab }: Props) {
  const ticker = company?.ticker ?? "AAPL";
  const demo = demoData[ticker];
  const demoBusiness = demoV2[ticker];
  const trend = overview?.trend ?? {};

  const kpis = useMemo<{ items: KpiItem[] } | null>(() => {
    if (!overview) return null;
    const k = overview.kpis;
    const rev = trend.revenue?.values ?? [];
    const growth = trend.revenueGrowth?.values ?? [];
    const gross = trend.grossMargin?.values ?? [];
    const op = trend.opMargin?.values ?? [];
    const fcf = trend.fcf?.values ?? [];
    const revTtm = k.TTM_REVENUE?.value ?? null;
    const revTtmPrev = rev.length >= 8 ? rev.slice(-8, -4).reduce((a: number, b) => a + (b ?? 0), 0) : null;
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
        },
        {
          label: "最近季度收入增速",
          value: latestGrowth !== null && latestGrowth !== undefined ? signedPct(latestGrowth) : "—",
          note: "同比（真实数据）",
          tone: latestGrowth !== null && latestGrowth !== undefined && latestGrowth > 0 ? "good" : "warn",
        },
        { label: "营业利润率", value: opLast != null ? fmtPct(opLast) : "—", note: "最近季度", tone: opLast != null && opLast > 0.2 ? "good" : "" },
        { label: "毛利率", value: grossLast != null ? fmtPct(grossLast) : "—", note: "最近季度", tone: grossLast != null && grossLast > 0.3 ? "good" : "" },
        { label: "TTM 自由现金流", value: fmtMoney(fcfTtm), note: "经营现金流 − 资本开支", tone: fcfTtm != null && fcfTtm > 0 ? "good" : "warn" },
        { label: "FCF 率", value: fcfMargin != null ? fmtPct(fcfMargin) : "—", note: "TTM", tone: fcfMargin != null && fcfMargin > 0.15 ? "good" : "" },
        { label: "净现金 / 净债务", value: netDebt != null ? fmtMoney(netDebt) : "—", note: netDebt != null && netDebt < 0 ? "净负债状态" : "净现金状态", tone: netDebt != null && netDebt < 0 ? "warn" : "good" },
        {
          label: "最新财报期",
          value: overview.latest_period ? `FY${overview.latest_period.fiscal_year} Q${overview.latest_period.fiscal_quarter}` : "—",
          note: "SEC 10-Q / 10-K",
          tone: "",
        },
      ],
    };
  }, [overview, trend]);

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

  const seg = demoBusiness.segments[0];
  const chartKeys: [string, string][] = [
    ["revenue", "收入"],
    ["revenueGrowth", "同比"],
    ["grossMargin", "毛利率"],
    ["opMargin", "营业利润率"],
    ["fcf", "FCF"],
  ];
  const activeChart = "revenue";
  const active = trend[activeChart];

  return (
    <>
      <div className="grid grid-2">
        <Card className="thesis-card">
          <h2>一句话理解公司（模拟）</h2>
          <div className="big">{demo.thesis}</div>
          <div className="thesis-meta">{demo.tags.map((t: any) => <span key={t}>{t}</span>)}</div>
        </Card>
        <Card className="score-wrap">
          <div className="card-sub">综合质量评分 · Demo framework（模拟）</div>
          <div className="summary-score">
            <strong>{demo.overall}</strong>
            <span>/ 100</span>
          </div>
          {Object.entries(demo.scores).map(([k, v]: [string, any]) => (
            <div className="score-row" key={k}>
              <div className="score-name">{k}</div>
              <div className="score-track"><div className="score-fill" style={{ width: `${v}%` }} /></div>
              <div className="score-num">{v}</div>
            </div>
          ))}
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
          <KpiCard key={k.label} label={k.label} value={k.value} note={k.note} tone={k.tone} />
        ))}
      </div>

      <div className="cockpit-grid" style={{ marginTop: 16 }}>
        <Card className="donut-card">
          <div className="section-head">
            <div>
              <h2>业务构成（模拟）</h2>
              <div className="card-sub">分部数据接入为后续阶段（M4）；当前显示 V3 原型数据。</div>
            </div>
            <button className="text-link" onClick={() => onGotoTab("business")}>完整下钻 →</button>
          </div>
          <div className="donut-layout">
            <div className="donut-wrap">
              <div className="donut-fallback">
                <strong>{seg.share}%</strong>
                <span>{seg.name}</span>
              </div>
              <div className="donut-legend">
                {demoBusiness.segments.map((s: any) => (
                  <div className="segment-btn" key={s.key}>
                    <span className="legend-swatch" style={{ background: s.color }} />
                    <span><strong>{s.name}</strong><br /><span>${s.revenue}B · YoY {s.yoy > 0 ? "+" : ""}{s.yoy}%</span></span>
                    <span className="segment-share">{s.share}%</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </Card>
        <Card className="quarter-chart-wrap">
          <div className="chart-top">
            <div>
              <div className="card-title">营业收入 · 最近 8 季（真实）</div>
              <div className="card-sub">连续季度比单点数字更容易看出经营方向</div>
            </div>
            <div className="seg">
              {chartKeys.map(([key, label]) => (
                <button key={key} className={activeChart === key ? "active" : ""}>{label}</button>
              ))}
            </div>
          </div>
          <div className="chart-area">
            {active && active.values.length ? (
              <EChart option={seriesOption(active.periods.slice(-8), active.values.slice(-8), { unit: "currency" })} height={230} />
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
              <p>经营现金流减去 CapEx 后才是更接近股东可支配的自由现金流。资本开支突然上升时，要追问它是在"投资未来"还是"维持现状"。</p>
            </div>
          </div>
        </Card>
        <Card className="card-pad">
          <div className="card-title">下一步重点跟踪（模拟）</div>
          <div className="card-sub">把研究从"看完报告"变成持续验证投资逻辑。</div>
          <div className="watch-list">
            {demoBusiness.watch.map((w: any, i: number) => (
              <div className="watch-item" key={i}>
                <div className="watch-num">{i + 1}</div>
                <div><strong>{w[0]}</strong><p>{w[1]}</p></div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </>
  );
}
