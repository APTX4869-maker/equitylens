"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { fmtMoney } from "@/lib/format";
import { Card, Pill, ErrorBox, Spinner } from "@/components/ui";
import { EChart, barOption } from "@/components/charts";
import {
  buildPreviewRequest,
  draftFingerprint,
  draftFromInputs,
  updateDraft,
  type DcfInputs,
  type DraftEdit,
} from "@/lib/valuationDraft";

type RunResponse = {
  ticker?: string;
  input_fingerprint?: string;
  model_version: string;
  run_at: string;
  valuation_run_id?: string;
  assumptions: {
    inputs: DcfInputs;
    meta: Record<string, { value?: number; source?: string; as_of?: string }>;
  };
  result: {
    fair_value_per_share: number; enterprise_value: number; equity_value: number;
    terminal_value: number; pv_terminal: number; sum_pv_fcff: number; net_cash: number;
    terminal_value_share: number; model_version: string;
    forecast: { year: number; revenue: number; op_margin: number; fcff: number; pv_fcff: number }[];
    warnings: string[];
  };
  scenarios: Record<"bear" | "base" | "bull", {
    label: string;
    status: "OK" | "UNAVAILABLE";
    reason: string | null;
    result: { fair_value_per_share: number } | null;
    inputs: {
      revenue_growth: number[]; op_margin_end: number; wacc: number; terminal_growth: number;
    };
  }>;
  sensitivity: { wacc_grid: number[]; terminal_grid: number[]; rows: { wacc: number; values: (number | null)[] }[] };
  model_quality?: {
    data_completeness: string;
    estimated_inputs: string[];
    terminal_value_share: number;
    scenario_dispersion: number | null;
    applicability: string;
    note: string;
  };
  market?: {
    status: string;
    reason?: string;
    stale?: boolean;
    stale_reason?: string | null;
    quote_age_days?: number | null;
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
  growth: { min: -100, max: 20, step: 0.5 },
  margin: { min: 5, max: 60, step: 0.5 },
  wacc: { min: 4, max: 15, step: 0.25 },
  terminal: { min: 0.5, max: 4, step: 0.25 },
};

export function ValuationSection({ ticker }: { ticker: string }) {
  const [base, setBase] = useState<RunResponse | null>(null);
  const [draft, setDraft] = useState<DcfInputs | null>(null);
  const [appliedInputs, setAppliedInputs] = useState<DcfInputs | null>(null);
  const [appliedFingerprint, setAppliedFingerprint] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [targetPrice, setTargetPrice] = useState("");
  const [reverse, setReverse] = useState<{ implied: number | null; hist: number | null; note?: string; stale?: boolean } | null>(null);
  const [loading, setLoading] = useState(false);
  const [saved, setSaved] = useState(false);
  const [marginOfSafety, setMarginOfSafety] = useState("");
  const [planName, setPlanName] = useState("");
  const [plans, setPlans] = useState<{ plan_id: string; name: string; reference_price: number | null; margin_of_safety: number }[]>([]);
  const [planMsg, setPlanMsg] = useState<string | null>(null);
  const reqSeq = useRef(0);
  const draftRef = useRef<DcfInputs | null>(null);

  useEffect(() => {
    draftRef.current = draft;
  }, [draft]);

  // M8: when a synced quote is present, prefill the reverse-DCF reference once,
  // preserving the exact market decimals (326.68 stays 326.68, not 327).
  const prefillReverseTarget = useCallback((d: RunResponse) => {
    const q = d.market?.status === "OK" ? d.market.quote : null;
    if (q && q.price > 0) {
      setTargetPrice((prev) => (prev === "" ? String(q.price) : prev));
    }
  }, []);

  const applyResponse = useCallback((d: RunResponse, persist: boolean) => {
    const inputs = draftFromInputs(d.assumptions.inputs);
    setBase(d);
    setDraft(inputs);
    draftRef.current = inputs;
    setAppliedInputs(inputs);
    setAppliedFingerprint(d.input_fingerprint ?? null);
    setSaved(persist);
    setError(null);
  }, []);

  const loadPlans = useCallback(async () => {
    try {
      const d = await api.fetchJson<{ plans: { plan_id: string; name: string; reference_price: number | null; margin_of_safety: number }[] }>(
        `/api/v1/companies/${ticker}/valuation/plans`
      );
      setPlans(d.plans ?? []);
    } catch {
      // plans are optional; a fetch failure must not block the valuation page
    }
  }, [ticker]);

  const preview = useCallback(
    async (next: DcfInputs, persist = false) => {
      const seq = ++reqSeq.current;
      setLoading(true);
      setError(null);
      try {
        const d = await api.fetchJson<RunResponse>(`/api/v1/companies/${ticker}/valuation/run`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(buildPreviewRequest(next, persist)),
        });
        if (seq !== reqSeq.current) return; // stale response: ignore
        applyResponse(d, persist);
      } catch (e) {
        if (seq !== reqSeq.current) return;
        // a failed newest request leaves the prior result stale; save stays off
        setError(String(e));
      } finally {
        if (seq === reqSeq.current) setLoading(false);
      }
    },
    [ticker, applyResponse]
  );

  // Editing a field updates the COMPLETE draft synchronously before any fetch,
  // so a later edit can never re-send an older growth path (V03/U02).
  const edit = useCallback(
    (e: DraftEdit) => {
      const current = draftRef.current;
      if (!current) return;
      const next = updateDraft(current, e);
      draftRef.current = next;
      setDraft(next);
      setReverse((r) => (r ? { ...r, stale: true } : r));
      void preview(next, false);
    },
    [preview]
  );

  const loadDefault = useCallback(async () => {
    try {
      const d = await api.fetchJson<RunResponse>(`/api/v1/companies/${ticker}/valuation/default`);
      applyResponse(d, false);
      prefillReverseTarget(d);
      setReverse(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [ticker, applyResponse, prefillReverseTarget]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const d = await api.fetchJson<RunResponse>(`/api/v1/companies/${ticker}/valuation/default`);
        if (cancelled) return;
        applyResponse(d, false);
        prefillReverseTarget(d);
        setReverse(null);
        setError(null);
        void loadPlans();
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ticker, applyResponse, prefillReverseTarget, loadPlans]);

  const saveRun = useCallback(() => {
    const current = draftRef.current;
    if (!current) return;
    void preview(current, true);
  }, [preview]);

  const savePlan = useCallback(async () => {
    const pct = parseFloat(marginOfSafety);
    if (Number.isNaN(pct) || pct < 0 || pct >= 100) {
      setPlanMsg("安全边际必须是 0–99 之间的百分比（0 表示无边际）");
      return;
    }
    const refValue = base?.result.fair_value_per_share;
    if (refValue == null) {
      setPlanMsg("当前没有可用的参考估值");
      return;
    }
    try {
      const d = await api.fetchJson<{ reference_price: number | null; reference_price_reason?: string }>(
        `/api/v1/companies/${ticker}/valuation/plans`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: planName || undefined,
            reference_value: refValue,
            reference_source: "base_dcf",
            margin_of_safety: pct / 100,
            assumptions: base?.assumptions.inputs ?? {},
          }),
        }
      );
      setPlanMsg(d.reference_price != null
        ? `已保存方案：参考价 $${d.reference_price.toFixed(2)}`
        : `已保存（仅供研究）：${d.reference_price_reason ?? "不可买入"}`);
      setPlanName("");
      void loadPlans();
    } catch (e) {
      setPlanMsg(String(e));
    }
  }, [ticker, marginOfSafety, planName, base, loadPlans]);

  const runReverse = useCallback(async () => {
    const price = parseFloat(targetPrice);
    if (!price || price <= 0) return;
    const current = draftRef.current;
    if (!current) return;
    setLoading(true);
    try {
      const d = await api.fetchJson<{ implied_revenue_cagr: number | null; historical_revenue_cagr: number | null; no_root_reason?: string | null }>(
        `/api/v1/companies/${ticker}/valuation/reverse-dcf`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ target_price: price, assumptions: buildPreviewRequest(current).assumptions }),
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
  const bear = base?.scenarios.bear.result?.fair_value_per_share;
  const bull = base?.scenarios.bull.result?.fair_value_per_share;
  const refRange = fair != null && bear != null && bull != null ? [Math.min(bear, bull), Math.max(bear, bull)] : null;

  const growthPct = draft ? draft.revenue_growth[0] * 100 : 0;
  const marginPct = draft ? draft.op_margin_end * 100 : 0;
  const waccPct = draft ? draft.wacc * 100 : 0;
  const terminalPct = draft ? draft.terminal_growth * 100 : 0;

  // The visible result is saveable only when the applied inputs still equal the
  // current draft and there is no pending/failed request.
  const isDirty = appliedInputs != null && draft != null
    ? draftFingerprint(draft) !== draftFingerprint(appliedInputs)
    : true;
  const canSave = !isDirty && !error && !loading && appliedFingerprint != null;

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

  const i = draft ?? base.assumptions.inputs;
  const meta = base.assumptions.meta;
  const mkt = base.market && base.market.quote ? base.market : null;
  const mktQuote = mkt?.quote ?? null;
  const mktStale = base.market?.status === "STALE";
  const premiumPct = !mktStale ? (mkt?.derived?.price_vs_fair_pct ?? null) : null;

  return (
    <>
      <div className="demo-banner real">
        <strong>✓ 估值</strong> — FCFF DCF 由确定性引擎计算（公式版本 {base.result.model_version}），保存后记录完整不可变输入快照。
        {mktQuote
          ? (mktStale
            ? ` 行情已同步但过期（${mktQuote.observed_at}），不参与现价与公允价对比。`
            : ` 行情已同步（${mktQuote.provider_label} · ${mktQuote.observed_at}）：现价与公允价对比为确定性计算，非买卖建议。`)
          : " 行情未同步：本地快照模式（运行 equitylens sync-quotes AAPL MSFT 后价格对比自动出现），DCF 与 reverse DCF 可先用假设探索。"}
        {" "}该 FCFF DCF 适用于当前支持的高质量科技公司；银行/REIT/亏损成长等类型不直接套用此模型。
      </div>
      <div className="section-head">
        <div>
          <h2>估值</h2>
          <div className="card-sub beginner-only">估值不是寻找一个“精确目标价”，而是回答：当前假设下价值在什么区间？</div>
          <div className="card-sub pro-only">5Y FCFF DCF · 情景 · 敏感性矩阵 · Reverse DCF（确定性重算）</div>
        </div>
        <Pill tone={mktStale ? "warn" : mktQuote ? "good" : "warn"}>
          {mktStale ? "行情已过期" : mktQuote ? "行情已同步 · 现价 vs 公允价" : "行情未同步"}
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
                {mktStale ? (
                  <div style={{ fontSize: 12, marginTop: 6, color: "#b58900", fontWeight: 600 }}>
                    行情已过期 · 不参与现价对比{base.market?.stale_reason ? `（${base.market.stale_reason}）` : ""}
                  </div>
                ) : premiumPct != null ? (
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
          <span>{saved ? "已保存方案" : isDirty ? "未保存（预览已过期）" : "未保存（预览）"}</span>
          <button className="tab-btn" onClick={saveRun} disabled={!canSave}>
            保存本次运行
          </button>
        </div>
      </Card>

      {loading ? <div className="muted" style={{ marginBottom: 8 }}>正在重算…</div> : null}
      {error ? <Card style={{ marginBottom: 12 }}><ErrorBox message={error} onRetry={() => draftRef.current && preview(draftRef.current)} /></Card> : null}

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
            <div className="fair" style={{ fontSize: 34 }} data-testid="fair-value">${fair != null ? fair.toFixed(0) : "—"}</div>
            <div className="delta">净现金 ${fmtMoney(base.result.net_cash)} · 股本 {Math.round(i.shares / 1e6)}M（{i.shares > 1e9 ? "稀释加权" : "basis"}）</div>
          </div>
          <div className="dcf-sliders">
            <div className="dcf-control">
              <label htmlFor="growth-slider">首年收入增速（路径逐年递减）</label>
              <input id="growth-slider" type="range" min={RNG.growth.min} max={RNG.growth.max} step={RNG.growth.step}
                value={growthPct} onChange={(e) => edit({ field: "growth", percent: Number(e.target.value) })} />
              <output>{growthPct.toFixed(1)}%</output>
            </div>
            <div className="dcf-control">
              <label htmlFor="margin-slider">第5年营业利润率</label>
              <input id="margin-slider" type="range" min={RNG.margin.min} max={RNG.margin.max} step={RNG.margin.step}
                value={marginPct} onChange={(e) => edit({ field: "margin", percent: Number(e.target.value) })} />
              <output>{marginPct.toFixed(1)}%</output>
            </div>
            <div className="dcf-control">
              <label htmlFor="wacc-slider">WACC 折现率</label>
              <input id="wacc-slider" type="range" min={RNG.wacc.min} max={RNG.wacc.max} step={RNG.wacc.step}
                value={waccPct} onChange={(e) => edit({ field: "wacc", percent: Number(e.target.value) })} />
              <output>{waccPct.toFixed(2)}%</output>
            </div>
            <div className="dcf-control">
              <label htmlFor="terminal-slider">永续增长率</label>
              <input id="terminal-slider" type="range" min={RNG.terminal.min} max={RNG.terminal.max} step={RNG.terminal.step}
                value={terminalPct} onChange={(e) => edit({ field: "terminal", percent: Number(e.target.value) })} />
              <output>{terminalPct.toFixed(2)}%</output>
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
              {(["bear", "base", "bull"] as const).map((k) => {
                const sc = base.scenarios[k];
                return (
                  <div className={`scenario-v3 ${k === "base" ? "base" : ""}`} key={k}>
                    <h3>{k === "bear" ? "悲观 (Bear)" : k === "base" ? "中性 (Base)" : "乐观 (Bull)"}</h3>
                    {sc.result ? (
                      <div className="value">${Math.round(sc.result.fair_value_per_share)}</div>
                    ) : (
                      <div className="value" style={{ fontSize: 13 }}>不可用</div>
                    )}
                    <div className="card-sub" style={{ fontSize: 10, marginTop: 4, lineHeight: 1.5 }}>
                      增速 {sc.inputs.revenue_growth.map((g) => `${(g * 100).toFixed(0)}%`).join("→")}
                      <br />利润率 {(sc.inputs.op_margin_end * 100).toFixed(0)}% · WACC {(sc.inputs.wacc * 100).toFixed(1)}% · g {(sc.inputs.terminal_growth * 100).toFixed(1)}%
                    </div>
                    {sc.reason ? <div className="card-sub" style={{ fontSize: 10, marginTop: 2 }}>{sc.reason}</div> : null}
                  </div>
                );
              })}
            </div>
            <div className="card-sub" style={{ marginTop: 8 }}>
              参考区间 {refRange ? `$${Math.round(refRange[0])}–$${Math.round(refRange[1])}` : ""} 由悲观/中性/乐观情景值得出，
              是所选假设的结果范围，不是统计置信区间或股价上下限。
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
                type="number" step="0.01" min="1"
                placeholder="输入参考价格 $"
                value={targetPrice}
                onChange={(e) => { setTargetPrice(e.target.value); setReverse((r) => (r ? { ...r, stale: true } : r)); }}
                style={{ padding: "8px 10px", borderRadius: 8, border: "1px solid var(--line)", width: 140 }}
              />
              <button className="tab-btn" onClick={runReverse} disabled={loading}>计算隐含增长</button>
            </div>
            {reverse ? (
              <div style={{ marginTop: 14 }}>
                {reverse.stale ? <div className="card-sub" style={{ color: "#b7791f" }}>假设或价格已修改，以下结果已过期，请重新计算。</div> : null}
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

      {base.model_quality ? (
        <Card className="card-pad" data-testid="model-quality" style={{ marginTop: 16 }}>
          <div className="card-title">模型质量与适用性</div>
          <div className="card-sub">
            数据完整性：{base.model_quality.data_completeness === "complete" ? "完整（全部来自 SEC 事实）" : "部分（存在估计输入）"}
            {base.model_quality.estimated_inputs.length ? ` · 估计输入：${base.model_quality.estimated_inputs.join("、")}` : ""}
          </div>
          <div className="card-sub" style={{ marginTop: 4 }}>
            终值占 EV {Math.round(base.model_quality.terminal_value_share * 100)}%（估值有多少比例依赖较远未来）；
            情景分散（乐观−悲观）÷中性 ≈ {base.model_quality.scenario_dispersion != null ? base.model_quality.scenario_dispersion.toFixed(2) : "—"}。
          </div>
          <div className="card-sub" style={{ marginTop: 4 }}>{base.model_quality.applicability}</div>
          <div className="card-sub" style={{ marginTop: 4 }}>{base.model_quality.note}</div>
        </Card>
      ) : null}

      <Card className="card-pad" data-testid="reference-price" style={{ marginTop: 16 }}>
        <div className="card-title">个人参考价（安全边际）</div>
        <div className="card-sub">
          参考价 = 选定每股估值 × (1 − 安全边际)。这是你主动选择的买入价格参考，不是保证收益或自动交易信号。
        </div>
        <div className="beginner-note" style={{ marginTop: 10 }}>
          <div>💡</div>
          <div>
            <strong>新手下一步怎么走？</strong>
            <p>① 看“悲观–乐观”区间和终值占比（估值有多少依赖较远未来）；② 判断当前模型里最不可靠的假设（通常是增速与永续增长率）；③ 自己定一个安全边际，存成方案；④ 下季度新财报后再回来复核。</p>
          </div>
        </div>
        <div style={{ marginTop: 12, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <label className="card-sub">安全边际 %</label>
          <input
            type="number" min="0" max="99" step="1" placeholder="0"
            value={marginOfSafety}
            onChange={(e) => setMarginOfSafety(e.target.value)}
            style={{ width: 80, padding: "8px 10px", borderRadius: 8, border: "1px solid var(--line)" }}
          />
          <label className="card-sub">方案名</label>
          <input
            value={planName}
            onChange={(e) => setPlanName(e.target.value)}
            placeholder="未命名方案"
            style={{ width: 160, padding: "8px 10px", borderRadius: 8, border: "1px solid var(--line)" }}
          />
          <button className="tab-btn" onClick={savePlan} disabled={loading || fair == null}>
            保存参考价方案
          </button>
        </div>
        {marginOfSafety !== "" && fair != null ? (
          <div className="card-sub" style={{ marginTop: 8 }}>
            预览：参考价 ≈ ${(fair * (1 - (parseFloat(marginOfSafety) || 0) / 100)).toFixed(2)}（Base DCF ${fair.toFixed(0)} × 边际 {marginOfSafety || "0"}%）
          </div>
        ) : null}
        {planMsg ? <div className="card-sub" style={{ marginTop: 8 }}>{planMsg}</div> : null}
        {plans.length ? (
          <div style={{ marginTop: 12 }}>
            <div className="card-sub">已保存方案</div>
            {plans.slice(0, 5).map((p) => (
              <div key={p.plan_id} style={{ padding: "4px 0", borderBottom: "1px solid var(--line)", fontSize: 12 }}>
                {p.name}：参考价 {p.reference_price != null ? `$${p.reference_price.toFixed(2)}` : "—（不可买入）"} · 边际 {Math.round(p.margin_of_safety * 100)}%
              </div>
            ))}
          </div>
        ) : null}
      </Card>
    </>
  );
}
