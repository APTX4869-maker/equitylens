"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiRequestError, api, userErrorMessage } from "@/lib/api";
import {
  buildPreviewRequest,
  draftFromInputs,
  updateDraft,
  type DcfInputs,
  type DraftEdit,
} from "@/lib/valuationDraft";
import { Card, Pill, Spinner } from "@/components/ui";

type AssumptionMeta = {
  reason?: string;
  source?: string;
  version?: string;
  as_of?: string;
};

type Scenario = {
  label: string;
  status: "OK" | "UNAVAILABLE";
  reason: string | null;
  result: { fair_value_per_share: number } | null;
};

type Preview = {
  scenarios: Record<"bear" | "base" | "bull", Scenario>;
  result?: { fair_value_per_share: number };
};

type ValuationDraft = {
  security_id: string;
  publication_id: string;
  model_version: string;
  status: string;
  acknowledgement_required: boolean;
  assumptions: {
    inputs: DcfInputs;
    meta: Record<string, AssumptionMeta>;
  };
  preview: Preview;
};

export type ValuationSetupCardProps = {
  ticker: string;
  gate: { status: string; reason: string | null };
  onConfirmed: () => Promise<void> | void;
};

const controls: Array<{
  field: DraftEdit["field"];
  meta: string;
  label: string;
  min: number;
  max: number;
  step: number;
}> = [
  { field: "growth", meta: "revenue_growth", label: "首年收入增速（五年逐步回落）", min: -100, max: 60, step: 0.5 },
  { field: "margin", meta: "op_margin_end", label: "第五年营业利润率", min: 5, max: 80, step: 0.5 },
  { field: "wacc", meta: "wacc", label: "WACC 折现率", min: 4, max: 20, step: 0.25 },
  { field: "terminal", meta: "terminal_growth", label: "永续增长率", min: 0.5, max: 4, step: 0.25 },
  { field: "roic", meta: "terminal_roic", label: "稳定期增量资本回报率", min: 8, max: 40, step: 1 },
];

function percent(inputs: DcfInputs, field: DraftEdit["field"]): number {
  if (field === "growth") return inputs.revenue_growth[0] * 100;
  if (field === "margin") return inputs.op_margin_end * 100;
  if (field === "wacc") return inputs.wacc * 100;
  if (field === "terminal") return inputs.terminal_growth * 100;
  return inputs.terminal_roic * 100;
}

function draftUrl(ticker: string) {
  return `/api/v1/companies/${encodeURIComponent(ticker)}/valuation-profile/draft`;
}

