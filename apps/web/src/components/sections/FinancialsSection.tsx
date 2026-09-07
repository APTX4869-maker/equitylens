"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { MarketQuote, MetricPoint, Fact } from "@/lib/types";
import { fmtMoney, fmtPct, signedPct } from "@/lib/format";
import { Card, Pill, ErrorBox, Spinner, ExplainNote } from "@/components/ui";
import { EChart, seriesOption } from "@/components/charts";

type Props = {
  ticker: string;
  market?: MarketQuote | null;
  onOpenMetric: (key: string, fact: Fact | null) => void;
};

const QUARTER_METRICS: { key: string; label: string; kind: "ratio" | "currency" | "growth" }[] = [
  { key: "REVENUE", label: "收入", kind: "currency" },
  { key: "REVENUE_GROWTH_YOY", label: "收入同比", kind: "growth" },
  { key: "GROSS_MARGIN", label: "毛利率", kind: "ratio" },
  { key: "OPERATING_MARGIN", label: "营业利润率", kind: "ratio" },
  { key: "FCF", label: "自由现金流", kind: "currency" },
];

const ANNUAL_METRICS: { key: string; label: string; kind: "currency" | "ratio" }[] = [
  { key: "REVENUE", label: "收入", kind: "currency" },
  { key: "GROSS_MARGIN", label: "毛利率", kind: "ratio" },
  { key: "OPERATING_MARGIN", label: "营业利润率", kind: "ratio" },
  { key: "FCF", label: "自由现金流", kind: "currency" },
];

const CARD_DEFS: { key: string; metric: string; label: string; note: string; k?: string }[] = [
  { key: "revenue", metric: "REVENUE", label: "营业收入", note: "TTM", k: "revenue" },
  { key: "grossMargin", metric: "GROSS_MARGIN", label: "毛利率", note: "最近季度", k: "grossMargin" },
  { key: "opMargin", metric: "OPERATING_MARGIN", label: "营业利润率", note: "最近季度", k: "opMargin" },
  { key: "netMargin", metric: "NET_MARGIN", label: "净利率", note: "最近季度", k: "netMargin" },
  { key: "fcf", metric: "FCF", label: "自由现金流", note: "TTM", k: "fcf" },
  { key: "fcfMargin", metric: "FCF_MARGIN", label: "自由现金流率", note: "最近季度", k: "fcfMargin" },
  { key: "netCash", metric: "NET_DEBT", label: "净现金 / 净债务", note: "最新资产负债表", k: "netCash" },
  { key: "roic", metric: "ROIC", label: "投入资本回报率 ROIC", note: "V0.1 暂不提供", k: "roic" },
  { key: "pe", metric: "P_E", label: "市盈率 P/E", note: "行情未同步", k: "pe" },
  { key: "pfcf", metric: "P_FCF", label: "市现率 P/FCF", note: "行情未同步", k: "pfcf" },
  { key: "fcfYield", metric: "FCF_YIELD", label: "FCF 收益率", note: "行情未同步", k: "fcfYield" },
];

