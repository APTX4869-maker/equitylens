"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiRequestError, api, userErrorMessage } from "@/lib/api";
import { ValuationControls } from "@/components/valuation/ValuationControls";
import { RiskFreeSnapshot } from "@/components/valuation/RiskFreeSnapshot";
import {
  buildPreviewRequest,
  draftFromInputs,
  updateDraft,
  validateValuationDraft,
  type DcfInputs,
  type DraftEdit,
  type ValuationDraftErrors,
} from "@/lib/valuationDraft";
import { Card, Pill, Spinner } from "@/components/ui";
import type { ResearchIdentity } from "@/lib/types";

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
  risk_free_fingerprint?: string;
  assumptions: {
    inputs: DcfInputs;
    meta: Record<string, AssumptionMeta>;
  };
  preview: Preview;
};

export type ValuationSetupCardProps = {
  ticker: string;
  identity: ResearchIdentity;
  gate: { status: string; reason: string | null };
  onConfirmed: () => Promise<void> | void;
  onOpenFinancials?: () => void;
};

function draftUrl(ticker: string, identity: ResearchIdentity) {
  return `/api/v1/companies/${encodeURIComponent(ticker)}/valuation-profile/draft?security_id=${encodeURIComponent(identity.security_id)}&publication_id=${encodeURIComponent(identity.publication_id)}`;
}

export function ValuationSetupCard({ ticker, identity, gate, onConfirmed, onOpenFinancials }: ValuationSetupCardProps) {
  const securityId = identity.security_id;
  const publicationId = identity.publication_id;
  const [source, setSource] = useState<ValuationDraft | null>(null);
  const [draft, setDraft] = useState<DcfInputs | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [loading, setLoading] = useState(true);
  const [previewing, setPreviewing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [requiresMaintainer, setRequiresMaintainer] = useState(false);
  const [rawControlErrors, setRawControlErrors] = useState<ValuationDraftErrors>({});
  const [confirmed, setConfirmed] = useState(false);
  const requestSequence = useRef(0);

  const loadDraft = useCallback(async () => {
    const sequence = ++requestSequence.current;
    setLoading(true);
    setError(null);
    setRequiresMaintainer(false);
    setAcknowledged(false);
    setConfirmed(false);
    try {
      const response = await api.fetchJson<ValuationDraft>(draftUrl(ticker, {
        security_id: securityId,
        publication_id: publicationId,
      }));
      if (sequence !== requestSequence.current) return;
      setSource(response);
      setDraft(draftFromInputs(response.assumptions.inputs));
      setPreview(response.preview);
    } catch (reason) {
      if (sequence === requestSequence.current) {
        setError(userErrorMessage(reason));
        setRequiresMaintainer(reason instanceof ApiRequestError && reason.detail.code === "VALUATION_DEFAULT_UNAVAILABLE");
      }
    } finally {
      if (sequence === requestSequence.current) setLoading(false);
    }
  }, [ticker, securityId, publicationId]);

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
    if (Object.keys(validateValuationDraft(next)).length > 0) {
      setPreviewing(false);
      return;
    }
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

  const draftErrors = useMemo(
    () => draft ? validateValuationDraft(draft) : {},
    [draft]
  );
  const controlErrors = useMemo(
    () => ({ ...draftErrors, ...rawControlErrors }),
    [draftErrors, rawControlErrors]
  );
  const onRawValidityChange = useCallback((field: DraftEdit["field"], message: string | null) => {
    setRawControlErrors((current) => {
      const next = { ...current };
      if (message) next[field] = message;
      else delete next[field];
      return next;
    });
  }, []);

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
          risk_free_fingerprint: source.risk_free_fingerprint,
          confirmed: true,
        }),
      });
      setConfirmed(true);
      await onConfirmed();
    } catch (reason) {
      if (reason instanceof ApiRequestError && reason.detail.code === "VALUATION_DRAFT_STALE") {
        setError("财务发布版本已变化，请重新加载审核方案");
      } else if (reason instanceof ApiRequestError && reason.detail.code === "VALUATION_RISK_FREE_CHANGED") {
        setAcknowledged(false);
        setError("利率来源或时点已变化，请重新加载并审核");
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
        {requiresMaintainer ? <>
          <div className="action-error"><strong>需要维护者处理</strong><p>{ticker} 的公司研究配置或关键财务事实不足，当前无法生成可审核基准。等待或重复刷新不会自动解除。</p><p>下一步：维护者补充并核验公司配置与证据，适配完成后再检查审核草案。此页面不能用确认假设绕过缺失配置。</p></div>
          <details className="capability-reason"><summary>原始错误与技术原因</summary><p>{error}</p></details>
          {onOpenFinancials ? <button className="secondary-action" onClick={onOpenFinancials}>继续查看财务数据</button> : null}
        </> : <div className="action-error">{error ?? gate.reason ?? "关键财务事实或发行人研究配置不足。"}</div>}
        <button className="secondary-action" onClick={() => void loadDraft()}>{requiresMaintainer ? "适配完成后重新检查" : "重新加载"}</button>
      </Card>
    );
  }

  const assumptionNote = (key: string) => {
    const meta = source.assumptions.meta[key];
    return (
      <div className="assumption-context">
        <strong>{meta?.reason ?? "系统生成的研究假设，需人工审核。"}</strong>
        <span>{meta?.version ?? meta?.as_of ?? "未标注版本"} · {meta?.source ?? "未标注来源"}</span>
      </div>
    );
  };

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

      <RiskFreeSnapshot meta={source.assumptions.meta.risk_free} />
      <div className="valuation-review-grid">
        <div className="valuation-review-controls">
          <ValuationControls
            draft={draft}
            disabled={submitting}
            errors={controlErrors}
            onEdit={(change) => void edit(change)}
            onRawValidityChange={onRawValidityChange}
            notes={{
              growth: assumptionNote("revenue_growth"),
              margin: assumptionNote("op_margin_end"),
              wacc: assumptionNote("wacc"),
              terminal: assumptionNote("terminal_growth"),
              roic: assumptionNote("terminal_roic"),
            }}
          />
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
        <button className="primary-action" data-testid="valuation-confirm" disabled={!acknowledged || submitting || previewing || confirmed || Boolean(error) || Object.keys(controlErrors).length > 0} onClick={() => void confirm()}>
          {submitting ? "正在确认…" : "确认并启用估值"}
        </button>
      </div>
    </Card>
  );
}
