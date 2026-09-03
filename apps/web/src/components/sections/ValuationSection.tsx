"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { fmtMoney } from "@/lib/format";
import { Card, Pill, ErrorBox, Spinner } from "@/components/ui";
import { EChart, barOption } from "@/components/charts";

type RunResponse = {
  model_version: string;
  run_at: string;
  valuation_run_id?: string;
  assumptions: {
    inputs: {
      revenue_base: number; revenue_growth: number[]; op_margin_start: number;
      op_margin_end: number; tax_rate: number; da_pct: number; capex_pct: number;
      nwc_pct: number; wacc: number; terminal_growth: number; net_cash: number; shares: number;
    };
    meta: Record<string, { value?: number; source?: string; as_of?: string }>;
  };
  result: {
    fair_value_per_share: number; enterprise_value: number; equity_value: number;
    terminal_value: number; pv_terminal: number; sum_pv_fcff: number; net_cash: number;
    terminal_value_share: number; model_version: string;
    forecast: { year: number; revenue: number; op_margin: number; fcff: number; pv_fcff: number }[];
    warnings: string[];
  };
  scenarios: Record<"bear" | "base" | "bull", { result: { fair_value_per_share: number } }>;
  sensitivity: { wacc_grid: number[]; terminal_grid: number[]; rows: { wacc: number; values: (number | null)[] }[] };
  market?: {
    status: string;
    reason?: string;
    quote?: {
      price: number;
      currency: string;
      observed_at: string;
      provider: string;
      provider_label: string;
      source_url: string;
      fetched_at?: string;
      prev_close?: number | null;
    };
    derived?: {
      market_cap?: number;
      pe_ttm?: number;
      price_vs_fair_pct?: number;
      price_vs_fair_formula?: string;
      fair_value_per_share?: number;
    };
  };
  risk_free?: { value: number; as_of?: string; source?: string };
};

const RNG = {
  growth: { min: 0, max: 20, step: 0.5 },
  margin: { min: 5, max: 60, step: 0.5 },
  wacc: { min: 4, max: 15, step: 0.25 },
  terminal: { min: 0.5, max: 4, step: 0.25 },
};