export function ValuationSetupCard({ ticker, gate, onConfirmed }: ValuationSetupCardProps) {
  const [source, setSource] = useState<ValuationDraft | null>(null);
  const [draft, setDraft] = useState<DcfInputs | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [loading, setLoading] = useState(true);
  const [previewing, setPreviewing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const requestSequence = useRef(0);

  const loadDraft = useCallback(async () => {
    const sequence = ++requestSequence.current;
    setLoading(true);
    setError(null);
    setAcknowledged(false);
    setConfirmed(false);
    try {
      const response = await api.fetchJson<ValuationDraft>(draftUrl(ticker));
      if (sequence !== requestSequence.current) return;
      setSource(response);
      setDraft(draftFromInputs(response.assumptions.inputs));
      setPreview(response.preview);
    } catch (reason) {
      if (sequence === requestSequence.current) setError(userErrorMessage(reason));
    } finally {
      if (sequence === requestSequence.current) setLoading(false);
    }
  }, [ticker]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadDraft(), 0);
    return () => {
      window.clearTimeout(timer);
      requestSequence.current += 1;
    };
  }, [loadDraft]);

  const edit = useCallback(async (change: DraftEdit) => {
    if (!draft || !source) return;
    const next = updateDraft(draft, change);
    const sequence = ++requestSequence.current;
    setDraft(next);
    setPreviewing(true);
    setError(null);
    try {
      const response = await api.fetchJson<Preview & { assumptions?: unknown }>(
        `/api/v1/companies/${encodeURIComponent(ticker)}/valuation/run?security_id=${encodeURIComponent(source.security_id)}&publication_id=${encodeURIComponent(source.publication_id)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(buildPreviewRequest(next, false)),
        },
      );
      if (sequence === requestSequence.current) setPreview(response);
    } catch (reason) {
      if (sequence === requestSequence.current) setError(userErrorMessage(reason));
    } finally {
      if (sequence === requestSequence.current) setPreviewing(false);
    }
  }, [draft, source, ticker]);

  const confirm = useCallback(async () => {
    if (!source || !draft || !acknowledged || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.fetchJson(`/api/v1/companies/${encodeURIComponent(ticker)}/valuation-profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          security_id: source.security_id,
          publication_id: source.publication_id,
          model_version: source.model_version,
          assumptions: buildPreviewRequest(draft).assumptions,
          confirmed: true,
        }),
      });
      setConfirmed(true);
      await onConfirmed();
    } catch (reason) {
      if (reason instanceof ApiRequestError && reason.detail.code === "VALUATION_DRAFT_STALE") {
        setError("财务发布版本已变化，请重新加载审核方案");
      } else {
        setError(userErrorMessage(reason));
      }
    } finally {
      setSubmitting(false);
    }
  }, [acknowledged, draft, onConfirmed, source, submitting, ticker]);

  if (loading) return <Card className="valuation-setup"><Spinner label="正在生成估值审核方案…" /></Card>;

  if (!source || !draft || !preview) {
    return (
      <Card className="valuation-setup card-pad" data-testid="valuation-setup-error">
        <div className="section-head"><div><span className="eyebrow">Valuation review</span><h2>无法生成估值审核方案</h2></div><Pill tone="bad">数据阻断</Pill></div>
        <div className="action-error">{error ?? gate.reason ?? "关键财务事实或发行人研究配置不足。"}</div>
        <button className="secondary-action" onClick={() => void loadDraft()}>重新加载</button>
      </Card>
    );
  }

  return (
    <Card className="valuation-setup card-pad" data-testid="valuation-setup">
      <div className="valuation-setup-head">
        <div>
          <span className="eyebrow">Valuation readiness · assumption review</span>
          <h2>审核并启用 {ticker} 估值</h2>
          <p>这是研究假设审核，不是价格预测承诺。事实输入由当前正式发布生成，仅开放五项判断供你调整。</p>
        </div>
        <Pill tone="warn">待确认</Pill>
      </div>

      <div className="valuation-identity" aria-label="估值方案身份">
        <span><small>证券</small><strong>{source.security_id}</strong></span>
        <span><small>财务发布</small><strong>{source.publication_id}</strong></span>
        <span><small>模型</small><strong>{source.model_version}</strong></span>
      </div>

      <div className="valuation-review-grid">
        <div className="valuation-review-controls">
          {controls.map((control) => {
            const value = percent(draft, control.field);
            const meta = source.assumptions.meta[control.meta];
            return (
              <div className="dcf-control" key={control.field}>
                <label htmlFor={`setup-${control.field}`}>{control.label}</label>
                <input
                  id={`setup-${control.field}`}
                  type="range"
                  min={control.min}
                  max={control.max}
                  step={control.step}
                  value={value}
                  disabled={submitting}
                  onChange={(event) => void edit({ field: control.field, percent: Number(event.target.value) } as DraftEdit)}
                />
                <output>{value.toFixed(control.step < 1 ? 2 : 1)}%</output>
                <div className="assumption-context">
                  <strong>{meta?.reason ?? "系统生成的研究假设，需人工审核。"}</strong>
                  <span>{meta?.version ?? meta?.as_of ?? "未标注版本"} · {meta?.source ?? "未标注来源"}</span>
                </div>
              </div>
            );
          })}
        </div>

        <aside className="valuation-review-preview" aria-live="polite">
          <span className="eyebrow">Scenario preview</span>
          <h3>{previewing ? "正在重算…" : "三情景参考值"}</h3>
          {(["bear", "base", "bull"] as const).map((key) => {
            const scenario = preview.scenarios[key];
            const fair = scenario?.result?.fair_value_per_share;
            return <div className={`setup-scenario setup-scenario-${key}`} key={key}><span>{scenario?.label ?? key}</span><strong>{fair == null ? "不可用" : `$${fair.toFixed(0)}`}</strong></div>;
          })}
          <p>情景用于暴露假设敏感性，不代表发生概率。</p>
        </aside>
      </div>

      {error ? <div className="action-error" data-testid="valuation-setup-error">{error} <button onClick={() => void loadDraft()}>重新加载</button></div> : null}
      {confirmed ? <div className="next-step pass"><strong>配置已确认</strong><span>正在重新读取公司能力与估值结果…</span></div> : null}

      <div className="valuation-confirm-row">
        <label>
          <input type="checkbox" checked={acknowledged} disabled={submitting || confirmed} onChange={(event) => setAcknowledged(event.target.checked)} />
          <span>我已审核该证券和本发布版本的估值假设</span>
        </label>
        <button className="primary-action" data-testid="valuation-confirm" disabled={!acknowledged || submitting || previewing || confirmed || Boolean(error)} onClick={() => void confirm()}>
          {submitting ? "正在确认…" : "确认并启用估值"}
        </button>
      </div>
    </Card>
  );
}