export function FinancialsSection({ ticker, market, onOpenMetric }: Props) {
  const [view, setView] = useState<"quarter" | "annual">("quarter");
  const [activeMetric, setActiveMetric] = useState("REVENUE");
  const [quarterly, setQuarterly] = useState<Record<string, MetricPoint[]>>({});
  const [annual, setAnnual] = useState<Record<string, MetricPoint[]>>({});
  const [ttm, setTtm] = useState<Record<string, MetricPoint[]>>({});
  const [statement, setStatement] = useState<Fact[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const qKeys = [...new Set([...QUARTER_METRICS.map((m) => m.key), "NET_MARGIN", "FCF_MARGIN", "NET_DEBT"])];
        const aKeys = ANNUAL_METRICS.map((m) => m.key);
        const ttmKeys = ["REVENUE", "FCF", "GROSS_MARGIN", "OPERATING_MARGIN", "NET_MARGIN", "FCF_MARGIN"];
        const [qRes, aRes, tRes, sRes] = await Promise.all([
          api.metrics(ticker, qKeys, "quarterly", 12),
          api.metrics(ticker, aKeys, "annual", 10),
          api.metrics(ticker, ttmKeys, "ttm", 8),
          api.facts(
            ticker,
            ["REVENUE", "GROSS_PROFIT", "OPERATING_INCOME", "NET_INCOME", "OPERATING_CASH_FLOW", "CAPITAL_EXPENDITURES"],
            "annual",
            4
          ),
        ]);
        if (cancelled) return;
        const qMap: Record<string, MetricPoint[]> = {};
        for (const m of qRes.metrics) (qMap[m.metric] ??= []).push(m);
        const aMap: Record<string, MetricPoint[]> = {};
        for (const m of aRes.metrics) (aMap[m.metric] ??= []).push(m);
        const tMap: Record<string, MetricPoint[]> = {};
        for (const m of tRes.metrics) (tMap[m.metric] ??= []).push(m);
        setQuarterly(qMap);
        setAnnual(aMap);
        setTtm(tMap);
        setStatement(sRes.facts);
        setError(null);
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ticker, reloadKey]);

  const series = useMemo(
    () => (view === "quarter" ? quarterly[activeMetric] ?? [] : annual[activeMetric] ?? []),
    [view, activeMetric, quarterly, annual]
  );
  const labels = useMemo(() => series.map((p) => p.period), [series]);
  const values = useMemo(() => series.map((p) => p.value), [series]);
  const kind = useMemo(() => {
    const def = (view === "quarter" ? QUARTER_METRICS : ANNUAL_METRICS).find((m) => m.key === activeMetric);
    return def?.kind ?? "currency";
  }, [view, activeMetric]);

  const compare = useMemo(() => {
    if (view !== "quarter" || series.length < 5) return null;
    const last = series[series.length - 1];
    const prev = series[series.length - 2];
    const yago = series[series.length - 5];
    return { last, prev, yago };
  }, [series, view]);

  const chartOpt = useMemo(() => {
    const fmt = (v: number | null) => {
      if (v === null || v === undefined) return null;
      if (kind === "ratio") return Number((v * 100).toFixed(1));
      if (kind === "currency") return v / 1e9;
      return Number((v * 100).toFixed(1));
    };
    const unit = kind === "ratio" || kind === "growth" ? "%" : "$B";
    return seriesOption(labels, values.map(fmt), { unit, name: activeMetric });
  }, [labels, values, kind, activeMetric]);

  const cardValues = useMemo(() => {
    const out: Record<string, { value: string; note: string; fact: Fact | null }> = {};
    for (const def of CARD_DEFS) {
      if (def.key === "roic") {
        out[def.key] = { value: "—", note: def.note, fact: null };
        continue;
      }
      if (def.key === "pe") {
        // M8: P/E(TTM) = 行情市值 / 净利润TTM（确定性公式 pe_ttm.v1，后端计算）
        const pe = market?.status === "OK" ? market.derived?.pe_ttm : undefined;
        out[def.key] = pe != null
          ? { value: pe.toFixed(1), note: `P/E(TTM) · ${market?.quote?.provider_label ?? ""} · 确定性`, fact: null }
          : { value: "—", note: market?.derived?.pe_ttm_reason ?? "行情未同步", fact: null };
        continue;
      }
      if (def.key === "pfcf") {
        const pfcf = market?.status === "OK" ? market.derived?.pfcf_ttm : undefined;
        out[def.key] = pfcf != null
          ? { value: `${pfcf.toFixed(1)}×`, note: "P/FCF(TTM) · 确定性", fact: null }
          : { value: "—", note: market?.derived?.pfcf_ttm_reason ?? "行情未同步", fact: null };
        continue;
      }
      if (def.key === "fcfYield") {
        const fy = market?.status === "OK" ? market.derived?.fcf_yield_ttm : undefined;
        out[def.key] = fy != null
          ? { value: `${(fy * 100).toFixed(1)}%`, note: "FCF 收益率(TTM) · 确定性", fact: null }
          : { value: "—", note: "行情未同步", fact: null };
        continue;
      }
      if (def.key === "revenue" || def.key === "fcf") {
        // TTM-labeled cards read the backend TTM series (4 consecutive quarters),
        // never a front-end sum of quarterly points that would treat null as 0.
        const pts = ttm[def.metric] ?? [];
        const last = pts[pts.length - 1];
        const yago = pts[pts.length - 5]; // TTM 4 quarters earlier
        out[def.key] = {
          value: last?.value != null ? fmtMoney(last.value) : "—",
          note: last?.value != null && yago?.value != null && yago.value !== 0
            ? `${signedPct(last.value / yago.value - 1)} YoY（TTM）` : def.note,
          fact: last ? (last as unknown as Fact) : null,
        };
        continue;
      }
      const pts = quarterly[def.metric] ?? [];
      const last = pts[pts.length - 1];
      if (!last || last.value === null) {
        out[def.key] = { value: "—", note: def.note, fact: null };
        continue;
      }
      const isRatio = def.key.includes("Margin") || def.key === "fcfMargin";
      out[def.key] = {
        value: isRatio ? fmtPct(last.value) : fmtMoney(last.value),
        note: def.note,
        fact: last as unknown as Fact,
      };
    }
    return out;
  }, [quarterly, ttm, market]);

  const annualRows = useMemo(() => {
    const byMetric: Record<string, Fact[]> = {};
    for (const f of statement) (byMetric[f.metric] ??= []).push(f);
    const years = [...new Set(byMetric.REVENUE?.map((f) => f.fiscal_year).filter((y): y is number => y != null))].slice(-3);
    const rows: { label: string; values: (number | null)[]; major: boolean }[] = [
      { label: "营业收入", values: years.map((y) => byMetric.REVENUE?.find((f) => f.fiscal_year === y)?.value ?? null), major: true },
      { label: "毛利润", values: years.map((y) => byMetric.GROSS_PROFIT?.find((f) => f.fiscal_year === y)?.value ?? null), major: false },
      { label: "营业利润", values: years.map((y) => byMetric.OPERATING_INCOME?.find((f) => f.fiscal_year === y)?.value ?? null), major: true },
      { label: "净利润", values: years.map((y) => byMetric.NET_INCOME?.find((f) => f.fiscal_year === y)?.value ?? null), major: true },
      { label: "经营现金流", values: years.map((y) => byMetric.OPERATING_CASH_FLOW?.find((f) => f.fiscal_year === y)?.value ?? null), major: false },
      { label: "资本开支", values: years.map((y) => byMetric.CAPITAL_EXPENDITURES?.find((f) => f.fiscal_year === y)?.value ?? null), major: false },
    ];
    return { years, rows };
  }, [statement]);

  return (
    <>
      <div className="section-head">
        <div>
          <h2>财务分析</h2>
          <div className="card-sub beginner-only">默认先看最近 8-12 个季度：增长、利润率、现金流是否同向改善。</div>
          <div className="card-sub pro-only">SEC 规范化事实 · 季度/年度/TTM 切换 · 点击指标查看定义与来源</div>
        </div>
        <Pill tone="good">SEC 真实数据 · 不提供模拟质量分</Pill>
      </div>

      {error ? <ErrorBox message={error} onRetry={reload} /> : null}

      <Card className="quarter-chart-wrap">
        <div className="chart-top">
          <div>
            <div className="card-title">
              {(view === "quarter" ? QUARTER_METRICS : ANNUAL_METRICS).find((m) => m.key === activeMetric)?.label ?? activeMetric}
              {" · "}{view === "quarter" ? "最近季度趋势" : "年度趋势"}
            </div>
            <div className="card-sub">
              {view === "quarter" ? "看连续变化与拐点（单季为独立季度，非累计值）" : "看 5-10 年长期经营质量"}
            </div>
            <div className="card-sub" data-testid="financial-chart-unit">
              图表单位：{kind === "currency" ? "$B" : "%"}
            </div>
          </div>
          <div className="quarter-controls">
            <div className="seg">
              <button className={view === "quarter" ? "active" : ""} onClick={() => setView("quarter")}>季度</button>
              <button className={view === "annual" ? "active" : ""} onClick={() => setView("annual")}>年度</button>
            </div>
            <div className="seg">
              {(view === "quarter" ? QUARTER_METRICS : ANNUAL_METRICS).map((m) => (
                <button key={m.key} className={activeMetric === m.key ? "active" : ""} onClick={() => setActiveMetric(m.key)}>
                  {m.label}
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="chart-area">
          {chartOpt ? <EChart option={chartOpt} height={240} /> : <Spinner />}
        </div>
        {compare ? (
          <div className="quarter-compare">
            <div className="compare-chip">
              <span>本季度</span>
              <strong>{fmtCompare(compare.last.value, kind)}</strong>
            </div>
            <div className="compare-chip">
              <span>vs 上季度</span>
              <strong>{fmtDiff(compare.last.value, compare.prev.value, kind)}</strong>
            </div>
            <div className="compare-chip">
              <span>vs 去年同期</span>
              <strong>{fmtDiff(compare.last.value, compare.yago.value, kind)}</strong>
            </div>
          </div>
        ) : null}
        <div className="trend-summary">
          {compare ? (
            <>
              <strong>{QUARTER_METRICS.find((m) => m.key === activeMetric)?.label}：</strong>
              最新 {fmtCompare(compare.last.value, kind)}，上季 {fmtCompare(compare.prev.value, kind)}，去年同期 {fmtCompare(compare.yago.value, kind)}。
              当前{compare.last.value != null && compare.yago.value != null ? (compare.last.value >= compare.yago.value ? "高于去年同期" : "低于去年同期") : "无同比"}{activeMetric === "FCF" && compare.last.value != null && compare.yago.value != null && compare.last.value < compare.yago.value ? "，先检查 CapEx 与营运资本" : ""}。
            </>
          ) : null}
        </div>
      </Card>

      <div className="section-head" style={{ marginTop: 20 }}>
        <div>
          <h2>关键指标</h2>
          <div className="card-sub">点击任意指标查看定义、公式和常见误区；点击“查看来源”追踪 SEC 原始文件。</div>
        </div>
      </div>
      <div className="metrics">
        {CARD_DEFS.map((def) => {
          const cv = cardValues[def.key];
          return (
            <button
              key={def.key}
              className={`metric-card ${def.key === "roic" || def.key === "pe" ? "pro-only" : ""}`}
              onClick={() => onOpenMetric(def.k ?? def.key, cv.fact)}
            >
              <div className="metric-name">{def.label} <span className="help">?</span></div>
              <div className="metric-value">{cv.value}</div>
              <div className="metric-delta flat">{cv.note}</div>
            </button>
          );
        })}
      </div>

      <div className="grid grid-2" style={{ marginTop: 16 }}>
        <Card className="card-pad">
          <div className="card-title">三年简化财务表（SEC 年度真实数据）</div>
          <div className="card-sub">数字为十亿美元；每行均可在来源抽屉中溯源。</div>
          <div style={{ overflow: "auto", marginTop: 12 }}>
            <table className="statement-table">
              <thead>
                <tr>
                  <th>项目</th>
                  {annualRows.years.map((y) => <th key={y}>FY{y}</th>)}
                </tr>
              </thead>
              <tbody>
                {annualRows.rows.map((r, i) => (
                  <tr key={i} className={r.major ? "major" : ""}>
                    <td>{r.label}</td>
                    {r.values.map((v, j) => <td key={j}>{v != null ? `$${(v / 1e9).toFixed(1)}B` : "—"}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <Card className="card-pad">
          <div className="card-title">财务质量怎么读？</div>
          <ExplainNote num="1" title="收入增长只是起点">
            确认增长有没有转化成营业利润和自由现金流。
          </ExplainNote>
          <ExplainNote num="2" title="季度看拐点，年度看质量">
            季度适合发现趋势变化；5-10 年更适合判断商业模式是否稳定。
          </ExplainNote>
          <ExplainNote num="3" title="异常点要解释原因">
            利润率或 FCF 突然变化时，下一步应该直接跳到财报 / 来源抽屉寻找证据。
          </ExplainNote>
        </Card>
      </div>
    </>
  );
}

function fmtCompare(v: number | null, kind: string): string {
  if (v === null || v === undefined) return "—";
  if (kind === "ratio" || kind === "growth") return `${(v * 100).toFixed(1)}%`;
  if (kind === "currency") return fmtMoney(v);
  return String(v);
}

function fmtDiff(a: number | null, b: number | null, kind: string): string {
  if (a === null || a === undefined || b === null || b === undefined) return "—";
  if (kind === "currency") {
    const d = a - b;
    return `${d >= 0 ? "+" : ""}${fmtMoney(d)}`;
  }
  const d = (a - b) * 100;
  return `${d >= 0 ? "+" : ""}${d.toFixed(1)}pct`;
}
