"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { RiskFreeSnapshot } from "@/components/valuation/RiskFreeSnapshot";

import {
  api,
  userErrorMessage,
  type ValuationPlan,
  type ValuationPlanComparison,
  type ValuationPlanCopyDraft,
  type ValuationRunSnapshot,
} from "@/lib/api";

const PERCENT_FIELDS = new Set([
  "revenue_growth", "op_margin_end", "wacc", "terminal_growth",
  "terminal_roic", "margin_of_safety",
]);

const ASSUMPTION_LABELS: Record<string, string> = {
  revenue_growth: "五年收入增速路径",
  op_margin_end: "第 5 年营业利润率",
  wacc: "WACC",
  terminal_growth: "永续增长率",
  terminal_roic: "稳定期 ROIC",
  revenue_base: "收入基准",
  op_margin_start: "起始营业利润率",
  tax_rate: "税率",
  net_cash: "净现金",
  shares: "稀释后股数",
};

function displayValue(key: string, value: unknown): string {
  if (value == null || value === "") return "—";
  if (Array.isArray(value)) {
    return value.map((item) => typeof item === "number" ? `${(item * 100).toFixed(2)}%` : String(item)).join(" → ");
  }
  if (typeof value === "number") {
    if (PERCENT_FIELDS.has(key)) return `${(value * 100).toFixed(2)}%`;
    return value.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
  }
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function PlanDetail({ plan, run }: { plan: ValuationPlan; run: ValuationRunSnapshot | null }) {
  const assumptions = plan.assumptions_json ?? run?.assumptions.inputs ?? {};
  const fairValue = plan.reference_value;
  return (
    <section className="plan-detail" data-testid="plan-detail" aria-label="方案不可变快照">
      <div className="plan-detail-head">
        <div>
          <span className="eyebrow">IMMUTABLE SNAPSHOT</span>
          <h4>{plan.name} <small>v{plan.version ?? "—"}</small></h4>
        </div>
        <span className={`plan-status ${plan.review_status === "current" ? "current" : "review"}`}>
          {plan.review_status === "current" ? "当前有效" : plan.review_status}
        </span>
      </div>
      <div className="plan-detail-metrics">
        <div><span>所选情景每股价值</span><strong>{fairValue == null ? "—" : `$${Number(fairValue).toFixed(2)}`}</strong></div>
        <div><span>安全边际</span><strong>{displayValue("margin_of_safety", plan.margin_of_safety)}</strong></div>
        <div><span>个人参考价</span><strong>{plan.reference_price == null ? "—" : `$${plan.reference_price.toFixed(2)}`}</strong></div>
        <div><span>模型 / 运行</span><strong>{run?.model_version ?? "—"}</strong><small>{plan.valuation_run_id ?? "历史记录不完整"}</small></div>
      </div>
      <div className="plan-detail-grid">
        <div>
          <h5>已冻结假设</h5>
          <RiskFreeSnapshot meta={run?.assumptions.meta?.risk_free} />
          <dl className="plan-assumptions">
            {Object.entries(assumptions).map(([key, value]) => (
              <div key={key}><dt>{ASSUMPTION_LABELS[key] ?? key}</dt><dd>{displayValue(key, value)}</dd></div>
            ))}
          </dl>
        </div>
        <div className="plan-notes">
          <h5>决策记录</h5>
          <span>备注</span><p>{plan.notes || "未填写"}</p>
          <span>待验证条件</span>
          {plan.conditions_to_verify.length
            ? <ul>{plan.conditions_to_verify.map((condition) => <li key={condition}>{condition}</li>)}</ul>
            : <p>未填写</p>}
          <span>血缘</span>
          <p>{plan.parent_plan_id ? `源自 ${plan.parent_plan_id}，当前为 v${plan.version}` : "初始版本"}</p>
        </div>
      </div>
    </section>
  );
}

function Comparison({ result }: { result: ValuationPlanComparison }) {
  const names = Object.fromEntries(result.plans.map((plan) => [plan.plan_id, plan.name]));
  return (
    <section className="plan-comparison" data-testid="plan-comparison">
      <div className="plan-comparison-head">
        <div><span className="eyebrow">SIDE BY SIDE</span><h4>方案实际值对比</h4></div>
        <span>{result.has_differences ? `${result.changed_fields.length} 项差异` : "方案完全相同"}</span>
      </div>
      <div className="plan-comparison-table-wrap">
        <table>
          <thead><tr><th>字段</th>{result.plans.map((plan) => <th key={plan.plan_id}>{plan.name}</th>)}<th>结论</th></tr></thead>
          <tbody>{result.fields.map((field) => (
            <tr key={field.key} data-changed={field.changed ? "true" : "false"}>
              <th>{field.label}</th>
              {result.plans.map((plan) => {
                const entry = field.values.find((value) => value.plan_id === plan.plan_id);
                return <td key={plan.plan_id} aria-label={`${names[plan.plan_id]} ${field.label}`}>{displayValue(field.key, entry?.value)}</td>;
              })}
              <td><span className={field.changed ? "comparison-changed" : "comparison-same"}>{field.changed ? "有差异" : "相同"}</span></td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </section>
  );
}

export function ValuationPlanLibrary({
  ticker,
  refreshToken,
  copyContext,
  onCopyEdit,
}: {
  ticker: string;
  refreshToken: number;
  copyContext: string;
  onCopyEdit: (draft: ValuationPlanCopyDraft) => void;
}) {
  const [status, setStatus] = useState<"active" | "archived">("active");
  const [searchInput, setSearchInput] = useState("");
  const [query, setQuery] = useState("");
  const [searchRevision, setSearchRevision] = useState(0);
  const [plans, setPlans] = useState<ValuationPlan[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [comparison, setComparison] = useState<ValuationPlanComparison | null>(null);
  const [opened, setOpened] = useState<{ plan: ValuationPlan; run: ValuationRunSnapshot | null } | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const requestSeq = useRef(0);
  const copySeq = useRef(0);

  useEffect(() => {
    return () => { copySeq.current += 1; };
  }, [copyContext]);

  const load = useCallback(async (append = false, cursor: string | null = null) => {
    const seq = ++requestSeq.current;
    if (append) setLoadingMore(true); else setLoading(true);
    setError(null);
    try {
      const result = await api.valuationPlans(ticker, { status, q: query, limit: 6, cursor });
      if (seq !== requestSeq.current) return;
      setPlans((current) => append ? [...current, ...result.plans] : result.plans);
      setNextCursor(result.next_cursor);
    } catch (reason) {
      if (seq === requestSeq.current) setError(userErrorMessage(reason));
    } finally {
      if (seq === requestSeq.current) {
        setLoading(false);
        setLoadingMore(false);
      }
    }
  }, [query, status, ticker]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(false), 0);
    return () => window.clearTimeout(timer);
  }, [load, refreshToken, searchRevision]);

  const resetView = () => {
    setSelectedIds([]);
    setComparison(null);
    setOpened(null);
  };

  const submitSearch = (event: FormEvent) => {
    event.preventDefault();
    resetView();
    const next = searchInput.trim();
    if (next === query) setSearchRevision((value) => value + 1);
    else setQuery(next);
  };

  const changeStatus = (next: "active" | "archived") => {
    if (next === status) return;
    resetView();
    setStatus(next);
  };

  const mutateArchive = async (plan: ValuationPlan) => {
    setMessage(null);
    try {
      if (status === "active") await api.archiveValuationPlan(ticker, plan.plan_id);
      else await api.restoreValuationPlan(ticker, plan.plan_id);
      setPlans((current) => current.filter((item) => item.plan_id !== plan.plan_id));
      setSelectedIds((current) => current.filter((id) => id !== plan.plan_id));
      setMessage(status === "active" ? `已归档“${plan.name}”，可在已归档中恢复。` : `已恢复“${plan.name}”。`);
    } catch (reason) {
      setError(userErrorMessage(reason));
    }
  };

  const openPlan = async (planId: string) => {
    setDetailLoading(true);
    setError(null);
    try {
      const plan = await api.valuationPlan(ticker, planId);
      const run = plan.valuation_run_id
        ? await api.valuationRunSnapshot(ticker, plan.valuation_run_id)
        : null;
      setOpened({ plan, run });
    } catch (reason) {
      setError(userErrorMessage(reason));
    } finally {
      setDetailLoading(false);
    }
  };

  const copyPlan = async (plan: ValuationPlan) => {
    const seq = ++copySeq.current;
    setError(null);
    try {
      const draft = await api.copyValuationPlan(ticker, plan.plan_id);
      if (seq !== copySeq.current) return;
      onCopyEdit(draft);
      setMessage(`已载入“${plan.name}”的可编辑草稿；重算并保存后才会生成 v${draft.next_version}。`);
    } catch (reason) {
      if (seq === copySeq.current) setError(userErrorMessage(reason));
    }
  };

  const compare = async () => {
    if (selectedIds.length < 2) return;
    setError(null);
    try {
      setComparison(await api.compareValuationPlans(ticker, selectedIds));
    } catch (reason) {
      setError(userErrorMessage(reason));
    }
  };

  const emptyLabel = status === "active" ? "没有匹配的有效方案" : "没有匹配的归档方案";
  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);

  return (
    <section className="plan-library" data-testid="valuation-plan-library">
      <div className="plan-library-heading">
        <div><span className="eyebrow">PERSONAL DECISION LEDGER</span><h3>估值方案库</h3><p>历史方案保持不可变；复制后须重算，才会保存为有血缘的新版本。</p></div>
        <div className="plan-library-tabs" aria-label="方案状态">
          <button className={status === "active" ? "active" : ""} onClick={() => changeStatus("active")}>有效方案</button>
          <button className={status === "archived" ? "active" : ""} onClick={() => changeStatus("archived")}>已归档</button>
        </div>
      </div>
      <form className="plan-search" onSubmit={submitSearch} role="search">
        <input type="search" aria-label="搜索方案" value={searchInput} onChange={(event) => setSearchInput(event.target.value)} placeholder="搜索名称或备注" />
        <button className="secondary-action" type="submit" aria-label="搜索方案">搜索</button>
      </form>

      {error ? <div className="action-error plan-library-error" role="alert">{error}<button onClick={() => void load(false)}>重试加载方案</button></div> : null}
      {message ? <div className="plan-library-message" role="status">{message}</div> : null}
      {loading && plans.length === 0 ? <div className="plan-library-empty">正在读取方案…</div> : null}
      {!loading && plans.length === 0 ? <div className="plan-library-empty">{emptyLabel}</div> : null}

      <div className="plan-library-list">
        {plans.map((plan) => (
          <article className="plan-library-row" data-testid="plan-library-row" key={plan.plan_id}>
            <label className="plan-compare-check">
              <input
                type="checkbox"
                aria-label={`比较 ${plan.name}`}
                checked={selectedSet.has(plan.plan_id)}
                disabled={!selectedSet.has(plan.plan_id) && selectedIds.length >= 5}
                onChange={(event) => setSelectedIds((current) => event.target.checked
                  ? [...current, plan.plan_id]
                  : current.filter((id) => id !== plan.plan_id))}
              />
            </label>
            <div className="plan-row-main">
              <strong>{plan.name}</strong>
              <span>{plan.scenario_key ?? "旧来源"} · v{plan.version ?? "—"}{plan.parent_plan_id ? ` · 源自 ${plan.parent_plan_id}` : ""}</span>
            </div>
            <div className="plan-row-price"><span>参考价</span><strong>{plan.reference_price == null ? "—" : `$${plan.reference_price.toFixed(2)}`}</strong></div>
            <div className="plan-row-actions">
              <button className="text-link" aria-label={`打开${plan.name}`} onClick={() => void openPlan(plan.plan_id)}>打开</button>
              {status === "active" ? <button className="text-link" aria-label={`复制并编辑${plan.name}`} onClick={() => void copyPlan(plan)}>复制并编辑</button> : null}
              <button className="text-link danger" aria-label={`${status === "active" ? "归档" : "恢复"}${plan.name}`} onClick={() => void mutateArchive(plan)}>{status === "active" ? "归档" : "恢复"}</button>
            </div>
          </article>
        ))}
      </div>

      <div className="plan-library-footer">
        <button className="secondary-action" disabled={!nextCursor || loadingMore} onClick={() => void load(true, nextCursor)}>{loadingMore ? "加载中…" : "加载更多方案"}</button>
        <button className="primary-action" disabled={selectedIds.length < 2} onClick={() => void compare()}>比较所选方案</button>
        <span>{selectedIds.length ? `已选 ${selectedIds.length}/5` : "选择 2–5 个方案比较"}</span>
      </div>
      {detailLoading ? <div className="plan-library-empty">正在打开不可变快照…</div> : null}
      {opened ? <PlanDetail plan={opened.plan} run={opened.run} /> : null}
      {comparison ? <Comparison result={comparison} /> : null}
    </section>
  );
}
