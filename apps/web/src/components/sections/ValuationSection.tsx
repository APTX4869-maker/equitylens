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
  rebaseDraftOnDefaults,
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
    meta: Record<string, AssumptionMeta>;
  };
  result: {
    fair_value_per_share: number; enterprise_value: number; equity_value: number;
    terminal_value: number; pv_terminal: number; sum_pv_fcff: number; net_cash: number;
    terminal_value_share: number; model_version: string;
    terminal_forecast: {
      year: number; revenue: number; op_margin: number; ebit: number; nopat: number;
      terminal_roic: number; reinvestment_rate: number; reinvestment: number;
      fcff: number; definition: string;
    };
    forecast: { year: number; revenue: number; op_margin: number; fcff: number; pv_fcff: number }[];
    warnings: string[];
  };
  scenarios: Record<"bear" | "base" | "bull", {
    label: string;
    story?: string;
    scenario_version?: string;
    changed_fields?: string[];
    status: "OK" | "UNAVAILABLE";
    reason: string | null;
    result: { fair_value_per_share: number } | null;
    inputs: {
      revenue_growth: number[]; op_margin_end: number; wacc: number;
      terminal_growth: number; terminal_roic: number;
      da_pct?: number; capex_pct?: number; nwc_pct?: number;
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

type AssumptionMeta = {
  value?: unknown;
  source_type?: string;
  source?: string;
  source_ids?: string[];
  as_of?: string;
  version?: string;
  rule?: string;
  reason?: string;
  fallback_reason?: string | null;
  basis?: string;
  components?: Record<string, number>;
  historical_reference?: { label: string; value: number | null; period: string | null; rule: string };
};

type ValuationPlan = {
  plan_id: string;
  name: string;
  valuation_run_id: string | null;
  scenario_key: "base" | "bear" | "bull" | null;
  reference_value: number | null;
  reference_price: number | null;
  reference_price_reason?: string | null;
  margin_of_safety: number;
  notes?: string | null;
  conditions_to_verify: string[];
  parent_plan_id?: string | null;
  version: number | null;
  review_status: string;
  review_reason?: string | null;
  assumptions_json?: Record<string, unknown>;
};

const RNG = {
  growth: { min: -100, max: 20, step: 0.5 },
  margin: { min: 5, max: 60, step: 0.5 },
  wacc: { min: 4, max: 15, step: 0.25 },
  terminal: { min: 0.5, max: 4, step: 0.25 },
  roic: { min: 8, max: 40, step: 1 },
};

export function ValuationSection({
  ticker,
  gate = null,
  refreshGeneration = 0,
  refreshReviewRequired = false,
}: {
  ticker: string;
  gate?: { status: string; reason: string | null } | null;
  refreshGeneration?: number;
  refreshReviewRequired?: boolean;
}) {
  const [base, setBase] = useState<RunResponse | null>(null);
  const [draft, setDraft] = useState<DcfInputs | null>(null);
  const [appliedInputs, setAppliedInputs] = useState<DcfInputs | null>(null);
  const [appliedFingerprint, setAppliedFingerprint] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [targetPrice, setTargetPrice] = useState("");
  const [reverse, setReverse] = useState<{
    implied: number | null;
    hist: number | null;
    note?: string;
    requestIdentity: string;
  } | null>(null);
  const [reverseLoading, setReverseLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saved, setSaved] = useState(false);
  const [marginOfSafety, setMarginOfSafety] = useState("");
  const [planName, setPlanName] = useState("");
  const [planScenario, setPlanScenario] = useState<"base" | "bear" | "bull">("base");
  const [planNotes, setPlanNotes] = useState("");
  const [planConditions, setPlanConditions] = useState("");
  const [plans, setPlans] = useState<ValuationPlan[]>([]);
  const [openedPlan, setOpenedPlan] = useState<ValuationPlan | null>(null);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [changedFields, setChangedFields] = useState<string[]>([]);
  const [planMsg, setPlanMsg] = useState<string | null>(null);
  const [lastCalculatedRefresh, setLastCalculatedRefresh] = useState(refreshGeneration);
  const [draftBaselineRefresh, setDraftBaselineRefresh] = useState(refreshGeneration);
  const reqSeq = useRef(0);
  const defaultReqSeq = useRef(0);
  const reverseReqSeq = useRef(0);
  const draftRef = useRef<DcfInputs | null>(null);
  const targetPriceRef = useRef("");
  const refreshGenerationRef = useRef(refreshGeneration);

  useEffect(() => {
    draftRef.current = draft;
  }, [draft]);

  useEffect(() => {
    refreshGenerationRef.current = refreshGeneration;
  }, [refreshGeneration]);

  // M8: when a synced quote is present, prefill the reverse-DCF reference once,
  // preserving the exact market decimals (326.68 stays 326.68, not 327).
  const prefillReverseTarget = useCallback((d: RunResponse) => {
    const q = d.market?.status === "OK" ? d.market.quote : null;
    if (q && q.price > 0) {
      setTargetPrice((prev) => {
        const next = prev === "" ? String(q.price) : prev;
        targetPriceRef.current = next;
        return next;
      });
    }
  }, []);

  const applyResponse = useCallback((d: RunResponse, persist: boolean, calculatedRefresh: number) => {
    const inputs = draftFromInputs(d.assumptions.inputs);
    setBase(d);
    setDraft(inputs);
    draftRef.current = inputs;
    setAppliedInputs(inputs);
    setAppliedFingerprint(d.input_fingerprint ?? null);
    setSaved(persist);
    setLastCalculatedRefresh(calculatedRefresh);
    setError(null);
  }, []);

  const loadPlans = useCallback(async () => {
    try {
      const d = await api.fetchJson<{ plans: ValuationPlan[] }>(
        `/api/v1/companies/${ticker}/valuation/plans`
      );
      setPlans(d.plans ?? []);
    } catch {
      // plans are optional; a fetch failure must not block the valuation page
    }
  }, [ticker]);

  const preview = useCallback(
    async (
      next: DcfInputs,
      persist = false,
      calculatedRefresh = refreshGenerationRef.current,
    ) => {
      const seq = ++reqSeq.current;
      setLoading(true);
      setError(null);
      try {
        const d = await api.fetchJson<RunResponse>(`/api/v1/companies/${ticker}/valuation/run`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(buildPreviewRequest(next, persist)),
        });
        if (seq !== reqSeq.current || calculatedRefresh !== refreshGenerationRef.current) return;
        applyResponse(d, persist, calculatedRefresh);
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
      reverseReqSeq.current += 1;
      setReverseLoading(false);
      draftRef.current = next;
      setDraft(next);
      void preview(next, false);
    },
    [preview]
  );

  const loadDefault = useCallback(async () => {
    const requestSeq = ++defaultReqSeq.current;
    const calculatedRefresh = refreshGenerationRef.current;
    setLoading(true);
    try {
      const d = await api.fetchJson<RunResponse>(`/api/v1/companies/${ticker}/valuation/default`);
      if (
        requestSeq !== defaultReqSeq.current
        || calculatedRefresh !== refreshGenerationRef.current
      ) return;
      applyResponse(d, false, calculatedRefresh);
      prefillReverseTarget(d);
      setReverse(null);
    } catch (e) {
      if (requestSeq === defaultReqSeq.current) setError(String(e));
    } finally {
      if (requestSeq === defaultReqSeq.current) setLoading(false);
    }
  }, [ticker, applyResponse, prefillReverseTarget]);

  const rebaseOnLatestDefault = useCallback(async (
    targetRefresh = refreshGenerationRef.current,
  ) => {
    const requestSeq = ++defaultReqSeq.current;
    // A refresh supersedes every preview/reverse request that started against
    // the previous fact baseline. Their finally blocks must not unlock the UI.
    reqSeq.current += 1;
    reverseReqSeq.current += 1;
    setReverseLoading(false);
    let previewStarted = false;
    setLoading(true);
    setError(null);
    try {
      const latest = await api.fetchJson<RunResponse>(
        `/api/v1/companies/${ticker}/valuation/default`
      );
      if (
        requestSeq !== defaultReqSeq.current
        || targetRefresh !== refreshGenerationRef.current
      ) return;
      const latestInputs = draftFromInputs(latest.assumptions.inputs);
      const next = draftRef.current
        ? rebaseDraftOnDefaults(latestInputs, draftRef.current)
        : latestInputs;
      // Make the fresh fact-derived baseline authoritative before the network
      // preview starts. A slider edit during that request must inherit the new
      // revenue/cash/share inputs rather than revive the pre-refresh snapshot.
      draftRef.current = next;
      setDraft(next);
      setDraftBaselineRefresh(targetRefresh);
      setSaved(false);
      previewStarted = true;
      await preview(next, false, targetRefresh);
    } catch (e) {
      if (requestSeq === defaultReqSeq.current) setError(String(e));
    } finally {
      if (!previewStarted && requestSeq === defaultReqSeq.current) setLoading(false);
    }
  }, [ticker, preview]);

  useEffect(() => {
    if (gate && gate.status !== "READY") return;
    const timer = window.setTimeout(() => void loadDefault(), 0);
    return () => window.clearTimeout(timer);
  }, [ticker, gate, loadDefault]);

  useEffect(() => {
    if (gate && gate.status !== "READY") return;
    const timer = window.setTimeout(() => void loadPlans(), 0);
    return () => window.clearTimeout(timer);
  }, [refreshGeneration, gate, loadPlans]);

  useEffect(() => {
    if (
      (gate && gate.status !== "READY")
      || !refreshReviewRequired
      || refreshGeneration <= lastCalculatedRefresh
    ) return;
    const targetRefresh = refreshGeneration;
    const timer = window.setTimeout(
      () => void rebaseOnLatestDefault(targetRefresh),
      0,
    );
    return () => window.clearTimeout(timer);
  }, [
    refreshGeneration,
    refreshReviewRequired,
    lastCalculatedRefresh,
    gate,
    rebaseOnLatestDefault,
  ]);

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
    const runId = base?.valuation_run_id;
    const selected = base?.scenarios[planScenario];
    if (!runId || !saved) {
      setPlanMsg("请先保存当前估值运行，再创建可追溯方案");
      return;
    }
    if (!selected?.result) {
      setPlanMsg("所选情景当前不可用");
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
            valuation_run_id: runId,
            scenario_key: planScenario,
            margin_of_safety: pct / 100,
            notes: planNotes || undefined,
            conditions_to_verify: planConditions.split("\n").map((item) => item.trim()).filter(Boolean),
          }),
        }
      );
      setPlanMsg(d.reference_price != null
        ? `已保存方案：参考价 $${d.reference_price.toFixed(2)}`
        : `已保存（仅供研究）：${d.reference_price_reason ?? "不可买入"}`);
      setPlanName("");
      setPlanNotes("");
      setPlanConditions("");
      void loadPlans();
    } catch (e) {
      setPlanMsg(String(e));
    }
  }, [ticker, marginOfSafety, planName, planScenario, planNotes, planConditions, base, saved, loadPlans]);

  const openPlan = useCallback(async (planId: string) => {
    try {
      const plan = await api.fetchJson<ValuationPlan>(
        `/api/v1/companies/${ticker}/valuation/plans/${planId}`
      );
      setOpenedPlan(plan);
    } catch (e) {
      setPlanMsg(String(e));
    }
  }, [ticker]);

  const copyPlan = useCallback(async (planId: string) => {
    try {
      const copy = await api.fetchJson<ValuationPlan>(
        `/api/v1/companies/${ticker}/valuation/plans/${planId}/copy`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) }
      );
      setOpenedPlan(copy);
      setPlanMsg(`已复制为版本 ${copy.version ?? "—"}`);
      await loadPlans();
    } catch (e) {
      setPlanMsg(String(e));
    }
  }, [ticker, loadPlans]);

  const comparePlans = useCallback(async () => {
    if (compareIds.length < 2) {
      setPlanMsg("请至少选择两个方案比较");
      return;
    }
    try {
      const result = await api.fetchJson<{ plans: ValuationPlan[]; changed_fields: string[] }>(
        `/api/v1/companies/${ticker}/valuation/plans/compare?ids=${encodeURIComponent(compareIds.join(","))}`
      );
      setChangedFields(result.changed_fields);
    } catch (e) {
      setPlanMsg(String(e));
    }
  }, [ticker, compareIds]);

  const runReverse = useCallback(async () => {
    const price = parseFloat(targetPriceRef.current);
    if (!price || price <= 0) return;
    const current = draftRef.current;
    if (!current) return;
    const seq = ++reverseReqSeq.current;
    const requestIdentity = [
      ticker,
      draftFingerprint(current),
      String(price),
      String(refreshGenerationRef.current),
    ].join("|");
    setReverseLoading(true);
    try {
      const d = await api.fetchJson<{ implied_revenue_cagr: number | null; historical_revenue_cagr: number | null; no_root_reason?: string | null }>(
        `/api/v1/companies/${ticker}/valuation/reverse-dcf`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ target_price: price, assumptions: buildPreviewRequest(current).assumptions }),
        }
      );
      const latestDraft = draftRef.current;
      const latestPrice = parseFloat(targetPriceRef.current);
      const latestIdentity = latestDraft ? [
        ticker,
        draftFingerprint(latestDraft),
        String(latestPrice),
        String(refreshGenerationRef.current),
      ].join("|") : "";
      if (seq !== reverseReqSeq.current || latestIdentity !== requestIdentity) return;
      setReverse({
        implied: d.implied_revenue_cagr,
        hist: d.historical_revenue_cagr,
        note: d.no_root_reason ?? undefined,
        requestIdentity,
      });
    } catch (e) {
      if (seq === reverseReqSeq.current) {
        setReverse({ implied: null, hist: null, note: String(e), requestIdentity });
      }
    } finally {
      if (seq === reverseReqSeq.current) setReverseLoading(false);
    }
  }, [ticker]);

  const fair = base?.result.fair_value_per_share;
  const bear = base?.scenarios.bear.result?.fair_value_per_share;
  const bull = base?.scenarios.bull.result?.fair_value_per_share;
  const refRange = fair != null && bear != null && bull != null ? [Math.min(bear, bull), Math.max(bear, bull)] : null;
  const selectedPlanValue = base?.scenarios[planScenario]?.result?.fair_value_per_share ?? null;

  const growthPct = draft ? draft.revenue_growth[0] * 100 : 0;
  const marginPct = draft ? draft.op_margin_end * 100 : 0;
  const waccPct = draft ? draft.wacc * 100 : 0;
  const terminalPct = draft ? draft.terminal_growth * 100 : 0;
  const roicPct = draft ? draft.terminal_roic * 100 : 0;

  // The visible result is saveable only when the applied inputs still equal the
  // current draft and there is no pending/failed request.
  const isDirty = appliedInputs != null && draft != null
    ? draftFingerprint(draft) !== draftFingerprint(appliedInputs)
    : true;
  const refreshStale = refreshReviewRequired && refreshGeneration > lastCalculatedRefresh;
  const currentReverseIdentity = draft ? [
    ticker,
    draftFingerprint(draft),
    String(parseFloat(targetPrice)),
    String(refreshGeneration),
  ].join("|") : "";
  const reverseStale = reverse != null && reverse.requestIdentity !== currentReverseIdentity;
  const canSave = !refreshStale && !isDirty && !error && !loading && appliedFingerprint != null;

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

  if (gate && gate.status !== "READY") return <Card className="card-pad" data-testid="valuation-gate"><div className="section-head"><div><span className="eyebrow">Valuation readiness</span><h2 style={{ margin: "4px 0" }}>估值尚未开放</h2></div><Pill tone={gate.status === "BLOCKED" ? "bad" : "warn"}>{gate.status === "BLOCKED" ? "数据阻断" : "待配置"}</Pill></div><div className="next-step">{gate.reason ?? "该证券尚未确认估值模型、币种与每股口径。"}<br />下一步：在公司档案中确认估值配置，并重新通过发布质量门禁。</div></Card>;
  if (error && !base) return <Card><ErrorBox message={error} onRetry={loadDefault} /></Card>;
  if (!base) return <Spinner label="正在加载估值引擎…" />;

  const i = draft ?? base.assumptions.inputs;
  const meta = base.assumptions.meta;
  const assumptionNote = (key: string) => {
    const item = meta[key];
    if (!item) return null;
    const identity = item.as_of || item.version || "未标注版本";
    const effects: Record<string, string> = {
      revenue_growth: "调高通常会提高收入与价值；调低或转负通常会降低价值。",
      op_margin_end: "调高表示每单位收入留下更多经营利润，通常提高价值；调低则相反。",
      wacc: "调高会更大幅度折价未来现金流，通常降低价值；它是模型折现率，不是个人承诺收益率。",
      terminal_growth: "调高通常提高终值，但也会增加模型对远期假设的依赖。",
      terminal_roic: "调高表示稳定增长需要较少再投资，通常提高稳定期自由现金流。",
    };
    const history = item.historical_reference;
    return (
      <div className="assumption-context" data-testid={`assumption-${key}`}>
        {history?.value != null ? (
          <span>公司历史参照：{history.label} {(history.value * 100).toFixed(1)}% · {history.period}（{history.rule}）</span>
        ) : null}
        <strong>{item.reason}</strong>
        {effects[key] ? <span>变动影响：{effects[key]}</span> : null}
        <span>{item.source_type ?? "unknown"} · {identity} · {item.source}</span>
        <span>规则：{item.rule}</span>
        {item.fallback_reason ? <span>回退原因：{item.fallback_reason}</span> : null}
      </div>
    );
  };
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

      <Card className="card-pad beginner-only" data-testid="beginner-valuation-walkthrough" style={{ marginBottom: 16 }}>
        <div className="card-title">先读懂，再调整</div>
        <div className="beginner-steps">
          <div><strong>1 · 公司经营基准</strong><span>{ticker} 从 {meta.revenue_base?.as_of ?? "未标注期间"} 收入 {fmtMoney(i.revenue_base)}、营业利润率 {(i.op_margin_start * 100).toFixed(1)}% 开始预测。</span></div>
          <div><strong>2 · 数据时点</strong><span>利润与股数：{meta.shares?.as_of ?? "未标注"}；净现金：{meta.net_cash?.as_of ?? "未标注"}；行情：{mktQuote?.observed_at ?? "未同步"}。</span></div>
          <div><strong>3 · 先看范围与不确定性</strong><span>下方区间来自三个明确情景，不是概率范围。当前最需要自己判断的是收入增长路径；默认理由和历史参照会显示在滑杆下方。</span></div>
          <div><strong>4 · 再采取行动</strong><span>修改假设后重算，用 Reverse DCF 检查市场价格要求，再自行设置安全边际并保存方案。</span></div>
        </div>
      </Card>

      {refreshStale ? (
        <Card data-testid="refresh-review-warning" style={{ marginBottom: 16 }}>
          <div className="card-sub" style={{ color: "#b7791f" }}>
            财务或行情快照已更新。当前草稿仍保留，但页面上的估值结果来自刷新前的数据，请重新计算后再保存。
          </div>
          <button className="tab-btn" style={{ marginTop: 8 }} onClick={() => void rebaseOnLatestDefault()} disabled={loading}>
            按当前草稿重新计算
          </button>
        </Card>
      ) : null}

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
          <span>{saved && !refreshStale && base.valuation_run_id ? `已保存 · run ${base.valuation_run_id}` : saved && !refreshStale ? "已保存方案" : isDirty || refreshStale ? "未保存（预览已过期）" : "未保存（预览）"}</span>
          <button className="tab-btn" onClick={saveRun} disabled={!canSave}>
            保存本次运行
          </button>
        </div>
      </Card>

      {loading ? <div className="muted" style={{ marginBottom: 8 }}>正在重算…</div> : null}
      {error ? <Card style={{ marginBottom: 12 }}><ErrorBox message={error} onRetry={() => void rebaseOnLatestDefault()} /></Card> : null}

      <div className="grid grid-2" style={{ marginTop: 12 }}>
        <Card className="card-pad" data-testid="dcf-model">
          <div className="section-head">
            <div>
              <div className="card-title">5-Year FCFF DCF</div>
              <div className="card-sub">代码计算现金流；改动假设即全量重算。开放 5 个核心假设。</div>
            </div>
            <Pill tone="blue">FCFF DCF</Pill>
          </div>
          <div className="dcf-output">
            <div className="card-sub">当前假设下每股内在价值</div>
            <div className="fair" style={{ fontSize: 34 }} data-testid="fair-value">${fair != null ? fair.toFixed(0) : "—"}</div>
            <div className="delta">净现金 ${fmtMoney(base.result.net_cash)} · 股本 {Math.round(i.shares / 1e6)}M（{meta.shares?.basis ?? i.share_basis_label ?? "股数口径未标注"}）</div>
          </div>
          <div className="dcf-sliders">
            <div className="dcf-control">
              <label htmlFor="growth-slider">首年收入增速（路径逐年递减）</label>
              <input id="growth-slider" type="range" min={RNG.growth.min} max={RNG.growth.max} step={RNG.growth.step}
                value={growthPct} disabled={refreshGeneration > draftBaselineRefresh}
                onChange={(e) => edit({ field: "growth", percent: Number(e.target.value) })} />
              <output>{growthPct.toFixed(1)}%</output>
              {assumptionNote("revenue_growth")}
            </div>
            <div className="dcf-control">
              <label htmlFor="margin-slider">第5年营业利润率</label>
              <input id="margin-slider" type="range" min={RNG.margin.min} max={RNG.margin.max} step={RNG.margin.step}
                value={marginPct} disabled={refreshGeneration > draftBaselineRefresh}
                onChange={(e) => edit({ field: "margin", percent: Number(e.target.value) })} />
              <output>{marginPct.toFixed(1)}%</output>
              {assumptionNote("op_margin_end")}
            </div>
            <div className="dcf-control">
              <label htmlFor="wacc-slider">WACC 折现率</label>
              <input id="wacc-slider" type="range" min={RNG.wacc.min} max={RNG.wacc.max} step={RNG.wacc.step}
                value={waccPct} disabled={refreshGeneration > draftBaselineRefresh}
                onChange={(e) => edit({ field: "wacc", percent: Number(e.target.value) })} />
              <output>{waccPct.toFixed(2)}%</output>
              {assumptionNote("wacc")}
            </div>
            <div className="dcf-control">
              <label htmlFor="terminal-slider">永续增长率</label>
              <input id="terminal-slider" type="range" min={RNG.terminal.min} max={RNG.terminal.max} step={RNG.terminal.step}
                value={terminalPct} disabled={refreshGeneration > draftBaselineRefresh}
                onChange={(e) => edit({ field: "terminal", percent: Number(e.target.value) })} />
              <output>{terminalPct.toFixed(2)}%</output>
              {assumptionNote("terminal_growth")}
            </div>
            <div className="dcf-control">
              <label htmlFor="roic-slider">稳定期增量资本回报率</label>
              <input id="roic-slider" type="range" min={RNG.roic.min} max={RNG.roic.max} step={RNG.roic.step}
                value={roicPct} disabled={refreshGeneration > draftBaselineRefresh}
                onChange={(e) => edit({ field: "roic", percent: Number(e.target.value) })} />
              <output>{roicPct.toFixed(0)}%</output>
              {assumptionNote("terminal_roic")}
            </div>
          </div>
          <div className="card-sub" style={{ marginBottom: 8 }}>
            稳定期 Y{base.result.terminal_forecast.year}：NOPAT {fmtMoney(base.result.terminal_forecast.nopat)}，
            再投资率 {(base.result.terminal_forecast.reinvestment_rate * 100).toFixed(1)}%，
            终值年度 FCFF {fmtMoney(base.result.terminal_forecast.fcff)}。
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
                    <p className="card-sub" style={{ fontSize: 10, marginTop: 5 }}>
                      {sc.story ?? "旧版本情景未记录公司故事。"}
                    </p>
                    <details style={{ marginTop: 5 }}>
                      <summary className="text-link">查看全部假设与差异</summary>
                      <div className="card-sub" style={{ fontSize: 10, lineHeight: 1.5, marginTop: 4 }}>
                        D&amp;A/收入 {sc.inputs.da_pct != null ? `${(sc.inputs.da_pct * 100).toFixed(1)}%` : "旧版本未记录"} · CapEx/收入 {sc.inputs.capex_pct != null ? `${(sc.inputs.capex_pct * 100).toFixed(1)}%` : "旧版本未记录"}
                        <br />营运资金/收入增量 {sc.inputs.nwc_pct != null ? `${(sc.inputs.nwc_pct * 100).toFixed(1)}%` : "旧版本未记录"} · 稳定期 ROIC {(sc.inputs.terminal_roic * 100).toFixed(0)}%
                        <br />相对当前草稿变更：{sc.changed_fields?.length ? sc.changed_fields.join("、") : sc.changed_fields ? "无" : "旧版本未记录"}
                        <br />版本：{sc.scenario_version ?? "旧版本未记录"}
                      </div>
                    </details>
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

          <details className="advanced-disclosure">
            <summary>展开高级敏感性矩阵（WACC × 永续增长）</summary>
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
          </details>
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
                onChange={(e) => {
                  reverseReqSeq.current += 1;
                  setReverseLoading(false);
                  targetPriceRef.current = e.target.value;
                  setTargetPrice(e.target.value);
                }}
                style={{ padding: "8px 10px", borderRadius: 8, border: "1px solid var(--line)", width: 140 }}
              />
              <button className="tab-btn" onClick={runReverse} disabled={reverseLoading}>
                {reverseLoading ? "计算中…" : "计算隐含增长"}
              </button>
            </div>
            {reverse ? (
              <div style={{ marginTop: 14 }}>
                {reverseStale || refreshStale ? <div className="card-sub" style={{ color: "#b7791f" }}>假设、价格或底层数据已修改，以下结果已过期，请重新计算。</div> : null}
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
          <details className="advanced-disclosure">
            <summary>展开全部假设来源与原始字段</summary>
            <div className="card-title" style={{ marginTop: 10 }}>假设来源</div>
            <div className="card-sub">每个输入都区分事实、确定性公式、配置假设与用户覆盖。</div>
            <div style={{ marginTop: 10, fontSize: 11, color: "var(--muted)" }}>
            {Object.entries(meta).map(([k, v]) => (
              <div key={k} style={{ padding: "4px 0", borderBottom: "1px solid var(--line)" }}>
                <strong style={{ color: "var(--navy)" }}>{k}</strong>
                <span> = {typeof v.value === "number" ? (k === "beta" ? v.value.toFixed(2) : k.includes("pct") || k.includes("rate") || k.includes("margin") || k === "wacc" ? `${(v.value * 100).toFixed(1)}%` : v.value.toLocaleString()) : Array.isArray(v.value) ? v.value.join(" → ") : String(v.value ?? "")}</span>
                <div>{v.source_type ?? "unknown"} · {v.as_of ?? v.version ?? "未标注"} · {v.source}</div>
                <div>{v.rule}</div>
              </div>
            ))}
            </div>
          </details>
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
        <div className="beginner-note" data-testid="plan-review-trigger" style={{ marginTop: 10 }}>
          <div>💡</div>
          <div>
            <strong>新手下一步怎么走？</strong>
            <p>① 看“悲观–乐观”区间和终值占比（估值有多少依赖较远未来）；② 判断当前模型里最不可靠的假设（通常是增速与永续增长率）；③ 自己定一个安全边际，存成方案；④ 下季度新财报后再回来复核。</p>
          </div>
        </div>
        <div style={{ marginTop: 12, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <label className="card-sub" htmlFor="plan-scenario">参考情景</label>
          <select id="plan-scenario" value={planScenario}
            onChange={(e) => setPlanScenario(e.target.value as "base" | "bear" | "bull")}
            style={{ padding: "8px 10px", borderRadius: 8, border: "1px solid var(--line)" }}>
            <option value="bear">悲观 Bear</option>
            <option value="base">中性 Base</option>
            <option value="bull">乐观 Bull</option>
          </select>
          <label className="card-sub" htmlFor="plan-margin">安全边际 %</label>
          <input
            id="plan-margin"
            type="number" min="0" max="99" step="1" placeholder="0"
            value={marginOfSafety}
            onChange={(e) => setMarginOfSafety(e.target.value)}
            style={{ width: 80, padding: "8px 10px", borderRadius: 8, border: "1px solid var(--line)" }}
          />
          <label className="card-sub" htmlFor="plan-name">方案名</label>
          <input
            id="plan-name"
            value={planName}
            onChange={(e) => setPlanName(e.target.value)}
            placeholder="未命名方案"
            style={{ width: 160, padding: "8px 10px", borderRadius: 8, border: "1px solid var(--line)" }}
          />
          <button className="tab-btn" onClick={savePlan}
            disabled={loading || refreshStale || !saved || !base.valuation_run_id || selectedPlanValue == null}>
            保存参考价方案
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 10 }}>
          <textarea aria-label="方案备注" value={planNotes} onChange={(e) => setPlanNotes(e.target.value)}
            placeholder="备注：为什么选择这个情景？"
            style={{ minHeight: 64, padding: 8, borderRadius: 8, border: "1px solid var(--line)" }} />
          <textarea aria-label="待验证条件" value={planConditions} onChange={(e) => setPlanConditions(e.target.value)}
            placeholder={"每行一个待验证条件\n例如：下一季服务收入继续增长"}
            style={{ minHeight: 64, padding: 8, borderRadius: 8, border: "1px solid var(--line)" }} />
        </div>
        {!saved || !base.valuation_run_id ? (
          <div className="card-sub" style={{ marginTop: 8 }}>先点击“保存本次运行”，方案才能绑定不可变输入与情景。</div>
        ) : null}
        {marginOfSafety !== "" && selectedPlanValue != null ? (
          <div className="card-sub" style={{ marginTop: 8 }}>
            预览：参考价 ≈ ${(selectedPlanValue * (1 - (parseFloat(marginOfSafety) || 0) / 100)).toFixed(2)}
            （{planScenario} ${selectedPlanValue.toFixed(2)} × 边际 {marginOfSafety || "0"}%）
          </div>
        ) : null}
        {planMsg ? <div className="card-sub" style={{ marginTop: 8 }}>{planMsg}</div> : null}
        {plans.length ? (
          <div style={{ marginTop: 12 }}>
            <div className="card-sub">已保存方案</div>
            {plans.slice(0, 5).map((p) => (
              <div key={p.plan_id} style={{ padding: "4px 0", borderBottom: "1px solid var(--line)", fontSize: 12 }}>
                <label style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
                  <input type="checkbox" aria-label={`比较 ${p.name}`} checked={compareIds.includes(p.plan_id)}
                    onChange={(e) => setCompareIds((ids) => e.target.checked
                      ? [...ids, p.plan_id]
                      : ids.filter((id) => id !== p.plan_id))} />
                  {p.name}：参考价 {p.reference_price != null ? `$${p.reference_price.toFixed(2)}` : "—（不可买入）"}
                  · {p.scenario_key ?? "旧来源"} · 边际 {Math.round(p.margin_of_safety * 100)}%
                  · {p.review_status}
                </label>
                <button className="text-link" style={{ marginLeft: 8 }} onClick={() => void openPlan(p.plan_id)}>打开</button>
                <button className="text-link" style={{ marginLeft: 8 }} onClick={() => void copyPlan(p.plan_id)}>复制</button>
              </div>
            ))}
            <button className="tab-btn" style={{ marginTop: 8 }} onClick={() => void comparePlans()}
              disabled={compareIds.length < 2}>比较所选方案</button>
            {changedFields.length ? (
              <div className="card-sub" data-testid="plan-comparison" style={{ marginTop: 8 }}>
                差异字段：{changedFields.join("、")}
              </div>
            ) : null}
          </div>
        ) : null}
        {openedPlan ? (
          <div className="plain-box" data-testid="plan-detail" style={{ marginTop: 12 }}>
            <strong>{openedPlan.name} · v{openedPlan.version ?? "—"} · {openedPlan.review_status}</strong>
            <div>来源：run {openedPlan.valuation_run_id ?? "缺失"} / {openedPlan.scenario_key ?? "旧方案"}</div>
            <div>备注：{openedPlan.notes || "—"}</div>
            <div>待验证：{openedPlan.conditions_to_verify.length ? openedPlan.conditions_to_verify.join("；") : "—"}</div>
            {openedPlan.review_reason ? <div>{openedPlan.review_reason}</div> : null}
          </div>
        ) : null}
      </Card>
    </>
  );
}