export function ValuationSection({ ticker }: { ticker: string }) {
  const [base, setBase] = useState<RunResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [growth, setGrowth] = useState(8);
  const [margin, setMargin] = useState(33);
  const [wacc, setWacc] = useState(8.5);
  const [terminal, setTerminal] = useState(2.5);
  const [targetPrice, setTargetPrice] = useState("");
  const [reverse, setReverse] = useState<{ implied: number | null; hist: number | null; note?: string } | null>(null);
  const [loading, setLoading] = useState(false);

  // M8: when a synced quote is present, prefill the reverse-DCF reference once.
  const prefillReverseTarget = useCallback((d: RunResponse) => {
    const q = d.market?.status === "OK" ? d.market.quote : null;
    if (q && q.price > 0) {
      setTargetPrice((prev) => (prev === "" ? String(Math.round(q.price)) : prev));
    }
  }, []);

  const loadDefault = useCallback(async () => {
    try {
      const d = await api.fetchJson<RunResponse>(`/api/v1/companies/${ticker}/valuation/default`);
      setBase(d);
      const i = d.assumptions.inputs;
      setGrowth(i.revenue_growth[0] * 100);
      setMargin(i.op_margin_end * 100);
      setWacc(i.wacc * 100);
      setTerminal(i.terminal_growth * 100);
      prefillReverseTarget(d);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [ticker, prefillReverseTarget]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const d = await api.fetchJson<RunResponse>(`/api/v1/companies/${ticker}/valuation/default`);
        if (cancelled) return;
        setBase(d);
        const inp = d.assumptions.inputs;
        setGrowth(inp.revenue_growth[0] * 100);
        setMargin(inp.op_margin_end * 100);
        setWacc(inp.wacc * 100);
        setTerminal(inp.terminal_growth * 100);
        prefillReverseTarget(d);
        setError(null);
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ticker, prefillReverseTarget]);

  const recompute = useCallback(
    async (over: Partial<{ growth: number; margin: number; wacc: number; terminal: number }>) => {
      const g = over.growth ?? growth;
      const m = over.margin ?? margin;
      const w = over.wacc ?? wacc;
      const t = over.terminal ?? terminal;
      setLoading(true);
      try {
        // declining growth path anchored at the user CAGR
        const path = [g, g - 0.5, g - 1, g - 1.5, g - 2].map((x) => Math.max(0, x) / 100);
        const d = await api.fetchJson<RunResponse>(`/api/v1/companies/${ticker}/valuation/run`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            assumptions: { revenue_growth: path, op_margin_end: m / 100, wacc: w / 100, terminal_growth: t / 100 },
          }),
        });
        setBase(d);
        setError(null);
      } catch (e) {
        setError(String(e));
      } finally {
        setLoading(false);
      }
    },
    [ticker, growth, margin, wacc, terminal]
  );

  const runReverse = useCallback(async () => {
    const price = parseFloat(targetPrice);
    if (!price || price <= 0) return;    setLoading(true);
    try {
      const d = await api.fetchJson<{ implied_revenue_cagr: number | null; historical_revenue_cagr: number | null; no_root_reason?: string | null }>(
        `/api/v1/companies/${ticker}/valuation/reverse-dcf`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ target_price: price }),
        }
      );
      setReverse({ implied: d.implied_revenue_cagr, hist: d.historical_revenue_cagr, note: d.no_root_reason ?? undefined });
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [ticker, targetPrice]);

  const fair = base?.result.fair_value_per_share;
  const bear = base?.scenarios.bear.result.fair_value_per_share;
  const bull = base?.scenarios.bull.result.fair_value_per_share;
  const refRange = fair != null && bear != null && bull != null ? [Math.min(bear, bull), Math.max(bear, bull)] : null;

  const forecastChart = useMemo(() => {
    if (!base) return null;
    const f = base.result.forecast;
    return barOption(
      f.map((x) => `Y${x.year}`),
      [
        { name: "收入", data: f.map((x) => x.revenue), color: "#315ca8" },
        { name: "FCFF", data: f.map((x) => x.fcff), color: "#2c8b72" },
      ],
      { unit: "currency" }
    );
  }, [base]);

  if (error && !base) return <Card><ErrorBox message={error} onRetry={loadDefault} /></Card>;
  if (!base) return <Spinner label="正在加载估值引擎…" />;

  const i = base.assumptions.inputs;
  const meta = base.assumptions.meta;
  const mkt = base.market?.status === "OK" && base.market.quote ? base.market : null;
  const mktQuote = mkt?.quote ?? null;
  const premiumPct = mkt?.derived?.price_vs_fair_pct ?? null;

  return (
    <>
      <div className="demo-banner real">
        <strong>✓ 估值</strong> — FCFF DCF 由确定性引擎计算（公式版本 {base.result.model_version}），每次运行持久化可复现。
        {mktQuote
          ? ` 行情已同步（${mktQuote.provider_label} · ${mktQuote.observed_at}）：现价与公允价对比为确定性计算，非买卖建议。`
          : " 行情未同步：本地快照模式（运行 equitylens sync-quotes AAPL MSFT 后价格对比自动出现），DCF 与 reverse DCF 可先用假设探索。"}
      </div>
      <div className="section-head">
        <div>
          <h2>估值</h2>
          <div className="card-sub beginner-only">估值不是寻找一个“精确目标价”，而是回答：当前假设下价值在什么区间？</div>
          <div className="card-sub pro-only">5Y FCFF DCF · 情景 · 敏感性矩阵 · Reverse DCF（确定性重算）</div>
        </div>
        <Pill tone={mktQuote ? "good" : "warn"}>
          {mktQuote ? "行情已同步 · 现价 vs 公允价" : "模型可信度中 · 行情未同步"}
        </Pill>
      </div>

      <Card className="valuation-snapshot" style={{ marginBottom: 16 }}>
        <div className="card-sub">Reference Value Snapshot · SEC 事实 + 确定性模型（研究参考，非目标价）</div>
        <div className="value-band">
          <div>
            <span className="card-sub">市场价（快照）</span>
            {mktQuote ? (
              <>
                <div className="big-number" style={{ fontSize: 22 }}>${mktQuote.price.toFixed(2)}</div>
                <small className="muted">{mktQuote.provider_label} · {mktQuote.observed_at}</small>
                {premiumPct != null ? (
                  <div style={{ fontSize: 12, marginTop: 6 }}>
                    <span style={{ color: premiumPct > 5 ? "#c0392b" : premiumPct < -5 ? "#2c8b72" : "inherit", fontWeight: 600 }}>
                      较公允价 {premiumPct >= 0 ? "+" : ""}{premiumPct.toFixed(1)}%
                    </span>
                    <span className="muted">（现价 vs Base DCF ${base.result.fair_value_per_share.toFixed(0)}）</span>
                  </div>
                ) : null}
              </>
            ) : (
              <>
                <div className="big-number" style={{ fontSize: 22 }}>未同步</div>
                <small className="muted">{base.market?.reason ?? "行情未同步"}</small>
              </>
            )}
          </div>
          <div className="range-number">
            <span>DCF 参考区间（Bear–Bull）</span>
            <strong>{refRange ? `$${Math.round(refRange[0])} — $${Math.round(refRange[1])}` : "—"}</strong>
            <small className="muted">Base DCF：{fair != null ? `$${fair.toFixed(0)}` : "—"}</small>
          </div>
          <div style={{ textAlign: "right" }}>
            <span className="card-sub">终值占比</span>
            <div className="big-number" style={{ fontSize: 22 }}>{(base.result.terminal_value_share * 100).toFixed(0)}%</div>
          </div>
        </div>
        <div className="valuation-tags">
          <span>模型：{base.result.model_version}</span>
          <span>无风险利率 {base.risk_free ? `${(base.risk_free.value * 100).toFixed(2)}%（${base.risk_free.as_of ?? ""}）` : "—"}</span>
          <span>每次运行已持久化（{base.valuation_run_id ? "✔" : "default"}）</span>
        </div>
      </Card>

      {loading ? <div className="muted" style={{ marginBottom: 8 }}>正在重算…</div> : null}
      {error ? <Card style={{ marginBottom: 12 }}><ErrorBox message={error} onRetry={() => recompute({})} /></Card> : null}

      <div className="grid grid-2" style={{ marginTop: 12 }}>
        <Card className="card-pad" data-testid="dcf-model">
          <div className="section-head">
            <div>
              <div className="card-title">5-Year FCFF DCF</div>
              <div className="card-sub">代码计算现金流；改动假设即全量重算。开放 4 个最重要假设。</div>
            </div>
            <Pill tone="blue">FCFF DCF</Pill>
          </div>
          <div className="dcf-output">
            <div className="card-sub">当前假设下每股内在价值</div>
            <div className="fair" style={{ fontSize: 34 }}>${fair != null ? fair.toFixed(0) : "—"}</div>
            <div className="delta">净现金 ${fmtMoney(base.result.net_cash)} · 股本 {Math.round(i.shares / 1e6)}M（{i.shares > 1e9 ? "稀释加权" : "basis"}）</div>
          </div>
          <div className="dcf-sliders">
            <div className="dcf-control">
              <label>首年收入增速（路径逐年递减）</label>
              <input type="range" min={RNG.growth.min} max={RNG.growth.max} step={RNG.growth.step}
                value={growth} onChange={(e) => { setGrowth(Number(e.target.value)); recompute({ growth: Number(e.target.value) }); }} />
              <output>{growth.toFixed(1)}%</output>
            </div>
            <div className="dcf-control">
              <label>第5年营业利润率</label>
              <input type="range" min={RNG.margin.min} max={RNG.margin.max} step={RNG.margin.step}
                value={margin} onChange={(e) => { setMargin(Number(e.target.value)); recompute({ margin: Number(e.target.value) }); }} />
              <output>{margin.toFixed(1)}%</output>
            </div>
            <div className="dcf-control">
              <label>WACC 折现率</label>
              <input type="range" min={RNG.wacc.min} max={RNG.wacc.max} step={RNG.wacc.step}
                value={wacc} onChange={(e) => { setWacc(Number(e.target.value)); recompute({ wacc: Number(e.target.value) }); }} />
              <output>{wacc.toFixed(2)}%</output>
            </div>
            <div className="dcf-control">
              <label>永续增长率</label>
              <input type="range" min={RNG.terminal.min} max={RNG.terminal.max} step={RNG.terminal.step}
                value={terminal} onChange={(e) => { setTerminal(Number(e.target.value)); recompute({ terminal: Number(e.target.value) }); }} />
              <output>{terminal.toFixed(2)}%</output>
            </div>
          </div>
          {forecastChart ? <EChart option={forecastChart} height={200} /> : null}
          <div className="beginner-note">
            <div>💡</div>
            <div>
              <strong>四个滑杆在改什么？</strong>
              <p>收入增速决定生意能长多大；利润率决定每 100 元收入留下多少经营利润；WACC 决定未来现金今天值多少钱；永续增长决定终值。</p>
            </div>
          </div>
        </Card>

        <div>
          <Card className="card-pad" style={{ marginBottom: 14 }}>
            <div className="card-title">Scenario Valuation</div>
            <div className="scenario-grid-v3" style={{ gridTemplateColumns: "repeat(3,1fr)" }}>
              {(["bear", "base", "bull"] as const).map((k) => (
                <div className={`scenario-v3 ${k === "base" ? "base" : ""}`} key={k}>
                  <h3>{k === "bear" ? "Bear" : k === "base" ? "Base" : "Bull"} Case</h3>
                  <div className="value">${Math.round(base.scenarios[k].result.fair_value_per_share)}</div>
                </div>
              ))}
            </div>
            <div className="card-sub" style={{ marginTop: 8 }}>
              参考区间 {refRange ? `$${Math.round(refRange[0])}–$${Math.round(refRange[1])}` : ""} 由情景值得出；市场价不在区间内不构成买卖建议。
            </div>
          </Card>

          <Card className="card-pad" data-testid="sensitivity-matrix">
            <div className="card-title">Sensitivity Matrix（全量重算）</div>
            <div className="card-sub">固定增长与利润率，观察 WACC × 永续增长。</div>
            <div style={{ overflow: "auto", marginTop: 8 }}>
              <table className="sensitivity">
                <thead>
                  <tr>
                    <th>WACC ↓ / g →</th>
                    {base.sensitivity.terminal_grid.map((g) => <th key={g}>{(g * 100).toFixed(2)}%</th>)}
                  </tr>
                </thead>
                <tbody>
                  {base.sensitivity.rows.map((row) => (
                    <tr key={row.wacc}>
                      <th>{(row.wacc * 100).toFixed(2)}%</th>
                      {row.values.map((v, j) => (
                        <td key={j} className={Math.abs(row.wacc - i.wacc) < 0.001 && j === 2 ? "near" : ""}>
                          {v != null ? `$${Math.round(v)}` : "—"}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      </div>

      <div className="grid grid-2" style={{ marginTop: 16 }}>
        <Card className="card-pad" data-testid="reverse-dcf">
          <div className="card-title">Reverse DCF：某价格隐含什么增长？</div>
          <div className="card-sub">
            {mktQuote
              ? `行情已同步：现价 $${mktQuote.price.toFixed(2)} 已自动填入（可改价），反推市场当前价格隐含的增长。`
              : "行情未同步 → 输入一个参考价（例如当前市场价）做探索。"}
          </div>
          <div className="reverse-box" style={{ marginTop: 12 }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <input
                type="number" step="1" min="1"
                placeholder="输入参考价格 $"
                value={targetPrice}
                onChange={(e) => setTargetPrice(e.target.value)}
                style={{ padding: "8px 10px", borderRadius: 8, border: "1px solid var(--line)", width: 140 }}
              />
              <button className="tab-btn" onClick={runReverse} disabled={loading}>计算隐含增长</button>
            </div>
            {reverse ? (
              <div style={{ marginTop: 14 }}>
                <div className="reverse-number">
                  <span>市场隐含 5Y 收入 CAGR</span>
                  <strong>{reverse.implied != null ? `${(reverse.implied * 100).toFixed(1)}%` : "无根"}</strong>
                </div>
                <div className="card-sub">历史 5Y 收入 CAGR：{reverse.hist != null ? `${(reverse.hist * 100).toFixed(1)}%` : "—"}</div>
                <p className="card-sub">
                  {reverse.implied != null
                    ? `隐含 ${(reverse.implied * 100).toFixed(1)}% ${reverse.hist != null && reverse.implied > reverse.hist ? "高于" : "低于或接近"}历史 ${reverse.hist != null ? `${(reverse.hist * 100).toFixed(1)}%` : ""}。是否可信，需要证据。`
                    : reverse.note}
                </p>
              </div>
            ) : null}
          </div>
        </Card>
        <Card className="card-pad">
          <div className="card-title">假设来源（pro 模式）</div>
          <div className="card-sub">每个输入都可溯源；“assumption” 标注的项在有行情数据前是文档化假设。</div>
          <div style={{ marginTop: 10, fontSize: 11, color: "var(--muted)" }}>
            {Object.entries(meta).map(([k, v]) => (
              <div key={k} style={{ padding: "4px 0", borderBottom: "1px solid var(--line)" }}>
                <strong style={{ color: "var(--navy)" }}>{k}</strong>
                <span> = {typeof v.value === "number" ? (k === "beta" ? v.value.toFixed(2) : k.includes("pct") || k.includes("rate") || k.includes("margin") || k === "wacc" ? `${(v.value * 100).toFixed(1)}%` : v.value.toLocaleString()) : String(v.value ?? "")}</span>
                <div>{v.source}</div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </>
  );
}
